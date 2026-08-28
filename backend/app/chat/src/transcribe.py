from __future__ import annotations

import asyncio
import tempfile
from typing import Optional

from faster_whisper import WhisperModel


class TranscriptionError(Exception):
    """Fichier audio illisible, corrompu, ou format non décodable."""


class Transcriber:
    """Wrapper autour de faster-whisper — chargement paresseux, hors event loop."""

    def __init__(self, model_size: str = "small", device: str = "cpu") -> None:
        self._model_size = model_size
        self._device = device
        self._model: Optional[WhisperModel] = None
        self._lock = asyncio.Lock()

    async def _get_model(self) -> WhisperModel:
        if self._model is None:
            async with self._lock:
                if self._model is None:
                    self._model = await asyncio.to_thread(
                        WhisperModel,
                        self._model_size,
                        device=self._device,
                        compute_type="int8",
                    )
        return self._model

    async def transcribe(self, content: bytes, suffix: str = ".webm") -> str:
        if not content:
            raise TranscriptionError("Fichier audio vide.")

        model = await self._get_model()

        def _run() -> str:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
                tmp.write(content)
                tmp.flush()
                try:
                    segments, _info = model.transcribe(tmp.name, beam_size=5)
                    return " ".join(seg.text.strip() for seg in segments).strip()
                except Exception as exc:
                    raise TranscriptionError(
                        f"Audio illisible ou corrompu : {exc}"
                    ) from exc

        return await asyncio.to_thread(_run)
