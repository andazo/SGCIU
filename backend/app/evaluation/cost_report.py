from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from app.costs import model_price

DEFAULT_SCENARIO_PATH = Path(__file__).resolve().parents[2] / "evaluation" / "cost_scenario.json"
USD_PRECISION = Decimal("0.0001")


def _usd(value: Decimal | float | int) -> float:
    return float(Decimal(str(value)).quantize(USD_PRECISION, rounding=ROUND_HALF_UP))


def load_cost_scenario(path: Path = DEFAULT_SCENARIO_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as scenario_file:
        scenario = json.load(scenario_file)
    if not scenario.get("version") or scenario.get("currency") != "USD":
        raise ValueError("El escenario debe tener versión y moneda USD.")
    return scenario


def _ai_line(workload: dict[str, Any]) -> dict[str, Any]:
    calls = int(workload["calls"])
    input_tokens = calls * int(workload["input_tokens_per_call"])
    output_tokens = calls * int(workload.get("output_tokens_per_call", 0))
    cached_tokens = calls * int(workload.get("cached_input_tokens_per_call", 0))
    if min(calls, input_tokens, output_tokens, cached_tokens) < 0 or cached_tokens > input_tokens:
        raise ValueError(f"Uso de tokens inválido en {workload['key']}.")

    price = model_price(str(workload["model"]))
    if price is None:
        raise ValueError(f"No existe tarifa para el modelo {workload['model']}.")
    if workload["kind"] == "embedding" and output_tokens:
        raise ValueError("Los workloads de embeddings no deben declarar tokens de salida.")
    if workload["kind"] not in {"llm", "embedding"}:
        raise ValueError(f"Tipo de workload desconocido: {workload['kind']}.")

    regular_tokens = input_tokens - cached_tokens
    cached_rate = price.cached_input_per_million or price.input_per_million
    million = Decimal(1_000_000)
    cost = Decimal(regular_tokens) / million * Decimal(str(price.input_per_million))
    cost += Decimal(cached_tokens) / million * Decimal(str(cached_rate))
    cost += Decimal(output_tokens) / million * Decimal(str(price.output_per_million))
    return {
        "key": workload["key"],
        "description": workload["description"],
        "model": workload["model"],
        "calls": calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": _usd(cost),
    }


def _infrastructure_line(resource: dict[str, Any]) -> dict[str, Any]:
    quantity = float(resource["quantity"])
    free_quantity = float(resource.get("free_quantity", 0))
    unit_price = float(resource["unit_price_usd"])
    if min(quantity, free_quantity, unit_price) < 0:
        raise ValueError(f"Tarifa o cantidad inválida en {resource['key']}.")
    billable_quantity = max(0.0, quantity - free_quantity)
    return {
        **resource,
        "billable_quantity": billable_quantity,
        "estimated_cost_usd": _usd(Decimal(str(billable_quantity)) * Decimal(str(unit_price))),
    }


def build_cost_report(
    scenario: dict[str, Any], *, as_of: date | None = None
) -> dict[str, Any]:
    monthly_ai = [_ai_line(item) for item in scenario["monthly_ai_workloads"]]
    one_time_ai = [_ai_line(item) for item in scenario["one_time_ai_workloads"]]
    infrastructure = [
        _infrastructure_line(item) for item in scenario["monthly_infrastructure"]
    ]
    ai_total = _usd(sum(Decimal(str(item["estimated_cost_usd"])) for item in monthly_ai))
    infrastructure_total = _usd(
        sum(Decimal(str(item["estimated_cost_usd"])) for item in infrastructure)
    )
    monthly_total = _usd(Decimal(str(ai_total)) + Decimal(str(infrastructure_total)))
    budget = float(scenario["budget"]["monthly_warning_usd"])
    valid_until = date.fromisoformat(scenario["pricing_valid_until"])
    pricing_is_current = (as_of or date.today()) <= valid_until
    return {
        "scenario_version": scenario["version"],
        "reviewed_at": scenario["reviewed_at"],
        "pricing_valid_until": scenario["pricing_valid_until"],
        "pricing_is_current": pricing_is_current,
        "currency": scenario["currency"],
        "monthly_ai": monthly_ai,
        "monthly_infrastructure": infrastructure,
        "one_time_ai": one_time_ai,
        "totals": {
            "monthly_ai_usd": ai_total,
            "monthly_infrastructure_usd": infrastructure_total,
            "monthly_estimate_usd": monthly_total,
            "one_time_ai_usd": _usd(
                sum(Decimal(str(item["estimated_cost_usd"])) for item in one_time_ai)
            ),
            "monthly_warning_usd": budget,
            "within_warning_budget": monthly_total <= budget,
        },
        "sources": scenario["sources"],
    }


def render_text(report: dict[str, Any]) -> str:
    rows = [
        f"Escenario SGCIU {report['scenario_version']} (USD, revisado {report['reviewed_at']})",
        f"Tarifas válidas hasta: {report['pricing_valid_until']}",
        "",
        "IA mensual:",
    ]
    rows.extend(
        f"  {item['key']:<30} ${item['estimated_cost_usd']:>8.4f}"
        for item in report["monthly_ai"]
    )
    rows.append("Infraestructura mensual:")
    rows.extend(
        f"  {item['key']:<30} ${item['estimated_cost_usd']:>8.4f}"
        for item in report["monthly_infrastructure"]
    )
    totals = report["totals"]
    rows.extend(
        [
            "",
            f"Total mensual estimado: ${totals['monthly_estimate_usd']:.2f}",
            f"Coste IA único inicial: ${totals['one_time_ai_usd']:.2f}",
            f"Umbral de advertencia: ${totals['monthly_warning_usd']:.2f}",
        ]
    )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera la estimación versionada de costes SGCIU.")
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO_PATH)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Retorna un código no cero cuando se supera el umbral mensual.",
    )
    args = parser.parse_args()
    report = build_cost_report(load_cost_scenario(args.scenario))
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.as_json else render_text(report))
    check_failed = (
        not report["totals"]["within_warning_budget"] or not report["pricing_is_current"]
    )
    return int(args.check and check_failed)


if __name__ == "__main__":
    raise SystemExit(main())
