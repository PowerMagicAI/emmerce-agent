"""Rule-first field extraction from listing titles (LLM only for leftovers)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PRICE_RE = re.compile(r"(?:[¥￥]|价格[:：]?\s*)(\d+(?:\.\d{1,2})?)")
SPEC_RE = re.compile(r"(\d+(?:\.\d+)?\s?(?:ml|g|kg|L|件|盒|支|瓶))", re.I)
BRAND_RE = re.compile(r"[【\[]([^】\]]{1,12})[】\]]")
COLOR_RE = re.compile(r"(黑色|白色|红色|蓝色|绿色|粉色|紫色|灰色|米色|豆沙色)")
SIZE_RE = re.compile(r"(XXL|XL|XS|[SML])码|均码")
MATERIAL_RE = re.compile(r"(纯棉|棉|真丝|聚酯|尼龙|皮革)")
BANNED = ("高仿", "A货", "精仿", "假货", "走私")


@dataclass(slots=True)
class ExtractedFields:
    listing_id: str
    title: str
    brand: str | None
    spec: str | None
    price_from_title: float | None
    color: str | None = None
    size: str | None = None
    material: str | None = None
    banned: list[str] = field(default_factory=list)
    method: str = "rule"


def extract_listing(*, listing_id: str, title: str) -> ExtractedFields:
    text = (title or "").strip()
    brand = None
    m = BRAND_RE.search(text)
    if m:
        brand = m.group(1).strip()
    spec = None
    sm = SPEC_RE.search(text)
    if sm:
        spec = sm.group(1).replace(" ", "")
    price = None
    pm = PRICE_RE.search(text)
    if pm:
        price = float(pm.group(1))
    color = None
    cm = COLOR_RE.search(text)
    if cm:
        color = cm.group(1)
    size = None
    zm = SIZE_RE.search(text)
    if zm:
        size = zm.group(0)
    material = None
    mm = MATERIAL_RE.search(text)
    if mm:
        material = mm.group(1)
    banned = [w for w in BANNED if w in text]
    return ExtractedFields(
        listing_id=listing_id,
        title=text,
        brand=brand,
        spec=spec,
        price_from_title=price,
        color=color,
        size=size,
        material=material,
        banned=banned,
        method="rule",
    )
