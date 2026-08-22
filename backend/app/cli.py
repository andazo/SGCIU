from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from pydantic import ValidationError

from app.agents.gateway import LocalToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent
from app.db import SessionLocal
from app.schemas import CitizenProfile, IntakeSubmissionRequest
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.intake import EMERGENCY_NOTICE, IntakeService
from app.services.reviews import HighlightNotFoundError, ReviewNotFoundError, ReviewService
from app.services.semantic import SemanticIncidentService


def _yes(prompt: str) -> bool:
    return input(prompt).strip().casefold() in {"s", "si", "sí", "y", "yes"}


def _optional(prompt: str) -> str | None:
    value = input(prompt).strip()
    return value or None


def _collect_citizen_profile() -> CitizenProfile | None:
    print("\nInformación general del ciudadano")
    print("La identificación y los datos de contacto son opcionales.")
    while True:
        name = input("Nombre completo: ").strip()
        if name.casefold() in {"salir", "cancelar"}:
            return None
        identification = _optional("Identificación opcional: ")
        email = _optional("Correo opcional: ")
        phone = _optional("Teléfono opcional: ")
        try:
            return CitizenProfile(
                name=name,
                identification=identification,
                email=email,
                phone=phone,
            )
        except ValidationError as exc:
            messages = "; ".join(error["msg"] for error in exc.errors())
            print(f"Revise la información general: {messages}")


def run_citizen() -> None:
    print("\nAviso importante SGCIU")
    print(EMERGENCY_NOTICE)
    profile = _collect_citizen_profile()
    if profile is None:
        print("Registro cancelado; no se creó ninguna denuncia.")
        return
    with SessionLocal() as db:
        try:
            service = IntakeService(db)
        except RuntimeError as exc:
            print(f"No se pudo iniciar el asistente: {exc}")
            return
        session = service.start()
        print("\nAsistente SGCIU:", session.messages[0]["content"])
        while True:
            message = input("\nCiudadano: ").strip()
            if message.casefold() in {"salir", "cancelar"}:
                print("Registro cancelado; no se creó ninguna denuncia.")
                return
            if not message:
                continue
            try:
                response = service.add_user_message(session.id, message)
            except Exception as exc:
                print(f"No se pudo analizar el mensaje: {type(exc).__name__}")
                continue
            print("Asistente SGCIU:", response.messages[-1].content)
            if response.requires_human_review:
                print("Aviso: el reporte será marcado para revisión humana.")
            if not response.is_complete:
                continue
            print("\nResumen propuesto:")
            print(response.summary_text)
            if not _yes("¿Confirma que la información es correcta? [s/N]: "):
                print("Puede continuar escribiendo para corregir la información.")
                continue
            try:
                payload = IntakeSubmissionRequest(
                    name=profile.name,
                    identification=profile.identification,
                    email=profile.email,
                    phone=profile.phone,
                    truth_confirmation=True,
                    data_usage_consent=_yes(
                        "¿Acepta el uso institucional de los datos de la denuncia? [s/N]: "
                    ),
                )
                incident = service.submit(session.id, payload)
            except ValidationError as exc:
                print("Los datos de contacto o consentimiento no son válidos:", exc)
                continue
            print(f"Denuncia registrada con ID {incident.id}.")
            return


def _print_incidents(db) -> None:
    incidents, total = IncidentService(db).list(limit=100)
    print(f"\nIncidentes registrados: {total}")
    for incident in incidents:
        data = incident.ai_extracted_data or {}
        print(
            f"#{incident.id} | {data.get('categoria_preliminar')} | "
            f"{data.get('distrito')} | {data.get('direccion_exacta')} | {incident.status}"
        )


def _print_incident(db) -> None:
    try:
        incident_id = int(input("ID del incidente: "))
        incident = IncidentService(db).get(incident_id)
    except (ValueError, IncidentNotFoundError):
        print("Incidente no encontrado.")
        return
    data = incident.ai_extracted_data or {}
    print(f"\nIncidente #{incident.id}")
    print("Nombre:", incident.name or "No proporcionado")
    print("Identificación:", incident.identification or "No proporcionada")
    print("Correo:", incident.email or "No proporcionado")
    print("Teléfono:", incident.phone or "No proporcionado")
    print("Resumen:", incident.ai_summary_text or "Sin resumen")
    for field in (
        "categoria_preliminar",
        "distrito",
        "direccion_exacta",
        "tipo_lugar",
        "fecha_hora_aproximada",
    ):
        print(f"{field}: {data.get(field)}")
    print("Revisión humana:", "sí" if incident.requires_human_review else "no")


