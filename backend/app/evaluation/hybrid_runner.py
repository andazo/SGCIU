from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from app.ai.intake import get_intake_provider
from app.config import get_settings
from app.db import SessionLocal
from app.evaluation.hybrid import OpenAICitizenActor, run_hybrid_evaluation, write_report


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
    args = parser.parse_args()
    if not args.execute:
        parser.error("Use --execute para iniciar una corrida que crea datos sintéticos.")
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
