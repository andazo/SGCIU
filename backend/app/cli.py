from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from pydantic import ValidationError

from app.agents.gateway import LocalToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent
from app.db import SessionLocal
from app.schemas import IntakeSubmissionRequest
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.intake import IntakeService
from app.services.reviews import ReviewNotFoundError, ReviewService
from app.services.semantic import SemanticIncidentService


def _yes(prompt: str) -> bool:
    return input(prompt).strip().casefold() in {"s", "si", "sí", "y", "yes"}


def _optional(prompt: str) -> str | None:
    value = input(prompt).strip()
    return value or None


def run_citizen() -> None:
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
                    name=_optional("Nombre opcional: "),
                    email=_optional("Correo opcional: "),
                    phone=_optional("Teléfono opcional: "),
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


def _manage_reviews(db) -> None:
    service = ReviewService(db)
    reviews = service.list("pending")
    if not reviews:
        print("No hay revisiones pendientes.")
        return
    for review in reviews:
        print(f"Revisión {review.id} | incidente #{review.incident_id} | {review.reason}")
    if not _yes("¿Desea resolver una revisión? [s/N]: "):
        return
    try:
        review_id = int(input("ID de revisión: "))
        notes = input("Notas de resolución: ").strip()
        review = service.resolve(review_id, notes)
    except (ValueError, ReviewNotFoundError):
        print("No se pudo resolver la revisión.")
        return
    print(f"Revisión {review.id} resuelta.")


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
        "4": "Ver clusters candidatos",
        "5": "Preguntar al agente operativo",
        "6": "Gestionar revisiones humanas",
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
                _print_clusters(db)
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
