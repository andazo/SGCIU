from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from openai import OpenAI

from app.config import Settings, get_settings
from app.costs import estimate_embedding_cost

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    model_name: str

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada para generar embeddings.")
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=2,
        )
        self.settings = settings
        self.model_name = settings.openai_embedding_model
        self.dimensions = settings.embedding_dimensions

    def embed(self, text: str) -> list[float]:
        started = time.perf_counter()
        response = self.client.embeddings.create(
            model=self.model_name,
            input=text,
            dimensions=self.dimensions,
        )
        input_tokens = int(getattr(response.usage, "prompt_tokens", 0) or 0)
        logger.info(
            "Embedding model call completed",
            extra={
                "feature": "incident_embedding",
                "model": self.model_name,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "input_tokens": input_tokens,
                "estimated_cost_usd": estimate_embedding_cost(input_tokens, self.settings),
            },
        )
        return response.data[0].embedding


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    return OpenAIEmbeddingProvider(settings)
