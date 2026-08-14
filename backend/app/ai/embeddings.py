from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from abc import ABC, abstractmethod

from openai import OpenAI

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    model_name: str

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada para generar embeddings.")
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model_name = settings.openai_embedding_model
        self.dimensions = settings.embedding_dimensions

    def embed(self, text: str) -> list[float]:
        started = time.perf_counter()
        response = self.client.embeddings.create(
            model=self.model_name,
            input=text,
            dimensions=self.dimensions,
        )
        logger.info(
            "Embedding model call completed",
            extra={
                "feature": "incident_embedding",
                "model": self.model_name,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "input_tokens": getattr(response.usage, "prompt_tokens", None),
            },
        )
        return response.data[0].embedding


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable local embeddings for tests and offline demonstrations."""

    model_name = "deterministic-hash-v1"

    def __init__(self, dimensions: int = 1536):
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"\w+", text.casefold())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    if settings.llm_provider == "mock":
        return DeterministicEmbeddingProvider(settings.embedding_dimensions)
    if settings.llm_provider == "openai":
        return OpenAIEmbeddingProvider(settings)
    raise ValueError("El proveedor configurado no soporta embeddings.")
