"""
Gemini embedding wrapper using the google-genai SDK (v1 API).

Model : text-embedding-004  (768-dimensional output)
SDK   : google-genai  (import: from google import genai)

Two task types are used:
  - "RETRIEVAL_DOCUMENT" when embedding chunks during ingestion.
  - "RETRIEVAL_QUERY"    when embedding a user query at retrieval time.

Batching + retry are handled here so callers don't need to worry about rate limits.
"""

from __future__ import annotations

import time
from typing import Literal

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768

TaskType = Literal["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY"]


class GeminiEmbedder:
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)

    # ── single text ───────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=30))
    def embed_one(self, text: str, task_type: TaskType = "RETRIEVAL_DOCUMENT") -> list[float]:
        result = self._client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=768
            ),
        )
        return result.embeddings[0].values

    def embed_query(self, text: str) -> list[float]:
        return self.embed_one(text, task_type="RETRIEVAL_QUERY")

    # ── batch ─────────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=30))
    def _embed_batch_raw(
        self, texts: list[str], task_type: TaskType
    ) -> list[list[float]]:
        result = self._client.models.embed_content(
            model=EMBED_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=768
            ),
        )
        return [e.values for e in result.embeddings]

    def embed_batch(
        self,
        texts: list[str],
        task_type: TaskType = "RETRIEVAL_DOCUMENT",
        batch_size: int = 20,
        delay_seconds: float = 1.0,
    ) -> list[list[float]]:
        """
        Embed a list of texts in batches, respecting Gemini rate limits.
        Returns embeddings in the same order as the input.
        """
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings.extend(self._embed_batch_raw(batch, task_type))
            if i + batch_size < len(texts):
                time.sleep(delay_seconds)
        return embeddings

    # ── generation ────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def generate_json(self, prompt: str, model: str = "models/gemini-flash-latest") -> dict:
        """Generate a JSON response from the LLM."""
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
        except Exception as e:
            print(f"DEBUG: Gemini generate_content failed: {e}")
            raise e
        try:
            import json
            return json.loads(response.text)
        except Exception:
            # Fallback for older models or malformed JSON
            import re
            match = re.search(r"\{.*\}", response.text, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise ValueError(f"Could not parse JSON from LLM: {response.text}")
