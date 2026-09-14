from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url


def _database_url_for_local_proxy(database_url: str) -> str:
    """Convert Cloud Run's Unix-socket URL to the local Cloud SQL proxy endpoint."""
    url = make_url(database_url)
    socket_path = url.query.get("host")
    if not socket_path or not socket_path.startswith("/cloudsql/"):
        raise ValueError(
            "DATABASE_URL no utiliza un socket de Cloud SQL; no se requiere "
            "--local-cloud-sql-proxy."
        )
    query = dict(url.query)
    query.pop("host", None)
    return url.set(host="127.0.0.1", port=5432, query=query).render_as_string(hide_password=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ejecuta localmente los 90 escenarios híbridos de evaluación de SGCIU."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Confirma la ejecución con OpenAI y la inserción de los casos sintéticos.",
    )
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="Requerido cuando la configuración local apunta a una base de datos productiva.",
    )
    parser.add_argument(
        "--run-id",
        help="Identificador reproducible de la corrida. Se genera uno si se omite.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/hybrid-evaluation"),
        help="Directorio local para el reporte JSON que alimenta el libro Excel.",
    )
    parser.add_argument(
        "--local-cloud-sql-proxy",
        action="store_true",
        help=(
            "Convierte la URL de socket de Cloud Run al proxy TCP local "
            "(127.0.0.1:5432) antes de inicializar la aplicación."
        ),
    )
    args = parser.parse_args()
    if not args.execute:
        parser.error("Use --execute para iniciar una corrida que crea datos sintéticos.")

    if args.local_cloud_sql_proxy:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            parser.error("--local-cloud-sql-proxy requiere DATABASE_URL.")
        try:
            os.environ["DATABASE_URL"] = _database_url_for_local_proxy(database_url)
        except ValueError as exc:
            parser.error(str(exc))

    # These imports must remain after the optional URL rewrite: app.db creates the engine.
    from app.ai.intake import get_intake_provider
    from app.config import get_settings
    from app.db import SessionLocal
    from app.evaluation.hybrid import OpenAICitizenActor, run_hybrid_evaluation, write_report

    settings = get_settings()
    if settings.is_production and not args.confirm_production:
        parser.error("La base configurada es productiva; agregue --confirm-production.")
    actor = OpenAICitizenActor(settings)
    intake_provider = get_intake_provider(settings)
    run_id = args.run_id or f"hybrid-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    with SessionLocal() as db:
        report = run_hybrid_evaluation(
            db,
            actor=actor,
            intake_provider=intake_provider,
            run_id=run_id,
        )
    report_path = args.output_dir / run_id / "hybrid_evaluation_report.json"
    write_report(report_path, report)
    print(report_path.resolve())


if __name__ == "__main__":
    main()
