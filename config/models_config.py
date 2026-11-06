"""Model pricing tables, token calculation rates, error classifications, and bounded retry policies.

Implements production-grade LLM governance:
1. Strict error taxonomy: QuotaExceededError, RateLimitError, ModelTimeoutError, TransientProviderError.
2. Bounded exponential backoff with zero infinite loops.
3. Supported model catalog and dynamic resolution.
4. Thread-safe token consumption and financial expenditure tracking.
"""

import time
import threading
from typing import Dict, Any, Optional, Callable, TypeVar
from pydantic import BaseModel, Field
from config.settings import settings

T = TypeVar("T")


class ModelPricing(BaseModel):
    prompt_cost_per_1k_tokens: float
    completion_cost_per_1k_tokens: float


# Official published Gemini & standard LLM rate cards (per 1K tokens)
MODEL_PRICING_TABLE: Dict[str, ModelPricing] = {
    "gemini-3.8-flash": ModelPricing(
        prompt_cost_per_1k_tokens=0.00010,
        completion_cost_per_1k_tokens=0.00040,
    ),
    "gemini-2.0-flash": ModelPricing(
        prompt_cost_per_1k_tokens=0.00010,
        completion_cost_per_1k_tokens=0.00040,
    ),
    "gemini-1.5-pro": ModelPricing(
        prompt_cost_per_1k_tokens=0.00125,
        completion_cost_per_1k_tokens=0.00500,
    ),
    "gemini-1.5-flash": ModelPricing(
        prompt_cost_per_1k_tokens=0.000075,
        completion_cost_per_1k_tokens=0.00030,
    ),
    "gpt-4o": ModelPricing(
        prompt_cost_per_1k_tokens=0.00500,
        completion_cost_per_1k_tokens=0.01500,
    ),
    "gpt-4o-mini": ModelPricing(
        prompt_cost_per_1k_tokens=0.00015,
        completion_cost_per_1k_tokens=0.00060,
    ),
}

# Catalog of supported models with operational profiles
SUPPORTED_MODELS: Dict[str, Dict[str, Any]] = {
    "gemini-3.8-flash": {
        "provider": "google",
        "tier": "frontier_fast",
        "context_window": 1048576,
        "default_rpm": 15,
        "production_ready": True,
    },
    "gemini-2.0-flash": {
        "provider": "google",
        "tier": "stable_fast",
        "context_window": 1048576,
        "default_rpm": 15,
        "production_ready": True,
    },
    "gemini-1.5-pro": {
        "provider": "google",
        "tier": "reasoning_pro",
        "context_window": 2097152,
        "default_rpm": 2,
        "production_ready": True,
    },
    "gemini-1.5-flash": {
        "provider": "google",
        "tier": "efficient_flash",
        "context_window": 1048576,
        "default_rpm": 15,
        "production_ready": True,
    },
    "gpt-4o": {
        "provider": "openai",
        "tier": "frontier_pro",
        "context_window": 128000,
        "default_rpm": 500,
        "production_ready": False,
    },
}


# ============================================================================
# Explicit Gemini Provider Error Hierarchy
# ============================================================================

class GeminiProviderError(Exception):
    """Base exception for Gemini provider communication and runtime failures."""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class QuotaExceededError(GeminiProviderError):
    """Raised when API quota or token budget is exhausted (HTTP 429 / RESOURCE_EXHAUSTED)."""
    pass


class RateLimitError(GeminiProviderError):
    """Raised when temporary rate limits (RPM/TPM) are triggered."""
    pass


class ModelTimeoutError(GeminiProviderError):
    """Raised when an API call exceeds the configured execution timeout."""
    pass


class TransientProviderError(GeminiProviderError):
    """Raised when temporary network or 5xx server errors occur."""
    pass


