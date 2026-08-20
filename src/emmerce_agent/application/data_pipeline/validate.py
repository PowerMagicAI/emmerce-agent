"""Listing QA: required fields, price bounds, category consistency."""

from __future__ import annotations

from dataclasses import dataclass, field

from emmerce_agent.application.data_pipeline.classify import ALLOWED_CATEGORIES, ClassifyResult
from emmerce_agent.application.data_pipeline.extract import ExtractedFields
from emmerce_agent.application.data_pipeline.vision import image_text_mismatch


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    field: str


@dataclass(slots=True)
class ValidationResult:
    listing_id: str
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    method: str = "rule"


def validate_listing(
    *,
    listing_id: str,
    title: str,
    listed_price: float | None,
    extracted: ExtractedFields,
    classified: ClassifyResult,
    image_text: str = "",
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    text = (title or "").strip()
    if len(text) < 4:
        issues.append(ValidationIssue("TITLE_TOO_SHORT", "标题过短或为空", "title"))

    price = listed_price if listed_price is not None else extracted.price_from_title
    if price is None:
        issues.append(ValidationIssue("PRICE_MISSING", "缺少有效价格", "price"))
    elif price <= 0:
        issues.append(ValidationIssue("PRICE_NON_POSITIVE", "价格必须为正数", "price"))
    elif price >= 100_000:
        issues.append(ValidationIssue("PRICE_OUT_OF_BOUNDS", "价格超出合理上限", "price"))

    if extracted.banned:
        issues.append(
            ValidationIssue("BANNED_WORD", "标题含违禁/仿冒词: " + ",".join(extracted.banned), "title")
        )
    if image_text_mismatch(text, image_text):
        issues.append(ValidationIssue("IMAGE_TEXT_MISMATCH", "主图文本与标题重叠过低，疑似图文不符", "image"))

    if classified.category and classified.category not in ALLOWED_CATEGORIES:
        issues.append(ValidationIssue("CATEGORY_UNKNOWN", "类目不在允许枚举", "category"))
    if classified.method == "needs_llm":
        issues.append(ValidationIssue("CATEGORY_AMBIGUOUS", classified.reason, "category"))
    if classified.conflict_with_listed:
        issues.append(ValidationIssue("CATEGORY_CONFLICT", classified.reason, "category"))

    return ValidationResult(listing_id=listing_id, ok=not issues, issues=issues)
