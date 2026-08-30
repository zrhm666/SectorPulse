from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ExceptionHandler

logger = logging.getLogger("sector_pulse.web")


def _error_response(*, status_code: int, code: str, message: str, retryable: bool) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}},
    )


async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "请求无法处理"
    status_codes = {
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "INVALID_REQUEST",
        503: "SERVICE_UNAVAILABLE",
    }
    code = (
        message
        if message.isupper() and " " not in message
        else status_codes.get(exc.status_code, "REQUEST_FAILED")
    )
    return _error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        retryable=exc.status_code in {429, 502, 503, 504},
    )


async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        status_code=422,
        code="INVALID_REQUEST",
        message="请求参数无效",
        retryable=False,
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a stable public error without reflecting exception or credential text."""
    logger.error(
        "%s unhandled request error method=%s path=%s error_type=%s",
        datetime.now(UTC).isoformat(),
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return _error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="服务暂时不可用",
        retryable=True,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, cast(ExceptionHandler, http_error_handler))
    app.add_exception_handler(
        RequestValidationError, cast(ExceptionHandler, validation_error_handler)
    )
    app.add_exception_handler(Exception, internal_error_handler)
