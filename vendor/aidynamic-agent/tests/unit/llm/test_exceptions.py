from aidynamic_agent.llm.exceptions import (
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ProviderUnavailableError,
    RateLimitError,
)


class TestLLMError:
    def test_is_exception_subclass(self):
        assert issubclass(LLMError, Exception)

    def test_recoverable_default_false(self):
        assert LLMError.recoverable is False

    def test_instantiation_with_message(self):
        err = LLMError("something went wrong")
        assert str(err) == "something went wrong"

    def test_is_catchable_as_exception(self):
        try:
            raise LLMError("boom")
        except Exception as e:
            assert isinstance(e, LLMError)


class TestRateLimitError:
    def test_is_llm_error_subclass(self):
        assert issubclass(RateLimitError, LLMError)

    def test_is_exception_subclass(self):
        assert issubclass(RateLimitError, Exception)

    def test_recoverable_true(self):
        assert RateLimitError.recoverable is True

    def test_retry_after_defaults_none(self):
        err = RateLimitError("rate limited")
        assert err.retry_after is None

    def test_retry_after_set(self):
        err = RateLimitError("rate limited", retry_after=30)
        assert err.retry_after == 30

    def test_message_preserved(self):
        err = RateLimitError("too many requests")
        assert str(err) == "too many requests"

    def test_catchable_as_llm_error(self):
        try:
            raise RateLimitError("rate limited")
        except LLMError as e:
            assert isinstance(e, RateLimitError)
            assert e.recoverable is True

    def test_catchable_as_exception(self):
        try:
            raise RateLimitError("rate limited")
        except Exception as e:
            assert isinstance(e, RateLimitError)


class TestContextWindowExceededError:
    def test_is_llm_error_subclass(self):
        assert issubclass(ContextWindowExceededError, LLMError)

    def test_recoverable_false(self):
        assert ContextWindowExceededError.recoverable is False

    def test_message_preserved(self):
        err = ContextWindowExceededError("context too large")
        assert str(err) == "context too large"


class TestAuthenticationError:
    def test_is_llm_error_subclass(self):
        assert issubclass(AuthenticationError, LLMError)

    def test_recoverable_false(self):
        assert AuthenticationError.recoverable is False

    def test_message_preserved(self):
        err = AuthenticationError("invalid api key")
        assert str(err) == "invalid api key"


class TestProviderUnavailableError:
    def test_is_llm_error_subclass(self):
        assert issubclass(ProviderUnavailableError, LLMError)

    def test_recoverable_true(self):
        assert ProviderUnavailableError.recoverable is True

    def test_message_preserved(self):
        err = ProviderUnavailableError("provider down")
        assert str(err) == "provider down"


class TestErrorRecoveryBehavior:
    def test_recoverable_errors_in_try_except(self):
        """Verify recoverable flag distinguishes retry candidates."""
        recoverable_errors = (RateLimitError, ProviderUnavailableError)
        unrecoverable_errors = (
            ContextWindowExceededError,
            AuthenticationError,
        )

        for err_cls in recoverable_errors:
            err = err_cls("error")
            assert err.recoverable is True

        for err_cls in unrecoverable_errors:
            err = err_cls("error")
            assert err.recoverable is False

    def test_catch_recoverable_in_handler(self):
        """Simulate a retry handler that only catches recoverable errors."""
        errors_to_test = [
            (RateLimitError("rate limited", retry_after=5), True),
            (ProviderUnavailableError("provider down"), True),
            (ContextWindowExceededError("too big"), False),
            (AuthenticationError("bad key"), False),
        ]

        for err, expected_recoverable in errors_to_test:
            assert err.recoverable == expected_recoverable

    def test_base_llm_error_not_recoverable(self):
        err = LLMError("generic error")
        assert err.recoverable is False
