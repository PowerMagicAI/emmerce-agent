"""Category classification: keyword rules first; ambiguous samples marked for LLM."""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_CATEGORIES = ("数码", "美妆", "女装", "食品", "家居")

KEYWORD_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("数码", ("手机", "耳机", "充电器", "平板", "键盘", "鼠标", "音箱")),
    ("美妆", ("面膜", "口红", "粉底", "精华", "防晒", "眉笔")),
    ("女装", ("连衣裙", "半身裙", "衬衫", "T恤", "牛仔裤")),
    ("食品", ("饼干", "坚果", "茶叶", "咖啡", "牛奶")),
    ("家居", ("毛巾", "收纳", "枕头", "垃圾袋")),
)


@dataclass(slots=True)
class ClassifyResult:
    listing_id: str
    category: str | None
    confidence: float
    method: str  # rule | needs_llm
    conflict_with_listed: bool = False
    reason: str = ""


def classify_listing(
    *,
    listing_id: str,
    title: str,
    listed_category: str = "",
) -> ClassifyResult:
    title = title or ""
    hit: str | None = None
    for cat, kws in KEYWORD_MAP:
        if any(k in title for k in kws):
            hit = cat
            break

    listed = listed_category.strip()
    if hit:
        conflict = bool(listed and listed in ALLOWED_CATEGORIES and listed != hit)
        return ClassifyResult(
            listing_id=listing_id,
            category=hit,
            confidence=0.55 if conflict else 0.92,
            method="rule",
            conflict_with_listed=conflict,
            reason="标题关键词与挂靠类目不一致" if conflict else "标题关键词命中",
        )

    if listed in ALLOWED_CATEGORIES:
        return ClassifyResult(
            listing_id=listing_id,
            category=listed,
            confidence=0.6,
            method="rule",
            reason="标题无关键词，沿用商家挂靠类目",
        )

    return ClassifyResult(
        listing_id=listing_id,
        category=None,
        confidence=0.2,
        method="needs_llm",
        reason="规则无法判断，应交 LLM 处理灰色样本",
    )
