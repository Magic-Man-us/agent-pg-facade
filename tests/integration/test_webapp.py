"""The REST transport: generated routes, /call, /ops, auth, errors, SSE."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from pgfacade import REGISTRY, Principal
from pgfacade.webapp import create_app
from tests.conftest import TEST_HEADERS, make_settings, unique

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings()), headers=TEST_HEADERS) as c:
        yield c


def test_every_op_has_a_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for spec in REGISTRY.values():
        assert f"/{spec.area}/{spec.action}" in paths
    assert client.get("/healthz").json() == {"ok": True, "message": None}
    ops = client.get("/ops").json()
    assert {o["op"] for o in ops} == set(REGISTRY)  # anonymous with allow_admin=True may call everything
    delete = next(o for o in ops if o["op"] == "rows.delete")
    assert delete["path"] == "/rows/delete" and delete["hint"] == "destructive" and delete["perm"] == {"write": True}


def test_generated_routes_and_call(client: TestClient, users: str) -> None:
    r = client.post(
        "/rows/select",
        json={"kind": "rows.select", "input": {"table": users, "order_by": [{"column": "score", "desc": True}], "with_total": "true"}},
    )
    assert r.status_code == 200 and [row["email"] for row in r.json()["outcome"]["data"]["rows"]] == [
        "cat@x.io",
        "ann@x.io",
        "bob@x.io",
    ]  # NULLS FIRST
    r = client.post(
        "/call",
        json={"kind": "rows.count", "input": {"table": users, "where": [{"kind": "cmp", "column": "score", "op": "gte", "value": 3}]}},
    )
    assert r.json() == {"kind": "rows.count", "outcome": {"status": "success", "data": {"count": 2}}}
    r = client.post(
        "/rows/insert", json={"kind": "rows.insert", "input": {"table": users, "rows": [{"email": "dan@x.io", "meta": {"k": 1}}]}}
    )
    assert r.status_code == 200 and r.json()["outcome"]["data"]["rows"][0]["meta"] == {"k": 1}
    key = r.json()["outcome"]["data"]["rows"][0]["id"]
    assert (
        client.post("/rows/get", json={"kind": "rows.get", "input": {"table": users, "key": key}}).json()["outcome"]["data"]["row"]["email"]
        == "dan@x.io"
    )
    assert client.post("/rows/get", json={"kind": "rows.get", "input": {"table": users, "key": 999}}).json() == {
        "kind": "rows.get",
        "outcome": {"status": "success", "data": {"row": None}},
    }
    ops = [
        {"kind": "rows.update", "input": {"table": users, "values": {"score": 2}, "match": {"id": key}}},
        {"kind": "rows.select", "input": {"table": users, "match": {"id": key}}},
    ]
    assert (
        client.post("/batch/run", json={"kind": "batch.run", "input": {"requests": ops}}).json()["outcome"]["data"]["results"][1][
            "outcome"
        ]["data"]["rows"][0]["score"]
        == 2
    )
    assert client.post("/table/describe", json={"kind": "table.describe", "input": {"table": users}}).json()["outcome"]["data"][
        "primary_key"
    ] == ["id"]
    assert (
        client.post(
            "/query/run", json={"kind": "query.run", "input": {"name": "rows.recent", "params": {"table": users, "limit": 1}}}
        ).json()["outcome"]["data"]["rowcount"]
        == 1
    )
    assert (
        client.post("/server/whoami", json={"kind": "server.whoami", "input": {}}).json()["outcome"]["data"]["principal"] == "integration"
    )


def test_error_mapping(client: TestClient, users: str) -> None:
    r = client.post("/rows/insert", json={"kind": "rows.insert", "input": {"table": users, "rows": [{"email": "ann@x.io"}]}})
    assert r.status_code == 409 and r.json()["outcome"]["error"]["sqlstate"] == "23505"
    assert client.post("/table/describe", json={"kind": "table.describe", "input": {"table": "does_not_exist"}}).status_code == 404
    assert client.post("/rows/insert", json={"kind": "rows.insert", "input": {"table": users, "rows": [{"score": 1}]}}).status_code == 422
    assert client.post("/rows/insert", json={"kind": "rows.insert", "input": {"table": users, "rows": []}}).status_code == 422
    assert client.post("/call", json={"kind": "rows.nope", "input": {}}).status_code == 422
    r = client.post("/rows/update", json={"kind": "rows.update", "input": {"table": users, "values": {"score": 0}}})
    assert r.status_code == 400 and "refusing UPDATE" in r.json()["outcome"]["error"]["message"]
    assert (
        client.post("/schema/create", json={"kind": "schema.create", "input": {"name": "public", "if_not_exists": False}}).status_code
        == 409
    )
    r = client.post("/migration/revision", json={"kind": "migration.revision", "input": {"message": 'x"""\nimport os'}})
    assert r.status_code == 422