def _print_related(db) -> None:
    try:
        incident_id = int(input("ID del incidente: "))
        incident = IncidentService(db).get(incident_id)
    except (ValueError, IncidentNotFoundError):
        print("Incidente no encontrado.")
        return
    related = SemanticIncidentService(db).find_related(incident)
    if not related:
        print("No se encontraron incidentes relacionados.")
        return
    for item in related:
        print(
            f"#{item.incident.id} | score={item.similarity_score:.3f} | "
            f"{', '.join(item.match_reasons)}"
        )


def _print_clusters(db) -> None:
    clusters = SemanticIncidentService(db).list_clusters()
    if not clusters:
        print("No hay clusters candidatos.")
        return
    for cluster in clusters:
        members = ", ".join(f"#{member.incident_id}" for member in cluster.members)
        print(f"Cluster {cluster.id}: {cluster.label} [{cluster.status}] -> {members}")


def _manage_clusters(db) -> None:
    while True:
        print("\nClusters y embeddings")
        print("1. Ver clusters candidatos")
        print("2. Recalcular embeddings y clusters")
        print("0. Volver")
        selection = input("Seleccione una opción: ").strip()
        if selection == "0":
            return
        if selection == "1":
            _print_clusters(db)
            continue
        if selection != "2":
            print("Opción inválida.")
            continue
        print(
            "Esta acción volverá a generar los embeddings con OpenAI y reconstruirá "
            "los clusters candidatos."
        )
        if not _yes("¿Desea continuar? [s/N]: "):
            continue
        result = SemanticIncidentService(db).recalculate_all()
        print("\nRecálculo semántico completado")
        print("Incidentes encontrados:", result.incidents_found)
        print("Embeddings actualizados:", result.embeddings_updated)
        print("Embeddings fallidos:", result.embeddings_failed)
        print("Clusters reconstruidos:", result.clusters_rebuilt)
        print("Miembros agrupados:", result.cluster_members)


def _print_recommended_actions(actions: list[dict[str, str]]) -> None:
    if not actions:
        print("Acciones sugeridas: ninguna")
        return
    print("Acciones sugeridas:")
    for action in actions:
        print(f"  - {action.get('code')}: {action.get('rationale')}")


def _manage_quality_reviews(db) -> None:
    service = ReviewService(db)
    reviews = service.list_active()
    if not reviews:
        print("No hay revisiones de calidad activas.")
        return
    for review in reviews:
        print(
            f"\nRevisión {review.id} | incidente #{review.incident_id} | "
            f"{review.review_type} | {review.status}"
        )
        print("Motivo:", review.reason)
        print("Análisis IA:", review.ai_summary or "Sin análisis detallado")
        print("Problemas detectados:", "; ".join(review.quality_issues) or "No detallados")
        print("Contacto disponible:", "sí" if review.contact_available else "no")
        _print_recommended_actions(review.recommended_actions)
    if not _yes("¿Desea gestionar una revisión? [s/N]: "):
        return
    try:
        review_id = int(input("ID de revisión: "))
        print("1. Iniciar revisión")
        print("2. Resolver")
        print("3. Descartar revisión por información insuficiente")
        print("4. Escalar")
        action = {"1": "start", "2": "resolve", "3": "dismiss", "4": "escalate"}.get(
            input("Acción: ").strip()
        )
        if action is None:
            raise ValueError
        notes = input("Notas de la decisión: ").strip()
        if len(notes) < 3:
            raise ValueError
        review = service.transition_review(review_id, action, notes)
    except (ValueError, ReviewNotFoundError):
        print("No se pudo actualizar la revisión.")
        return
    print(f"Revisión {review.id} actualizada a {review.status}.")


