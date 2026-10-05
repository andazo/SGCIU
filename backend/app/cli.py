from __future__ import annotations

import argparse
import asyncio
import getpass
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.agents.gateway import LocalToolGateway, connect_mcp_gateway
from app.agents.operational import OperationalAgent
from app.auth import AuthService
from app.db import SessionLocal
from app.rag.corpus import LegalCorpusIndexer
from app.schemas import CitizenProfile, IntakeSubmissionRequest
from app.services.incidents import IncidentNotFoundError, IncidentService
from app.services.intake import EMERGENCY_NOTICE, IntakeService
from app.services.legal_rag import LegalRAGService
from app.services.semantic import SemanticIncidentService, incident_time_reference


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
                print(
                    "Aviso: el reporte tendrá fiabilidad limitada y requerirá "
                    "verificación de datos."
                )
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


def _print_recurrent_patterns(db) -> None:
    service = SemanticIncidentService(db)
    patterns = service.list_recurrent_patterns()
    if not patterns:
        print(
            "No se detectaron patrones recurrentes en los últimos "
            f"{service.settings.cluster_time_window_days} días."
        )
        return

    threshold = datetime.now(UTC) - timedelta(days=service.settings.cluster_time_window_days)
    print(
        f"\nPatrones recurrentes de los últimos {service.settings.cluster_time_window_days} días"
    )
    for pattern in patterns:
        members = [
            member
            for member in pattern.members
            if member.incident and incident_time_reference(member.incident).value >= threshold
        ]
        if not members:
            continue
        scores = [member.similarity_score for member in members]
        print(f"\nPatrón #{pattern.id}: {pattern.label}")
        print(f"Incidentes relacionados: {len(members)}")
        print(f"Similitud promedio: {sum(scores) / len(scores):.3f}")
        print("Incidentes:")
        for member in sorted(
            members,
            key=lambda item: incident_time_reference(item.incident).value,
        ):
            incident = member.incident
            data = incident.ai_extracted_data or {}
            print(
                f"  #{incident.id} | {incident_time_reference(incident).value} | "
                f"{data.get('categoria_preliminar')} | "
                f"{data.get('distrito')} | {data.get('direccion_exacta')} | "
                f"score={member.similarity_score:.3f} | {member.match_reason}"
            )


def _manage_clusters(db) -> None:
    while True:
        print("\nAgrupación semántica y recurrente")
        print("1. Ver clusters candidatos")
        print("2. Recalcular embeddings y clusters")
        print("3. Ver agrupaciones recurrentes")
        print("0. Volver")
        selection = input("Seleccione una opción: ").strip()
        if selection == "0":
            return
        if selection == "1":
            _print_clusters(db)
            continue
        if selection == "3":
            _print_recurrent_patterns(db)
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
    print("Fuentes normativas citadas:", response.legal_citations or "ninguna")
    print("Trace ID:", response.trace_id)
    for step in response.steps:
        print(
            f"  paso {step.step}: {step.tool_name} | "
            f"éxito={step.success} | resultados={step.result_count}"
        )


def _print_legal_corpus_status(db) -> None:
    status = LegalCorpusIndexer(db).status()
    print(f"\nCorpus normativo SGCIU {status.corpus_version}")
    print(
        f"Documentos: {status.indexed_documents}/{status.documents_in_manifest} | "
        f"embeddings indexados: {status.indexed_embeddings}"
    )
    for document in status.documents:
        print(
            f"- {document.title} | páginas={document.page_count} | "
            f"embeddings={document.embeddings}"
        )
    if status.known_gaps:
        print("Vacíos documentales conocidos:")
        for gap in status.known_gaps:
            print("  -", gap)


