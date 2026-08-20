"""Force deterministic stub LLM in tests regardless of local .env."""

from __future__ import annotations

import os

# Must run before Settings.from_env / create_app load dotenv defaults.
os.environ["EMMERCE_LLM_PROVIDER"] = "stub"
os.environ["EMMERCE_SESSION_BACKEND"] = "memory"
