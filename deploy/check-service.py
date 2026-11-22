from __future__ import annotations

import logging
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pgfacade.configuration.settings import PgSettings
from pgfacade.contracts.admin import (
    DiagActivity,
    DiagActivityInput,
    Health,
    MigrationInit,
    MigrationInitInput,
    ServerHealth,
    ServerHealthInput,
    ServerSettings,
    ServerSettingsInput,
    ServerWhoAmI,
    ServerWhoAmIInput,
    WhoAmI,
)
from pgfacade.contracts.base import Contract
from pgfacade.contracts.discovery import OperationDiscoveryResponse
from pgfacade.contracts.envelopes import Failure, ResponseEnvelope, Success
from pgfacade.contracts.events import EventNotify, EventNotifyInput, EventWait, EventWaitInput, EventWatchList, EventWatchListInput
from pgfacade.contracts.lifecycle import LifecycleList, LifecycleListInput
from pgfacade.contracts.queries import QueryRun, QueryRunInput
from pgfacade.contracts.roles import RoleCreate, RoleCreateInput
from pgfacade.contracts.rows import SqlQuery, SqlQueryInput
from pgfacade.contracts.schema import SchemaCreate, SchemaCreateInput
from pgfacade.shared.types import DEFAULT_REQUEST_BYTE_LIMIT

BASE_URL = "http://127.0.0.1:8765"
KEY_FILE = "/etc/pgfacade/keys.json"
REQUEST_TIMEOUT_S = 15
UNAUTHORIZED = 401
FORBIDDEN = 403
BODY_TOO_LARGE = 413
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("pgfacade.check")


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, _request: Request, *_response_metadata: object, **_options: object) -> None:
        return None


def verified_data[T](response: ResponseEnvelope[T]) -> T:
    match response.outcome:
        case Success(data=data):
            return data
        case Failure():
            raise RuntimeError("Service returned an error outcome for an expected success")


