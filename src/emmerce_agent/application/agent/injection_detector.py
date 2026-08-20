"""Re-export for application layer convenience."""

from emmerce_agent.domain.security.injection import InjectionHit, PromptInjectionDetector

__all__ = ["InjectionHit", "PromptInjectionDetector"]
