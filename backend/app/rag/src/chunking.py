from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]

    sentences = _SENTENCE_SPLIT.split(paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)

    # Phrase elle-même trop longue (pas de ponctuation) : découpage brut.
    final: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            final.append(piece)
        else:
            final.extend(piece[i : i + max_chars] for i in range(0, len(piece), max_chars))
    return final


def chunk_text(content: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """
    Découpage récursif simple : paragraphes → phrases → brut, avec chevauchement
    entre chunks consécutifs pour préserver le contexte aux frontières.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    if not paragraphs:
        return []

    units: list[str] = []
    for paragraph in paragraphs:
        units.extend(_split_long(paragraph, chunk_size))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}".strip() if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = f"{current[-overlap:]}\n\n{unit}".strip() if overlap else unit
        else:
            current = unit

    if current:
        chunks.append(current)

    return chunks
