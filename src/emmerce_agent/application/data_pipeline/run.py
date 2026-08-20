"""Product data production pipeline: extract → classify → validate."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from emmerce_agent.application.data_pipeline.ocr import fake_ocr
from emmerce_agent.application.data_pipeline.classify import classify_listing
from emmerce_agent.application.data_pipeline.extract import extract_listing
from emmerce_agent.application.data_pipeline.validate import validate_listing
from emmerce_agent.application.ports import OcrSample, ProductListing


@dataclass(slots=True)
class PipelineStats:
    total: int = 0
    passed: int = 0
    failed: int = 0
    needs_llm: int = 0
    issue_counts: dict[str, int] = field(default_factory=dict)


def run_product_pipeline(
    listings: list[ProductListing],
    ocr_lookup: dict[str, OcrSample] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    stats = PipelineStats(total=len(listings))
    lookup = ocr_lookup or {}
    for item in listings:
        ocr = fake_ocr(item, lookup.get(item.listing_id))
        image_text = ocr.ocr_text or item.image_text
        extracted = extract_listing(listing_id=item.listing_id, title=item.title)
        classified = classify_listing(
            listing_id=item.listing_id,
            title=item.title,
            listed_category=item.listed_category,
        )
        validated = validate_listing(
            listing_id=item.listing_id,
            title=item.title,
            listed_price=item.listed_price,
            extracted=extracted,
            classified=classified,
            image_text=image_text,
        )
        if classified.method == "needs_llm":
            stats.needs_llm += 1
        if validated.ok:
            stats.passed += 1
        else:
            stats.failed += 1
            for iss in validated.issues:
                stats.issue_counts[iss.code] = stats.issue_counts.get(iss.code, 0) + 1
        rows.append(
            {
                "listing_id": item.listing_id,
                "sku": item.sku,
                "title": item.title,
                "listed_price": item.listed_price,
                "listed_category": item.listed_category,
                "image_text": image_text,
                "ocr": {"text": ocr.ocr_text, "confidence": ocr.confidence, "source": ocr.source, "method": ocr.method},
                "extracted": asdict(extracted),
                "classified": asdict(classified),
                "validation": {
                    "ok": validated.ok,
                    "issues": [asdict(i) for i in validated.issues],
                },
            }
        )
    return {
        "method": "rule_first",
        "note": "规则处理明确样本；needs_llm 为灰色样本，生产可交 LLM 二次分类",
        "stats": asdict(stats),
        "rows": rows,
    }
