"""Security helpers used by tool gateway and audit."""

from __future__ import annotations

import re
from dataclasses import dataclass

from emmerce_agent.domain.security.injection import PromptInjectionDetector

PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
ID_CARD_RE = re.compile(r"(?<!\d)(\d{15}|\d{17}[\dXx])(?!\d)")
AMOUNT_INLINE_RE = re.compile(
    r"((?:成交金额|实付|支付金额|订单金额)[:：]\s*)(\d[\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

_DEFAULT_INJECTION = PromptInjectionDetector()


@dataclass
class DesensitizeResult:
    text: str
    redacted_phones: int = 0
    redacted_amounts: int = 0
    redacted_id_cards: int = 0


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "****"


def mask_id_card(value: str) -> str:
    if len(value) < 8:
        return "****"
    return f"{value[:4]}**********{value[-4:]}"


def desensitize_text(text: str) -> DesensitizeResult:
    phones = 0
    ids = 0
    amounts = 0

    def _p(m: re.Match[str]) -> str:
        nonlocal phones
        phones += 1
        return mask_phone(m.group(1))

    def _id(m: re.Match[str]) -> str:
        nonlocal ids
        ids += 1
        return mask_id_card(m.group(1))

    def _a(m: re.Match[str]) -> str:
        nonlocal amounts
        amounts += 1
        return f"{m.group(1)}[AGGREGATE]"

    out = PHONE_RE.sub(_p, text)
    out = ID_CARD_RE.sub(_id, out)
    out = AMOUNT_INLINE_RE.sub(_a, out)
    return DesensitizeResult(
        text=out,
        redacted_phones=phones,
        redacted_amounts=amounts,
        redacted_id_cards=ids,
    )


def detect_prompt_injection(user_text: str) -> bool:
    """Backward-compatible wrapper around PromptInjectionDetector."""
    return _DEFAULT_INJECTION.is_blocked(user_text)
