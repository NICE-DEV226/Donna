"""
Reranker cross-encoder ONNX (BGE-reranker-v2-m3, multilingue) — affine le
classement des candidats fusionnés (vecteur + BM25) avant de les renvoyer.

Chargement paresseux et hors event loop (le modèle + tokenizer sont lourds à
charger — ~544 Mo quantifiés). Pas de torch : tokenizer via `transformers`
(mode tokenizer seul, sans backend ML) + inference via `onnxruntime`.
"""

from __future__ import annotations

import asyncio
from typing import Any

_MODEL_REPO = "onnx-community/bge-reranker-v2-m3-ONNX"
_MODEL_FILE = "onnx/model_quantized.onnx"


class Reranker:
    def __init__(self) -> None:
        self._session = None
        self._tokenizer = None
        self._lock = asyncio.Lock()

    async def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        async with self._lock:
            if self._session is not None:
                return
            self._session, self._tokenizer = await asyncio.to_thread(self._load)

    @staticmethod
    def _load() -> tuple[Any, Any]:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(_MODEL_REPO)
        model_path = hf_hub_download(_MODEL_REPO, filename=_MODEL_FILE)
        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        return session, tokenizer

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int,
        text_key: str = "text",
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        await self._ensure_loaded()
        scores = await asyncio.to_thread(self._score, query, [c[text_key] for c in candidates])

        for candidate, score in zip(candidates, scores):
            candidate["rerank_score"] = score

        ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
        return ranked[:top_k]

    def _score(self, query: str, texts: list[str]) -> list[float]:
        import numpy as np

        pairs = [(query, text) for text in texts]
        inputs = self._tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        onnx_inputs = {k: v for k, v in inputs.items() if k in {i.name for i in self._session.get_inputs()}}
        logits = self._session.run(None, onnx_inputs)[0]
        # Sortie du reranker : un seul logit par paire — score de pertinence brut.
        return [float(x) for x in np.asarray(logits).reshape(-1)]
