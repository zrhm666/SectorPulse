"""Unified exception system for LLM errors."""


class LLMError(Exception):
    """Base LLM error."""

    recoverable: bool = False


class RateLimitError(LLMError):
    """Rate limit exceeded — recoverable with a wait."""

    recoverable = True
    retry_after: int | None = None

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ContextWindowExceededError(LLMError):
    """Context window too small for the request — not recoverable."""

    recoverable = False


class AuthenticationError(LLMError):
    """Invalid or expired credentials — not recoverable."""

    recoverable = False


class ProviderUnavailableError(LLMError):
    """Provider endpoint unreachable — recoverable."""

    recoverable = True


class APIError(LLMError):
    """Generic API error with optional status code — may be recoverable."""

    recoverable = True

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class APIConnectionError(LLMError):
    """Network/connection error — recoverable."""

    recoverable = True
