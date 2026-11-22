"""Server runtime shared by the REST and MCP transports: resolved dependencies and their lifetime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from pgfacade.authorization.providers import IdentityProvider, configure_identity_provider
from pgfacade.configuration.settings import PgSettings
from pgfacade.facade import PgFacade
from pgfacade.infrastructure.startup import startup_command
from pgfacade.shared.types import SecurityFlag


@dataclass(frozen=True, slots=True)
class ServerRuntime:
    settings: PgSettings
    db: PgFacade
    identity_provider: IdentityProvider | None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Run the startup command and open the facade, unless the caller already opened it.

        An open facade belongs to whoever opened it: a host application that embeds a second
        transport, or a library caller. Its pool and startup command are theirs to stop.
        """
        if self.db.is_open:
            yield
            return
        async with startup_command(self.settings.startup_command), self.db:
            yield


def server_runtime(
    settings: PgSettings | None,
    db: PgFacade | None,
    identity_provider: IdentityProvider | None,
    *,
    require_auth: SecurityFlag,
) -> ServerRuntime:
    settings = settings or (db.settings if db is not None else PgSettings())
    if require_auth and not settings.auth_enabled:
        raise ValueError("API keys or access_control must be configured before starting a server")
    if db is not None and db.settings != settings:
        raise ValueError("The supplied application must use the server settings")
    provider = configure_identity_provider(settings, identity_provider)
    return ServerRuntime(settings=settings, db=db or PgFacade(settings), identity_provider=provider)
