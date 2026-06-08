"""Local embedding generation using sentence-transformers."""

from __future__ import annotations

import os

import numpy as np
from sentence_transformers import SentenceTransformer


class Embedder:
    """Generates embeddings for repository search text using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", hf_token: str | None = None):
        self.model_name = model_name
        self.hf_token = hf_token
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            token = self.hf_token or os.environ.get("HF_TOKEN")
            if token:
                self._model = SentenceTransformer(
                    self.model_name, token=token
                )
            else:
                self._model = SentenceTransformer(self.model_name)
        return self._model

    @property
    def dimension(self) -> int:
        return self.model.get_embedding_dimension()

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.
            batch_size: Batch size for encoding.

        Returns:
            List of embedding vectors as float lists.
        """
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        return self.embed_texts([text])[0]

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine similarity between two vectors."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
