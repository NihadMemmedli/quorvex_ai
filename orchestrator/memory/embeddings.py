"""
Embeddings Module

Handles text embeddings using OpenAI's text-embedding-3-small model.
"""

import hashlib
import math
import os

from openai import OpenAI

from .config import get_config


class LocalHashEmbeddingClient:
    """Deterministic local fallback for memory search when OpenAI is not configured."""

    def __init__(self, dimension: int | None = None):
        config = get_config()
        self.dimension = dimension or config.embedding_dimension
        self.model = f"local-hash-{self.dimension}"
        self.api_key = None

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = [token for token in text.lower().split() if token]
        if not tokens:
            tokens = [text.lower() or "empty"]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self.embed(query)


class EmbeddingClient:
    """Client for generating text embeddings using OpenAI"""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize the embedding client.

        Args:
            api_key: OpenAI API key (defaults to environment variable)
            model: Embedding model name (defaults to text-embedding-3-small)
        """
        config = get_config()

        self.api_key = api_key or config.openai_api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or config.embedding_model

        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)

    def embed(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            List of embedding values
        """
        try:
            response = self.client.embeddings.create(model=self.model, input=text)
            return response.data[0].embedding
        except Exception as e:
            raise RuntimeError(f"Failed to generate embedding: {e}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        try:
            response = self.client.embeddings.create(model=self.model, input=texts)
            return [item.embedding for item in response.data]
        except Exception as e:
            raise RuntimeError(f"Failed to generate batch embeddings: {e}")

    def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.

        Args:
            query: Search query text

        Returns:
            Query embedding vector
        """
        return self.embed(query)


# Global embedding client instance
_embedding_client: EmbeddingClient | LocalHashEmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient | LocalHashEmbeddingClient:
    """Get the global embedding client"""
    global _embedding_client
    if _embedding_client is None:
        config = get_config()
        api_key = config.openai_api_key or os.getenv("OPENAI_API_KEY")
        if api_key:
            _embedding_client = EmbeddingClient(api_key=api_key)
        else:
            _embedding_client = LocalHashEmbeddingClient()
    return _embedding_client
