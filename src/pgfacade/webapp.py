from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, asynccontextmanager
from functools import reduce
from http import HTTPStatus
from operator import or_
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, ValidationError
from starlette.exceptions import HTTPException

from pgfacade import __version__
from pgfacade.application.context import ExecutionContext
from pgfacade.application.errors import PgFacadeError, RequestValidationFailure, error_payload
from pgfacade.application.registry import REGISTRY, OpSpec
from pgfacade.application.types import ExecutionProvenance
from pgfacade.authorization.providers import IdentityProvider, authenticate, configure_identity_provider
from pgfacade.configuration.settings import PgSettings
from pgfacade.contracts.base import Contract, RequestContract
from pgfacade.contracts.discovery import LivenessRequest, LivenessResponse, OperationDiscoveryRequest, OperationDiscoveryResponse, OpInfo
from pgfacade.contracts.envelopes import Failure, ResponseEnvelope
from pgfacade.contracts.protocol import StreamEvent
from pgfacade.contracts.requests import Request as RequestUnion
from pgfacade.contracts.streaming import EventStreamRequest
from pgfacade.infrastructure.startup import startup_command
from pgfacade.myapp import MyApp
from pgfacade.presentation.middleware import RequestBodyLimit
from pgfacade.shared.types import (
    EventChannelList,
    EventStreamChunk,
    HeartbeatSeconds,
)

OperationResponse = reduce(or_, (spec.envelope for spec in REGISTRY.values()))
# FastAPI accepts heterogeneous OpenAPI response metadata at this framework boundary.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": Failure} for status in (400, 401, 403, 404, 405, 408, 409, 413, 422, 500, 502, 503)
}

_bearer = HTTPBearer(auto_error=False, description="Bearer credential for the configured authentication source")


def current_app(request: Request) -> MyApp:
    return request.app.state.db  # type: ignore[no-any-return]  # Starlette owns the untyped application-state container.


async def current_context(request: Request, cred: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)]) -> ExecutionContext:
    settings: PgSettings = request.app.state.settings
    provider: IdentityProvider | None = request.app.state.identity_provider
    principal = await authenticate(settings, cred.credentials if cred else None, provider)
    return ExecutionContext(principal=principal, provenance=ExecutionProvenance.HTTP)


Application = Annotated[MyApp, Depends(current_app)]
Context = Annotated[ExecutionContext, Depends(current_context)]


def _op_info(spec: OpSpec) -> OpInfo:
    return OpInfo(
        op=spec.op,
        path=f"/{spec.area}/{spec.action}",
        summary=spec.summary,
        hint=spec.hint,
        perm=spec.perm.flags(),
    )


def _route_for(
    spec: OpSpec,
) -> Callable[[MyApp, ExecutionContext, RequestContract[Contract], Response], Awaitable[ResponseEnvelope[Contract]]]:
    async def endpoint(
        app: Application, context: Context, body: RequestContract[Contract], response: Response
    ) -> ResponseEnvelope[Contract]:
        result = await app.call(body, context)
        response.status_code = result.outcome.error.status if isinstance(result.outcome, Failure) else HTTPStatus.OK
        return result

    # FastAPI needs the concrete catalog model after postponed annotations have been resolved.
    endpoint.__annotations__ = {"app": Application, "context": Context, "body": spec.request, "response": Response, "return": spec.envelope}
    endpoint.__name__ = spec.op.replace(".", "_")
    endpoint.__doc__ = spec.summary
    return endpoint


def build_router() -> APIRouter:
    router = APIRouter()
    for spec in REGISTRY.values():
        router.add_api_route(
            f"/{spec.area}/{spec.action}",
            _route_for(spec),
            methods=["POST"],
            response_model=spec.envelope,
            tags=[spec.area],
            summary=spec.summary,
            operation_id=spec.op.replace(".", "_"),
        )
    return router


def create_app(settings: PgSettings | None = None, db: MyApp | None = None, identity_provider: IdentityProvider | None = None) -> FastAPI:
    settings = settings or (db.settings if db is not None else PgSettings())
    if not settings.auth_enabled:
        raise ValueError("API keys or access_control must be configured before starting a server")
    if db is not None and db.settings != settings:
        raise ValueError("The supplied application must use the server settings")
    provider = configure_identity_provider(settings, identity_provider)
    db = db or MyApp(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with startup_command(settings.startup_command), db:
            yield

    app = FastAPI(title="pgfacade", version=__version__, lifespan=lifespan, responses=_ERROR_RESPONSES, redirect_slashes=False)
    app.add_middleware(RequestBodyLimit, max_bytes=settings.max_request_bytes, timeout_s=settings.request_read_timeout_s)
    app.state.settings = settings
    app.state.db = db
    app.state.identity_provider = provider

    @app.exception_handler(Exception)
    @app.exception_handler(HTTPException)
    @app.exception_handler(RequestValidationError)
    @app.exception_handler(PgFacadeError)
    @app.exception_handler(psycopg.Error)
    async def _transport_error(_: Request, exc: Exception) -> JSONResponse:
        payload = error_payload(exc)
        status = payload.error.status
        headers = dict(exc.headers or {}) if isinstance(exc, HTTPException) else {}
        if status == HTTPStatus.UNAUTHORIZED:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(payload.model_dump(mode="json"), status_code=status, headers=headers)

    @app.get("/healthz", tags=["server"], include_in_schema=False)
    async def healthz(request: Annotated[LivenessRequest, Query()]) -> LivenessResponse:
        return LivenessResponse(ok=db._pool is not None)

    @app.get("/ops", tags=["server"])
    async def ops(app: Application, context: Context, request: Annotated[OperationDiscoveryRequest, Query()]) -> OperationDiscoveryResponse:
        return OperationDiscoveryResponse([_op_info(spec) for spec in app.allowed_ops(context)])

    @app.post(
        "/call",
        tags=["server"],
        summary="Dispatch an operation by its kind",
        # The catalog supplies this closed union at runtime.
        response_model=Annotated[OperationResponse, Field(discriminator="kind")],
    )
    async def call(app: Application, context: Context, body: RequestUnion, response: Response) -> ResponseEnvelope[Contract]:
        result = await app.call(body, context)
        response.status_code = result.outcome.error.status if isinstance(result.outcome, Failure) else HTTPStatus.OK
        return result

    @app.get("/events/{channel}", tags=["event"], summary="Stream NOTIFY payloads as server-sent events")
    async def events(
        app: Application, context: Context, channel: EventChannelList, heartbeat_s: Annotated[HeartbeatSeconds, Query()] = 15.0
    ) -> StreamingResponse:
        try:
            request = EventStreamRequest.model_validate({"input": {"channels": channel, "heartbeat_s": heartbeat_s}})
        except ValidationError as error:
            raise RequestValidationFailure(error) from error
        notifications = await app.stream_events(request, context)

        async def stream() -> AsyncIterator[EventStreamChunk]:
            yield b": connected\n\n"
            async with aclosing(notifications):
                async for result in notifications:
                    if result is None:
                        yield b": heartbeat\n\n"
                    else:
                        event = StreamEvent.ERROR if isinstance(result.outcome, Failure) else StreamEvent.NOTIFY
                        yield f"event: {event}\ndata: {result.model_dump_json()}\n\n".encode()

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    app.include_router(build_router())
    return app
