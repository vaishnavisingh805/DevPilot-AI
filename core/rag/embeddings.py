"""Deterministic, Local Code Embedding Function for ChromaDB.

Produces dense, L2-normalized 128-dimensional embedding vectors from code
identifiers, AST symbol signatures, and semantic comments with zero network
downloads and zero API quota consumption.
"""

import hashlib
import re
from typing import List
import numpy as np
from chromadb import Documents, EmbeddingFunction, Embeddings


class DeterministicCodeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Generates deterministic dense vector representations of code tokens."""

    def __init__(self, vector_dim: int = 128):
        self.vector_dim = vector_dim
        # Tokenizer regex: splits words, camelCase, snake_case, and identifiers
        self.token_regex = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[0-9]+|[a-zA-Z_]+")

    @staticmethod
    def name() -> str:
        return "deterministic_code_embedding"

    def get_config(self) -> dict:
        return {"vector_dim": self.vector_dim}

    @classmethod
    def build_from_config(cls, config: dict) -> "DeterministicCodeEmbeddingFunction":
        return cls(vector_dim=config.get("vector_dim", 128))

    def _tokenize_code(self, text: str) -> List[str]:
        """Extracts normalized code tokens including camelCase and snake_case components."""
        raw_tokens = self.token_regex.findall(text.lower())
        tokens = []
        for t in raw_tokens:
            if len(t) >= 2:
                tokens.append(t)
        return tokens

    def _embed_single(self, text: str) -> List[float]:
        """Maps a single code document into a normalized dense vector."""
        tokens = self._tokenize_code(text)
        vec = np.zeros(self.vector_dim, dtype=np.float32)

        if not tokens:
            # Non-empty fallback vector for empty input
            vec[0] = 1.0
            return vec.tolist()

        # Feature hashing (hashing trick) with term frequency
        for token in tokens:
            # Primary index via md5
            h_int = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
            idx = h_int % self.vector_dim

            # Secondary sign hash via sha256 to minimize collision bias
            sign_int = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:4], 16)
            sign = 1.0 if (sign_int % 2 == 0) else -1.0

            # Boost importance for short identifier tokens (likely method/class names)
            weight = 1.5 if len(token) <= 12 else 1.0
            vec[idx] += sign * weight

        # Apply L2 normalization
        norm = np.linalg.norm(vec)
        if norm > 1e-6:
            vec = vec / norm
        else:
            vec[0] = 1.0

        return vec.tolist()

    def __call__(self, input: Documents) -> Embeddings:
        """Embeds a batch of documents into list of float lists."""
        return [self._embed_single(doc) for doc in input]


# Default singleton embedding function
code_embedding_function = DeterministicCodeEmbeddingFunction(vector_dim=128)
