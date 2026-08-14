from __future__ import annotations

from app.config import Settings


def estimate_llm_cost(input_tokens: int, output_tokens: int, settings: Settings) -> float:
    input_cost = input_tokens / 1_000_000 * settings.llm_input_cost_per_million
    output_cost = output_tokens / 1_000_000 * settings.llm_output_cost_per_million
    return round(input_cost + output_cost, 8)


def estimate_embedding_cost(input_tokens: int, settings: Settings) -> float:
    return round(input_tokens / 1_000_000 * settings.embedding_cost_per_million, 8)