def _ask_legal_rag(db) -> None:
    query = input("Consulta normativa: ").strip()
    if not query:
        return
    try:
        response = LegalRAGService(db).answer(query)
    except RuntimeError as exc:
        print(f"No se pudo completar la consulta normativa: {exc}")
        return
    print("\nAsistente normativo SGCIU:\n", response.answer, sep="")
    print(
        f"\nEmbeddings recuperados: {response.retrieved_embeddings} | "
        f"embeddings indexados: {response.indexed_embeddings}"
    )
    print("Fuentes verificables:")
    if not response.citations:
        print("  Ninguna; la respuesta se marcó con evidencia insuficiente.")
    for citation in response.citations:
        articles = ", ".join(citation.article_references) or "sin artículo detectado"
        printed = (
            f" (numeración impresa {citation.printed_page_label})"
            if citation.printed_page_label
            else ""
        )
        print(
            f"  [{citation.source_id}] {citation.document_title} | página PDF "
            f"{citation.pdf_page}{printed} | {articles} | chunk #{citation.chunk_id}"
        )
        classifications = ", ".join(citation.allowed_classifications)
        print(
            f"      alcance={citation.authority_scope} | fuerza={citation.legal_force} | "
            f"clasificaciones permitidas={classifications}"
        )
        print(
            f"      ranking: semántico={citation.semantic_score:.3f}, "
            f"léxico={citation.lexical_score:.3f}, híbrido={citation.fusion_score:.3f}"
        )
    for caveat in response.caveats:
        print("Aviso:", caveat)
    print("Trace ID:", response.trace_id)
    print("Esta orientación no sustituye criterio jurídico institucional.")


def _manage_legal_rag(db) -> None:
    while True:
        print("\nConsulta normativa RAG")
        print("1. Ver estado del corpus")
        print("2. Indexar o actualizar documentos")
        print("3. Consultar normativa")
        print("0. Volver")
        selection = input("Seleccione una opción: ").strip()
        if selection == "0":
            return
        if selection == "1":
            _print_legal_corpus_status(db)
        elif selection == "2":
            print(
                "Se validarán los PDF y se crearán embeddings solo para documentos "
                "nuevos o modificados. Esta acción utiliza OpenAI."
            )
            if not _yes("¿Desea continuar? [s/N]: "):
                continue
            result = LegalCorpusIndexer(db).index_all(
                progress=lambda position, total, key, status: print(
                    f"  [{position}/{total}] {key}: {status}"
                )
            )
            print(
                f"Indexación finalizada: documentos actualizados={result.documents_indexed}, "
                f"sin cambios={result.documents_skipped}, fallidos={result.documents_failed}, "
                f"embeddings creados={result.embeddings_created}."
            )
            for failure in result.failures:
                print("  Error:", failure)
        elif selection == "3":
            _ask_legal_rag(db)
        else:
            print("Opción inválida.")


def run_admin(transport: str) -> None:
    options = {
        "1": "Listar incidentes",
        "2": "Consultar detalle",
        "3": "Buscar relacionados",
        "4": "Agrupación semántica y recurrente",
        "5": "Preguntar al agente operativo",
        "6": "Consultar normativa (RAG)",
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
                _manage_legal_rag(db)
            else:
                print("Opción inválida.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interfaz terminal de SGCIU")
    parser.add_argument("--role", choices=("citizen", "admin"))
    parser.add_argument("--transport", choices=("local", "mcp"), default="local")
    parser.add_argument("--create-user", metavar="USERNAME")
    parser.add_argument("--user-role", choices=("police", "administrative"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.create_user:
        if not args.user_role:
            raise SystemExit("--user-role es obligatorio con --create-user.")
        password = getpass.getpass("Contraseña (mínimo 12 caracteres): ")
        confirmation = getpass.getpass("Repita la contraseña: ")
        if password != confirmation:
            raise SystemExit("Las contraseñas no coinciden.")
        with SessionLocal() as db:
            user = AuthService(db).create_user(args.create_user, password, args.user_role)
        print(f"Usuario {user.username} creado con rol {user.role}.")
        return
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
