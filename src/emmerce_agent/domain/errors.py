"""Domain errors with stable machine-readable codes."""

from __future__ import annotations


class DomainError(Exception):
    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.message = message


class PermissionDenied(DomainError):
    code = "PERMISSION_DENIED"


class ValidationFailed(DomainError):
    code = "VALIDATION_FAILED"


class ToolExecutionError(DomainError):
    code = "TOOL_ERROR"

    def __init__(self, message: str, *, code: str = "TOOL_ERROR", retryable: bool = False):
        super().__init__(message, code=code)
        self.retryable = retryable


class RateLimited(ToolExecutionError):
    def __init__(self, message: str = "查询过于频繁，请稍后再试"):
        super().__init__(message, code="RATE_LIMITED", retryable=True)


class HallucinationDetected(DomainError):
    code = "HALLUCINATION_DETECTED"


class TurnBudgetExceeded(DomainError):
    code = "TURN_BUDGET_EXCEEDED"

    def __init__(self, message: str = "本轮分析资源已达上限，请缩小问题范围后重试", *, used: int = 0, limit: int = 0):
        super().__init__(message, code="TURN_BUDGET_EXCEEDED")
        self.used = used
        self.limit = limit
        self.retryable = False