def classify_gemini_error(exc: BaseException) -> GeminiProviderError:
    """Inspects an exception and classifies it into an explicit GeminiProviderError."""
    if isinstance(exc, GeminiProviderError):
        return exc
    err_str = f"{type(exc).__name__}: {str(exc)}".lower()

    # 1. Quota exhaustion (Never retry immediately)
    quota_indicators = [
        "resource_exhausted",
        "resource has been exhausted",
        "quota exceeded",
        "quota_exhausted",
        "exceeded your current quota",
        "check quota",
    ]
    if any(q in err_str for q in quota_indicators):
        return QuotaExceededError(f"Gemini API Quota Exhausted: {str(exc)}", status_code=429)

    # 2. Rate limiting (Too many requests)
    if "429" in err_str or "rate limit" in err_str or "ratelimit" in err_str or "too many requests" in err_str:
        return RateLimitError(f"Gemini API Rate Limit Triggered: {str(exc)}", status_code=429)

    # 3. Timeout failures
    if "timeout" in err_str or "timed out" in err_str or "deadline exceeded" in err_str:
        return ModelTimeoutError(f"Gemini API Request Timed Out: {str(exc)}", status_code=408)

    # 4. Transient network and 5xx server errors
    transient_indicators = [
        "503", "service unavailable", "502", "bad gateway", "500", "internal server error",
        "connection reset", "connection refused", "broken pipe",
    ]
    if any(s in err_str for s in transient_indicators):
        return TransientProviderError(f"Transient Gemini Server Error: {str(exc)}", status_code=503)

    return GeminiProviderError(f"Gemini Provider Failure: {str(exc)}")


def bounded_retry(
    func: Callable[[], T],
    max_retries: int = 2,
    initial_backoff: float = 1.0,
    backoff_factor: float = 2.0,
    max_backoff: float = 8.0,
    timeout_seconds: float = 30.0,
) -> T:
    """Executes a callable with strict bounding to prevent infinite loops:
    
    1. Zero retries on QuotaExceededError (halts immediately to protect quota).
    2. Exponential backoff on TransientProviderError and RateLimitError up to max_retries.
    3. Wall-clock timeout monitoring across total attempts.
    """
    attempt = 0
    current_delay = initial_backoff
    start_time = time.perf_counter()

    while True:
        try:
            # Check timeout before invoking callable
            if (time.perf_counter() - start_time) > timeout_seconds:
                raise ModelTimeoutError(
                    f"Operation timed out after {timeout_seconds} seconds across {attempt} attempts."
                )
            return func()
        except BaseException as exc:
            classified = classify_gemini_error(exc)

            # Quota exhausted: never retry
            if isinstance(classified, QuotaExceededError):
                raise classified

            attempt += 1
            if attempt > max_retries:
                raise classified

            # Check if sleeping would exceed total timeout
            if (time.perf_counter() - start_time + current_delay) > timeout_seconds:
                raise ModelTimeoutError(
                    f"Retry budget exhausted: sleeping {current_delay}s would exceed timeout {timeout_seconds}s."
                )

            time.sleep(current_delay)
            current_delay = min(current_delay * backoff_factor, max_backoff)


def validate_and_resolve_model(model_name: Optional[str] = None) -> str:
    """Validates requested model against catalog; falls back to settings.DEFAULT_MODEL."""
    target = (model_name or settings.DEFAULT_MODEL).strip()
    if target in SUPPORTED_MODELS:
        return target
    return settings.DEFAULT_MODEL


def calculate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Calculate the estimated USD cost based on token counts."""
    pricing = MODEL_PRICING_TABLE.get(
        model_name,
        MODEL_PRICING_TABLE["gemini-2.0-flash"]
    )
    prompt_cost = (prompt_tokens / 1000.0) * pricing.prompt_cost_per_1k_tokens
    completion_cost = (completion_tokens / 1000.0) * pricing.completion_cost_per_1k_tokens
    return round(prompt_cost + completion_cost, 6)


class TokenCostTracker:
    """Thread-safe tracker accumulating token consumption and USD expenses."""

    def __init__(self):
        self._lock = threading.RLock()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_usd = 0.0

    def add_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        cost = calculate_cost(model_name, prompt_tokens, completion_tokens)
        with self._lock:
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_cost_usd = round(self.total_cost_usd + cost, 6)
        return cost

    def get_totals(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "prompt_tokens": self.total_prompt_tokens,
                "completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
                "total_cost_usd": self.total_cost_usd,
            }

    def reset(self) -> None:
        with self._lock:
            self.total_prompt_tokens = 0
            self.total_completion_tokens = 0
            self.total_cost_usd = 0.0


# Global Singleton Tracker
global_token_tracker = TokenCostTracker()


def get_llm_for_crewai(model_name: str = "gemini-3.8-flash") -> Any:
    """Factory for CrewAI LLM instance based on environment configuration."""
    from crewai import LLM
    resolved_model = validate_and_resolve_model(model_name)
    api_key = settings.GEMINI_API_KEY if (settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip()) else "gemini-simulation-key"
    return LLM(
        model=f"gemini/{resolved_model}",
        api_key=api_key,
        temperature=settings.TEMPERATURE,
    )
