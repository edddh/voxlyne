"""
Voxlyne - RAG text chunking.

Deliberately simple character-window chunker, not token-aware: good
enough for the embedding model's 8k-token input limit at these chunk
sizes (a 1200-char chunk is well under that for any language), and avoids
pulling in a tokenizer dependency just for this. Splits on paragraph/
sentence boundaries where possible so a chunk doesn't cut mid-sentence,
falls back to a hard cut only if a single "paragraph" is itself longer
than chunk_size.
"""

import re
from typing import List

DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 150


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> List[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(para) <= chunk_size:
            current = para
        else:
            # A single paragraph longer than chunk_size on its own -
            # hard-split it with overlap.
            for i in range(0, len(para), chunk_size - overlap):
                chunks.append(para[i : i + chunk_size])
            current = ""

    if current:
        chunks.append(current)

    return chunks
