"""Fake OCR: lookup table + listing.image_text. Stand-in for a vision model."""

from __future__ import annotations

from dataclasses import dataclass

from emmerce_agent.application.ports import OcrSample, ProductListing


@dataclass(slots=True)
class OcrResult:
    listing_id: str
    ocr_text: str
    confidence: float
    source: str
    method: str = "fake_ocr"


def fake_ocr(item: ProductListing, sample: OcrSample | None = None) -> OcrResult:
    if sample and (sample.ocr_text or "").strip():
        return OcrResult(
            listing_id=item.listing_id,
            ocr_text=sample.ocr_text.strip(),
            confidence=sample.confidence,
            source="ocr_table",
        )
    text = (item.image_text or "").strip()
    if text:
        return OcrResult(
            listing_id=item.listing_id,
            ocr_text=text,
            confidence=0.7,
            source="listing.image_text",
        )
    return OcrResult(listing_id=item.listing_id, ocr_text="", confidence=0.0, source="empty")
