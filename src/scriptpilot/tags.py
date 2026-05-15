from __future__ import annotations


def normalize_tags(raw: str) -> list[str]:
    """Split comma-separated tags; strip, lowercase, drop empties, dedupe (preserve first-seen order)."""
    seen: set[str] = set()
    out: list[str] = []
    for piece in raw.split(","):
        t = piece.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