def _manage_highlights(db) -> None:
    service = ReviewService(db)
    highlights = service.list_active_highlights()
    if not highlights:
        print("No hay resaltados operativos activos.")
        return
    for highlight in highlights:
        print(
            f"\nResaltado {highlight.id} | incidente #{highlight.incident_id} | "
            f"atención={highlight.attention_level} | {highlight.status}"
        )
        print("Razones:", "; ".join(highlight.reasons))
        print("Resumen IA:", highlight.ai_summary)
        print("Precauciones sugeridas:")
        for precaution in highlight.recommended_precautions:
            print("  -", precaution)
        if highlight.evidence:
            print("Evidencia utilizada:", "; ".join(highlight.evidence))
    if not _yes("¿Desea gestionar un resaltado? [s/N]: "):
        return
    try:
        highlight_id = int(input("ID del resaltado: "))
        print("1. Iniciar análisis")
        print("2. Resolver")
        print("3. Escalar")
        action = {"1": "start", "2": "resolve", "3": "escalate"}.get(input("Acción: ").strip())
        if action is None:
            raise ValueError
        notes = input("Notas de la decisión: ").strip()
        if len(notes) < 3:
            raise ValueError
        highlight = service.transition_highlight(highlight_id, action, notes)
    except (ValueError, HighlightNotFoundError):
        print("No se pudo actualizar el resaltado.")
        return
    print(f"Resaltado {highlight.id} actualizado a {highlight.status}.")


def _manage_reviews(db) -> None:
    while True:
        print("\nResaltados y revisiones de calidad")
        print("1. Gestionar resaltados operativos")
        print("2. Gestionar revisiones de calidad")
        print("3. Analizar con IA incidentes pendientes")
        print("0. Volver")
        selection = input("Seleccione una opción: ").strip()
        if selection == "0":
            return
        if selection == "1":
            _manage_highlights(db)
        elif selection == "2":
            _manage_quality_reviews(db)
        elif selection == "3":
            if not _yes("¿Analizar los incidentes pendientes con OpenAI? [s/N]: "):
                continue
            pending, completed, failed = ReviewService(db).assess_pending_incidents(
                lambda position, total, incident_id: print(
                    f"  [{position}/{total}] incidente #{incident_id} procesado"
                )
            )
            print(
                f"Análisis finalizado: pendientes={pending}, completados={completed}, "
                f"fallidos={failed}."
            )
        else:
            print("Opción inválida.")


async def _ask_agent(db, transport: str) -> None:
    query = input("Consulta operativa: ").strip()
    if not query:
        return
    if transport == "mcp":
        async with connect_mcp_gateway() as gateway:
            response = await OperationalAgent(gateway).run(query)
    else:
        response = await OperationalAgent(LocalToolGateway(db)).run(query)
    print("\nAgente:", response.answer)
    print("Incidentes citados:", response.incident_citations or "ninguno")
    print("Trace ID:", response.trace_id)
    for step in response.steps:
        print(
            f"  paso {step.step}: {step.tool_name} | "
            f"éxito={step.success} | resultados={step.result_count}"
        )


def run_admin(transport: str) -> None:
    options = {
        "1": "Listar incidentes",
        "2": "Consultar detalle",
        "3": "Buscar relacionados",
        "4": "Clusters y recálculo de embeddings",
        "5": "Preguntar al agente operativo",
        "6": "Gestionar resaltados y revisiones de calidad",
        "0": "Salir",
    }
    with SessionLocal() as db:
        while True:
            print("\nAdministración SGCIU")
            for key, label in options.items():
                print(f"{key}. {label}")
            selection = input("Seleccione una opción: ").strip()
            if selection == "0":
                return
            if selection == "1":
                _print_incidents(db)
            elif selection == "2":
                _print_incident(db)
            elif selection == "3":
                _print_related(db)
            elif selection == "4":
                _manage_clusters(db)
            elif selection == "5":
                asyncio.run(_ask_agent(db, transport))
            elif selection == "6":
                _manage_reviews(db)
            else:
                print("Opción inválida.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interfaz terminal de SGCIU")
    parser.add_argument("--role", choices=("citizen", "admin"))
    parser.add_argument("--transport", choices=("local", "mcp"), default="local")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    role = args.role
    if role is None:
        selected = input("Seleccione rol: [1] ciudadano, [2] administrador: ").strip()
        role = "admin" if selected == "2" else "citizen"
    if role == "admin":
        run_admin(args.transport)
    else:
        run_citizen()


if __name__ == "__main__":
    main()
