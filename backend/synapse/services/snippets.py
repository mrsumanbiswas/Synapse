"""Query-biased snippets: the densest window of matching words, as safe text segments."""

from __future__ import annotations

from ..text.tokenizer import spans


def make_snippet(text: str, stems: set[str], max_words: int = 42) -> list[dict]:
    """Return ``[{"t": text, "h": highlighted}, ...]``; the UI renders it without HTML."""
    text = " ".join((text or "").split())
    if not text:
        return []
    words = list(spans(text))
    if not words:
        return [{"t": text[:320], "h": False}]
    hits = [1 if term and term in stems else 0 for _, _, term in words]
    window = min(max_words, len(words))
    current = sum(hits[:window])
    best_start, best_hits = 0, current
    for start in range(1, len(words) - window + 1):
        current += hits[start + window - 1] - hits[start - 1]
        if current > best_hits:
            best_start, best_hits = start, current
    # Start a little before the first hit so the sentence has some context.
    if best_hits and best_start > 0:
        first_hit = next(i for i in range(best_start, best_start + window) if hits[i])
        best_start = max(0, min(best_start, first_hit - 6))
    chosen = words[best_start : best_start + window]

    segments: list[dict] = []
    if best_start > 0:
        segments.append({"t": "… ", "h": False})
    cursor = chosen[0][0]
    for (start, end, term), hit in zip(chosen, hits[best_start : best_start + window]):
        if start > cursor:
            segments.append({"t": text[cursor:start], "h": False})
        segments.append({"t": text[start:end], "h": bool(hit)})
        cursor = end
    tail_end = chosen[-1][1]
    if tail_end < len(text):
        trailing = text[tail_end : tail_end + 1]
        if trailing in ".,;:!?)":
            segments.append({"t": trailing, "h": False})
            tail_end += 1
        if tail_end < len(text):
            segments.append({"t": " …", "h": False})

    merged: list[dict] = []
    for segment in segments:  # join neighbours with the same flag to keep payloads small
        if merged and merged[-1]["h"] == segment["h"]:
            merged[-1]["t"] += segment["t"]
        else:
            merged.append(dict(segment))
    return merged
