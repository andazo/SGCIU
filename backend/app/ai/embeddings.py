from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from openai import OpenAI, OpenAIError

from app.config import Settings, get_settings
from app.costs import estimate_embedding_cost
from app.monitoring import record_ai_call

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    input_tokens: int = 0
    estimated_cost_usd: float = 0.0


class EmbeddingProvider(ABC):
    model_name: str

    @property
    def last_usage(self) -> EmbeddingUsage:
        return EmbeddingUsage()

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        model_name: str | None = None,
        dimensions: int | None = None,
        feature: str = "incident_embedding",
        client: OpenAI | None = None,
    ):
        if not settings.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY no está configurada para generar embeddings.")
        self.client = client or OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=2,
        )
        self.settings = settings
        self.model_name = model_name or settings.openai_embedding_model
        self.dimensions = dimensions or settings.embedding_dimensions
        self.feature = feature
        self._last_usage = EmbeddingUsage()

    @property
    def last_usage(self) -> EmbeddingUsage:
        return self._last_usage

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self._last_usage = EmbeddingUsage()
        if not texts:
            return []
        started = time.perf_counter()
        try:
            response = self.client.embeddings.create(
                model=self.model_name,
                input=texts,
                dimensions=self.dimensions,
            )
        except OpenAIError as exc:
            record_ai_call(
                feature=self.feature,
                model=self.model_name,
                status="error",
                duration_seconds=time.perf_counter() - started,
            )
            raise RuntimeError("No se pudieron generar embeddings con OpenAI.") from exc
        input_tokens = int(getattr(response.usage, "prompt_tokens", 0) or 0)
        duration_seconds = time.perf_counter() - started
        estimated_cost_usd = estimate_embedding_cost(
            input_tokens,
            self.settings,
            model_name=self.model_name,
        )
        self._last_usage = EmbeddingUsage(
            input_tokens=input_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        record_ai_call(
            feature=self.feature,
            model=self.model_name,
            status="success",
            duration_seconds=duration_seconds,
            input_tokens=input_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        logger.info(
            "Embedding model call completed",
            extra={
                "feature": self.feature,
                "model": self.model_name,
                "embeddings": len(texts),
                "latency_ms": round(duration_seconds * 1000, 2),
                "input_tokens": input_tokens,
                "estimated_cost_usd": estimated_cost_usd,
            },
        )
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    return OpenAIEmbeddingProvider(settings)


def get_legal_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    return OpenAIEmbeddingProvider(
        settings,
        model_name=settings.legal_rag_embedding_model,
        dimensions=settings.legal_rag_embedding_dimensions,
        feature="legal_rag_embedding",
    )
