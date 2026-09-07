from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class ModelPrice:
    """Public list prices in USD per one million tokens."""

    input_per_million: float
    output_per_million: float = 0.0
    cached_input_per_million: float | None = None


# Snapshot reviewed on 2026-09-06 against the official OpenAI pricing page.
# Keep model aliases explicit so a model switch cannot silently reuse another rate.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gpt-5.6-sol": ModelPrice(4.0, 20.0, 0.40),
    "gpt-5.6-terra": ModelPrice(2.0, 12.0, 0.20),
    "gpt-5.6-luna": ModelPrice(0.20, 1.20, 0.02),
    "gpt-5.4-mini": ModelPrice(0.75, 4.50, 0.075),
    "text-embedding-3-small": ModelPrice(0.02),
    "text-embedding-3-large": ModelPrice(0.13),
}

MODEL_ALIASES = {
    "gpt-5.6": "gpt-5.6-sol",
}


def model_price(model_name: str) -> ModelPrice | None:
    """Resolve aliases and dated model snapshots to a known public price."""

    normalized = MODEL_ALIASES.get(model_name.strip().lower(), model_name.strip().lower())
    if normalized in MODEL_PRICES:
        return MODEL_PRICES[normalized]
    matches = [
        (name, price)
        for name, price in MODEL_PRICES.items()
        if re.fullmatch(rf"{re.escape(name)}-\d{{4}}-\d{{2}}-\d{{2}}", normalized)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


def _validate_tokens(*token_counts: int) -> None:
    if any(token_count < 0 for token_count in token_counts):
        raise ValueError("Los conteos de tokens no pueden ser negativos.")


def estimate_llm_cost(
    input_tokens: int,
    output_tokens: int,
    settings: Settings,
    *,
    model_name: str | None = None,
    cached_input_tokens: int = 0,
) -> float:
    """Estimate a model call while honoring explicit environment overrides."""

    _validate_tokens(input_tokens, output_tokens, cached_input_tokens)
    if cached_input_tokens > input_tokens:
        raise ValueError("Los tokens de entrada en caché no pueden superar la entrada total.")

    price = model_price(model_name or settings.openai_model)
    configured_input = settings.llm_input_cost_per_million
    configured_output = settings.llm_output_cost_per_million
    if min(configured_input, configured_output) < 0:
        raise ValueError("Las tarifas configuradas no pueden ser negativas.")
    if price is None and (configured_input == 0 or configured_output == 0):
        raise ValueError(
            f"No existe una tarifa completa para {model_name or settings.openai_model}."
        )
    input_rate = configured_input or (price.input_per_million if price else 0.0)
    output_rate = configured_output or (price.output_per_million if price else 0.0)
    cached_rate = (
        configured_input
        if configured_input
        else (
            price.cached_input_per_million
            if price and price.cached_input_per_million is not None
            else input_rate
        )
    )

    regular_input_tokens = input_tokens - cached_input_tokens
    cost = regular_input_tokens / 1_000_000 * input_rate
    cost += cached_input_tokens / 1_000_000 * cached_rate
    cost += output_tokens / 1_000_000 * output_rate
    return round(cost, 8)


def estimate_embedding_cost(
    input_tokens: int,
    settings: Settings,
    *,
    model_name: str | None = None,
) -> float:
    _validate_tokens(input_tokens)
    price = model_price(model_name or settings.openai_embedding_model)
    if settings.embedding_cost_per_million < 0:
        raise ValueError("La tarifa configurada no puede ser negativa.")
    if price is None and settings.embedding_cost_per_million == 0:
        raise ValueError(
            f"No existe una tarifa para {model_name or settings.openai_embedding_model}."
        )
    rate = settings.embedding_cost_per_million or (
        price.input_per_million if price else 0.0
    )
    return round(input_tokens / 1_000_000 * rate, 8)
