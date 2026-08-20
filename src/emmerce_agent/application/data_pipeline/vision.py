"""Title-vs-image consistency: token overlap, not a real CV model."""

from __future__ import annotations

from emmerce_agent.infrastructure.memory.stores import _jaccard, _tokenize


def image_text_mismatch(title: str, image_text: str, *, min_overlap: float = 0.08) -> bool:
    """True when both sides have content but almost no shared tokens (likely 图文不符)."""
    t = (title or "").strip()
    img = (image_text or "").strip()
    if len(t) < 4 or len(img) < 4:
        return False
    score = _jaccard(_tokenize(t), _tokenize(img))
    return score < min_overlap
