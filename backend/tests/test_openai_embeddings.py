from dataclasses import replace
from types import SimpleNamespace

from app.ai.embeddings import OpenAIEmbeddingProvider
from app.config import get_settings


class EmbeddingsDouble:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ],
            usage=SimpleNamespace(prompt_tokens=10),
        )


class OpenAIClientDouble:
    def __init__(self):
        self.embeddings = EmbeddingsDouble()


def test_openai_embedding_provider_batches_inputs_and_restores_api_order():
    client = OpenAIClientDouble()
    provider = OpenAIEmbeddingProvider(
        replace(get_settings(), embedding_cost_per_million=0.02),
        model_name="test-model",
        dimensions=2,
        feature="test",
        client=client,
    )

    vectors = provider.embed_many(["primero", "segundo"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert client.embeddings.calls[0] == {
        "model": "test-model",
        "input": ["primero", "segundo"],
        "dimensions": 2,
    }