def test_sse_stream_and_events(client: TestClient) -> None:
    channel = unique("sse")
    assert (
        client.post("/event/notify", json={"kind": "event.notify", "input": {"channel": channel, "payload": "p"}}).json()["outcome"][
            "data"
        ]["status"]
        == "NOTIFY"
    )
    assert (
        client.post("/event/wait", json={"kind": "event.wait", "input": {"channels": [channel], "timeout_s": 0.2}}).json()["outcome"][
            "data"
        ]["timed_out"]
        is True
    )
    with client.stream("GET", f"/events/{channel}", params={"heartbeat_s": 0.2}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        lines = []
        for line in r.iter_lines():
            if line:
                lines.append(line)
            if ": heartbeat" in lines or len(lines) >= 5:
                break
    assert lines[0] == ": connected" and ": heartbeat" in lines


def test_api_keys_map_to_principals(users: str) -> None:
    keys = {
        "reader-key": Principal(name="claude", read_only=True),
        "admin-key": Principal(name="dba", sql=True, admin=True, listen=True),
    }
    with TestClient(create_app(make_settings(keys=keys))) as c:
        r = c.post("/server/health", json={"kind": "server.health", "input": {}})
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert (
            c.post("/server/health", json={"kind": "server.health", "input": {}}, headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        reader = {"Authorization": "Bearer reader-key"}
        who = c.post("/server/whoami", json={"kind": "server.whoami", "input": {}}, headers=reader).json()["outcome"]["data"]
        assert who == {
            "principal": "claude",
            "role": None,
            "read_only": True,
            "sql": False,
            "ddl": False,
            "admin": False,
            "migrate": False,
            "listen": False,
        }
        assert c.post("/rows/select", json={"kind": "rows.select", "input": {"table": users}}, headers=reader).status_code == 200
        assert (
            c.post(
                "/rows/insert", json={"kind": "rows.insert", "input": {"table": users, "rows": [{"email": "x@x.io"}]}}, headers=reader
            ).status_code
            == 403
        )
        assert c.post("/sql/query", json={"kind": "sql.query", "input": {"sql": "SELECT 1"}}, headers=reader).status_code == 403
        assert (
            c.post("/event/wait", json={"kind": "event.wait", "input": {"channels": ["c"], "timeout_s": 0.1}}, headers=reader).status_code
            == 403
        )
        assert c.get("/events/c", headers=reader).status_code == 403
        assert "rows.insert" not in {o["op"] for o in c.get("/ops", headers=reader).json()}
        admin = {"Authorization": "Bearer admin-key"}
        assert c.post("/sql/query", json={"kind": "sql.query", "input": {"sql": "SELECT 1"}}, headers=admin).status_code == 200
        assert (
            c.post("/event/wait", json={"kind": "event.wait", "input": {"channels": ["c"], "timeout_s": 0.1}}, headers=admin).status_code
            == 200
        )


def test_keys_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        make_settings(keys_file=tmp_path / "missing.json")  # fail closed, never silently unauthenticated
    (tmp_path / "keys.json").write_text('{"file-key": {"name": "from-file", "read_only": true}}')
    settings = make_settings(keys_file=tmp_path / "keys.json", keys={})
    assert set(settings.keys) == {"file-key"}
    with TestClient(create_app(settings)) as c:
        assert c.post("/server/whoami", json={"kind": "server.whoami", "input": {}}).status_code == 401
        assert (
            c.post("/server/whoami", json={"kind": "server.whoami", "input": {}}, headers={"Authorization": "Bearer file-key"}).json()[
                "outcome"
            ]["data"]["principal"]
            == "from-file"
        )


def test_server_read_only_hides_and_forbids_writes(users: str) -> None:
    with TestClient(create_app(make_settings(read_only=True)), headers=TEST_HEADERS) as c:
        assert (
            c.post("/rows/insert", json={"kind": "rows.insert", "input": {"table": users, "rows": [{"email": "x@x.io"}]}}).status_code
            == 403
        )
        assert "rows.insert" not in {o["op"] for o in c.get("/ops").json()}
