from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import cast

from pgfacade.application.context import ExecutionContext
from pgfacade.application.errors import Forbidden, InvalidRequest, error_payload
from pgfacade.application.registry import LISTEN, OPERATIONS, OpSpec, op
from pgfacade.application.types import ExecutionProvenance
from pgfacade.authorization.engine import PolicyEngine
from pgfacade.authorization.models import AuthorizationContext, AuthorizationDecision
from pgfacade.configuration.settings import ANONYMOUS, PgSettings, Principal
from pgfacade.contracts.admin import MaintReindex
from pgfacade.contracts.base import Contract, RequestContract
from pgfacade.contracts.enums import MaintenanceKind, Operation, OperationHint, Outcome
from pgfacade.contracts.envelopes import Failure, ResponseEnvelope, Success
from pgfacade.contracts.events import EventWait, EventWaitInput, Notification
from pgfacade.contracts.lifecycle import AllPolicies, LifecycleList, LifecycleListInput, LifecycleRun, LifecycleRunInput
from pgfacade.contracts.requests import Batch, BatchResult, Request
from pgfacade.contracts.streaming import EventStreamRequest, EventStreamResponse
from pgfacade.infrastructure.postgres.engine import Core

log = logging.getLogger("pgfacade")
_NONTRANSACTIONAL_OPERATIONS = frozenset({Operation.MAINT_BACKEND, Operation.QUERY_RELOAD})


def _requires_autocommit(request: Request, spec: OpSpec) -> bool:
    return (
        spec.perm.migrate
        or spec.op in _NONTRANSACTIONAL_OPERATIONS
        or isinstance(request, MaintReindex)
        and (request.input.kind == MaintenanceKind.SCHEMA or request.input.concurrently)
    )


class _BatchFailure(Exception):
    def __init__(self, outcome: Failure) -> None:
        self.outcome = outcome
        super().__init__(outcome.error.message)


