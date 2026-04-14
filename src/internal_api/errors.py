import logging
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from src.internal_api.schemas import InternalErrorEnvelope, InternalErrorPayload

logger = logging.getLogger("webapp.internal_api")


class InternalApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def ensure_request_id(request: Request) -> str:
    existing = getattr(request.state, "internal_request_id", None)
    if existing:
        return existing
    request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex[:12]
    request.state.internal_request_id = request_id
    return request_id


def _http_status_to_code(status_code: int) -> str:
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    if status_code >= 500:
        return "internal_error"
    return "request_error"


def build_internal_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = ensure_request_id(request)
    payload = InternalErrorEnvelope(
        error=InternalErrorPayload(code=code, message=message, details=details),
        request_id=request_id,
    )
    response_headers = {"X-Request-ID": request_id}
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", exclude_none=True),
        headers=response_headers,
    )


class InternalApiRoute(APIRoute):
    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            request_id = ensure_request_id(request)
            try:
                response = await original_route_handler(request)
            except RequestValidationError as exc:
                logger.warning("Internal API validation error | request_id=%s | path=%s", request_id, request.url.path)
                return build_internal_error_response(
                    request,
                    status_code=422,
                    code="validation_error",
                    message="Request validation failed.",
                    details=exc.errors(),
                )
            except InternalApiError as exc:
                logger.warning(
                    "Internal API handled error | request_id=%s | path=%s | code=%s",
                    request_id,
                    request.url.path,
                    exc.code,
                )
                return build_internal_error_response(
                    request,
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                    details=exc.details,
                )
            except HTTPException as exc:
                logger.warning(
                    "Internal API HTTP error | request_id=%s | path=%s | status=%d",
                    request_id,
                    request.url.path,
                    exc.status_code,
                )
                return build_internal_error_response(
                    request,
                    status_code=exc.status_code,
                    code=_http_status_to_code(exc.status_code),
                    message=str(exc.detail),
                    details=exc.detail if not isinstance(exc.detail, str) else None,
                    headers=exc.headers,
                )
            except Exception:
                logger.exception("Internal API unhandled error | request_id=%s | path=%s", request_id, request.url.path)
                return build_internal_error_response(
                    request,
                    status_code=500,
                    code="internal_error",
                    message="Internal API request failed.",
                )

            response.headers["X-Request-ID"] = request_id
            return response

        return custom_route_handler