def main() -> None:
    opener = build_opener(ProxyHandler({}), RefuseRedirects())
    settings = PgSettings(_env_file=None, keys_file=KEY_FILE)
    reader_keys = [key for key, principal in settings.keys.items() if principal.role == "pgfacade_reader" and principal.read_only]
    writer_keys = [key for key, principal in settings.keys.items() if principal.role == "pgfacade_writer" and (not principal.read_only)]
    if not reader_keys or not writer_keys:
        raise RuntimeError("The restricted profile requires a reader key and a writable writer key")
    restricted_ops = {
        "sql.query",
        "schema.create",
        "role.create",
        "migration.init",
        "event.notify",
        "event.wait",
        "diag.activity",
        "lifecycle.list",
    }
    for key, principal in settings.keys.items():
        name = principal.name
        if principal.role not in {"pgfacade_reader", "pgfacade_writer"}:
            raise RuntimeError(f"Principal {name!r} is mapped outside the restricted database roles")
        if principal.role == "pgfacade_reader" and (not principal.read_only):
            raise RuntimeError(f"Reader principal {name!r} must be configured read-only")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        request = Request(
            BASE_URL + "/server/health", data=ServerHealth(input=ServerHealthInput()).model_dump_json().encode(), headers=headers
        )
        with opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
            if not verified_data(ResponseEnvelope[Health].model_validate_json(response.read())).ok:
                raise RuntimeError(f"Principal {name!r} failed the database health check")
        request = Request(
            BASE_URL + "/server/whoami", data=ServerWhoAmI(input=ServerWhoAmIInput()).model_dump_json().encode(), headers=headers
        )
        with opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
            identity = verified_data(ResponseEnvelope[WhoAmI].model_validate_json(response.read()))
        if identity.principal != principal.name:
            raise RuntimeError(f"Principal {name!r} has an unexpected identity label")
        if identity.role != principal.role:
            raise RuntimeError(f"Principal {name!r} has an unexpected database role")
        if identity.read_only != principal.read_only:
            raise RuntimeError(f"Principal {name!r} has an unexpected read-only setting")
        if any((identity.sql, identity.ddl, identity.admin, identity.migrate, identity.listen)):
            raise RuntimeError(f"Principal {name!r} can use a disabled capability")
        with opener.open(Request(BASE_URL + "/ops", headers=headers), timeout=REQUEST_TIMEOUT_S) as response:
            operations = OperationDiscoveryResponse.model_validate_json(response.read()).root
        allowed = {operation.op for operation in operations}
        if not restricted_ops.isdisjoint(allowed):
            raise RuntimeError(f"Principal {name!r} can discover a disabled operation")
        if ("rows.insert" in allowed) != (not principal.read_only):
            raise RuntimeError(f"Principal {name!r} has unexpected row-write access")
        logger.info("PASS %s health, identity and filtered operations", name)
    writer = writer_keys[0]
    health_body = ServerHealth(input=ServerHealthInput()).model_dump_json().encode()
    checks = (
        ("missing key", None, "POST", "/server/health", health_body, UNAUTHORIZED),
        ("invalid key", "invalid-verification-key", "POST", "/server/health", health_body, UNAUTHORIZED),
        (
            "DDL",
            writer,
            "POST",
            "/schema/create",
            SchemaCreate(input=SchemaCreateInput(name="forbidden")).model_dump_json().encode(),
            FORBIDDEN,
        ),
        ("SQL", writer, "POST", "/sql/query", SqlQuery(input=SqlQueryInput(sql="SELECT 1")).model_dump_json().encode(), FORBIDDEN),
        ("call dispatch SQL", writer, "POST", "/call", SqlQuery(input=SqlQueryInput(sql="SELECT 1")).model_dump_json().encode(), FORBIDDEN),
        (
            "role management",
            writer,
            "POST",
            "/role/create",
            RoleCreate(input=RoleCreateInput(name="forbidden")).model_dump_json().encode(),
            FORBIDDEN,
        ),
        ("migrations", writer, "POST", "/migration/init", MigrationInit(input=MigrationInitInput()).model_dump_json().encode(), FORBIDDEN),
        (
            "notifications",
            writer,
            "POST",
            "/event/notify",
            EventNotify(input=EventNotifyInput(channel="forbidden")).model_dump_json().encode(),
            FORBIDDEN,
        ),
        (
            "LISTEN",
            writer,
            "POST",
            "/event/wait",
            EventWait(input=EventWaitInput(channels=["forbidden"], timeout_s=0.1)).model_dump_json().encode(),
            FORBIDDEN,
        ),
        ("SSE", writer, "GET", "/events/forbidden", None, FORBIDDEN),
        ("watches", writer, "POST", "/event/watches", EventWatchList(input=EventWatchListInput()).model_dump_json().encode(), FORBIDDEN),
        ("diagnostics", writer, "POST", "/diag/activity", DiagActivity(input=DiagActivityInput()).model_dump_json().encode(), FORBIDDEN),
        ("settings", writer, "POST", "/server/settings", ServerSettings(input=ServerSettingsInput()).model_dump_json().encode(), FORBIDDEN),
        (
            "diagnostic queries",
            writer,
            "POST",
            "/query/run",
            QueryRun(input=QueryRunInput(name="health.connections")).model_dump_json().encode(),
            FORBIDDEN,
        ),
        ("lifecycle", writer, "POST", "/lifecycle/list", LifecycleList(input=LifecycleListInput()).model_dump_json().encode(), FORBIDDEN),
        ("upload limit", writer, "POST", "/call", b"x" * (DEFAULT_REQUEST_BYTE_LIMIT + 1), BODY_TOO_LARGE),
    )
    for name, key, method, path, body, expected in checks:
        headers = {"Content-Type": "application/json"}
        if key is not None:
            headers["Authorization"] = f"Bearer {key}"
        request = Request(BASE_URL + path, data=body, headers=headers, method=method)
        try:
            with opener.open(request, timeout=REQUEST_TIMEOUT_S) as response:
                status = response.status
                response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
            result = (
                Failure.model_validate_json(body)
                if status in {UNAUTHORIZED, BODY_TOO_LARGE} or path.startswith("/events/")
                else ResponseEnvelope[Contract].model_validate_json(body).outcome
            )
            if not isinstance(result, Failure):
                raise RuntimeError(f"{name}: expected an error outcome") from None
            if result.error.status != status:
                raise RuntimeError(f"{name}: error envelope disagrees with HTTP status") from None
        if status != expected:
            raise RuntimeError(f"{name}: expected {expected}, got {status}")
        logger.info("PASS %s denied (%s)", name, status)
    logger.info("Restricted v0.5 service checks passed; no application data was modified")


if __name__ == "__main__":
    main()
