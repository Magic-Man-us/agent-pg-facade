from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Literal

from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pgfacade.application.errors import failure
from pgfacade.contracts.protocol import ASGIMessageType, ASGIScopeType
from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import DEFAULT_REQUEST_READ_TIMEOUT, RequestBodyBytes, RequestByteLimit, RequestReadTimeout


class BufferedRequestMessage(BaseModel):
    model_config = CONTRACT_CONFIG

    type: Literal[ASGIMessageType.HTTP_REQUEST] = ASGIMessageType.HTTP_REQUEST
    body: RequestBodyBytes
    more_body: Literal[False] = False


class RequestBodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: RequestByteLimit, timeout_s: RequestReadTimeout = DEFAULT_REQUEST_READ_TIMEOUT) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.timeout_s = timeout_s

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != ASGIScopeType.HTTP:
            await self.app(scope, receive, send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(self.timeout_s):
                while True:
                    message = await receive()
                    if message["type"] == ASGIMessageType.HTTP_DISCONNECT:
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.max_bytes:
                        response = JSONResponse(
                            failure(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body exceeds the configured limit").model_dump(
                                mode="json"
                            ),
                            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        )
                        await response(scope, receive, send)
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            response = JSONResponse(
                failure(HTTPStatus.REQUEST_TIMEOUT, "Request body read timed out").model_dump(mode="json"), HTTPStatus.REQUEST_TIMEOUT
            )
            await response(scope, receive, send)
            return
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return BufferedRequestMessage.model_validate({"body": body}).model_dump()

        await self.app(scope, bounded_receive, send)