class PgFacade(Core):
    def __init__(self, settings: PgSettings | None = None) -> None:
        super().__init__(settings)
        self._execution_context: ExecutionContext | None = None
        self._sweeper: asyncio.Task[None] | None = None

    async def open(self) -> None:
        await super().open()
        if self._sweeper is None and self.settings.lifecycle_sweep_s > 0 and not self.settings.read_only:
            self._sweeper = asyncio.create_task(self._sweep_loop(), name="pgfacade-lifecycle")

    async def close(self) -> None:
        if self._transaction_task is not None:
            return
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except asyncio.CancelledError:
                pass
            self._sweeper = None
        await super().close()

    async def _sweep_loop(self) -> None:
        context = ExecutionContext(principal=ANONYMOUS, provenance=ExecutionProvenance.WORKER)
        while True:
            await asyncio.sleep(self.settings.lifecycle_sweep_s)
            listing = await self.call(LifecycleList(input=LifecycleListInput()), context)
            if listing.outcome.status == Outcome.ERROR:
                log.warning("Lifecycle discovery failed: %s", listing.outcome.error.code)
            elif listing.outcome.data.installed:
                response = await self.call(LifecycleRun(input=LifecycleRunInput(target=AllPolicies())), context)
                if response.outcome.status == Outcome.ERROR:
                    log.warning("Lifecycle sweep failed: %s", response.outcome.error.code)

    async def call[ResultT: Contract](
        self, request: RequestContract[ResultT], context: ExecutionContext | None = None
    ) -> ResponseEnvelope[ResultT]:
        try:
            spec = self.spec_for(request)
            execution = self._with_context(context)._authorized_view(cast(Request, request))
            execution.require(spec.perm)
            if execution.in_transaction and _requires_autocommit(cast(Request, request), spec):
                raise InvalidRequest(f"{spec.op} cannot run inside a transaction")
            envelope = spec.envelope(kind=request.kind, outcome=Success(data=await spec.handler(execution, request)))
        except _BatchFailure as error:
            return ResponseEnvelope(kind=request.kind, outcome=error.outcome)
        except Exception as error:
            return ResponseEnvelope(kind=request.kind, outcome=error_payload(error))
        # Registration checks the request's phantom result parameter and its concrete response envelope.
        return cast(ResponseEnvelope[ResultT], envelope)

    @staticmethod
    def spec_for(request: RequestContract[Contract]) -> OpSpec:
        spec = OPERATIONS.get(request.kind)
        if spec is None or not isinstance(request, spec.request):
            raise InvalidRequest(f"Unsupported request type {type(request).__name__}")
        if type(request) is not spec.request:
            registered = {known.request for known in OPERATIONS.values()}
            if sum(base in registered for base in type(request).__mro__) > 1:
                raise InvalidRequest("Request inheritance does not match its operation contract")
        return spec

    def _with_context(self, context: ExecutionContext | None) -> PgFacade:
        if context is None:
            return self
        if self.in_transaction:
            principal = self._execution_context.principal if self._execution_context is not None else self.principal
            if context.principal != principal:
                raise Forbidden("Cannot change the authenticated principal inside a transaction")
            return self
        execution = self.as_(context.principal)
        execution._execution_context = context
        return execution

    def _authorization_context(self) -> AuthorizationContext:
        return AuthorizationContext(
            connector=self.settings.connector_id,
            default_schema=self.settings.default_schema,
            execution_identity=self._principal.execution_identity if self.in_transaction else None,
        )

    def _bind_execution(self, decision: AuthorizationDecision) -> PgFacade:
        if self.in_transaction and self._principal.role != decision.profile.role:
            raise Forbidden("Cannot change the database identity inside a transaction")
        bound = copy.copy(self)
        values = self._principal.model_dump() | decision.profile.model_dump()
        values |= {"identity": self._principal.identity, "execution_identity": decision.execution_identity}
        bound._principal = Principal.model_validate(values)
        return bound

    def _authorized_view(self, request: Request) -> PgFacade:
        identity = self._principal.identity
        if identity is None:
            return self
        config = self.settings.access_control
        if config is None:
            raise Forbidden("Group identities require configured access policies")
        if self.in_transaction and self._principal.execution_identity is None:
            raise Forbidden("A database identity must be selected before opening a group transaction")
        decision = PolicyEngine(config).authorize(request, identity, self._authorization_context())
        return self._bind_execution(decision)

    def allowed_ops(self, context: ExecutionContext | None = None) -> list[OpSpec]:
        execution = self._with_context(context)
        identity = execution._principal.identity
        if identity is None:
            return [spec for spec in OPERATIONS.values() if execution.allows(spec.perm)]
        config = execution.settings.access_control
        if config is None:
            return []
        engine = PolicyEngine(config)
        authorization = execution._authorization_context()
        return [
            spec
            for spec in OPERATIONS.values()
            if any(execution._bind_execution(decision).allows(spec.perm) for decision in engine.discover(spec.op, identity, authorization))
        ]

    async def stream_events(
        self, request: EventStreamRequest, context: ExecutionContext | None = None
    ) -> AsyncGenerator[EventStreamResponse | None, None]:
        execution = self._with_context(context)._authorized_view(EventWait(input=EventWaitInput(channels=request.input.channels)))
        execution.require(LISTEN)
        return execution._event_stream(request)

    async def _event_stream(self, request: EventStreamRequest) -> AsyncGenerator[EventStreamResponse | None, None]:
        from pgfacade.application.operations.events import listen

        try:
            # The listener is an async generator whose public annotation is AsyncIterator.
            notifications = cast(
                AsyncGenerator[Notification | None, None],
                listen(self, request.input.channels, heartbeat_s=request.input.heartbeat_s),
            )
            async with aclosing(notifications):
                async for notification in notifications:
                    if notification is None:
                        yield None
                    else:
                        yield EventStreamResponse(outcome=Success(data=notification))
        except Exception as error:
            yield EventStreamResponse(outcome=error_payload(error))


@op(Batch, response=BatchResult, hint=OperationHint.DESTRUCTIVE)
async def run_batch(db: PgFacade, request: Batch) -> BatchResult:
    for child in request.input.requests:
        if isinstance(child, Batch):
            raise InvalidRequest("nested batches are not allowed")
        spec = db.spec_for(child)
        db.require(spec.perm)
        if _requires_autocommit(child, spec):
            raise InvalidRequest(f"{spec.op} cannot run inside a transaction")
    results = []
    async with db.transaction() as tx:
        for child in request.input.requests:
            result = await tx.call(child)
            if result.outcome.status == Outcome.ERROR:
                raise _BatchFailure(result.outcome)
            results.append(result)
    return BatchResult(results=results)


from pgfacade.application import operations  # noqa: E402,F401  # Registered after batch.run to keep catalog order.
