from __future__ import annotations

import importlib.util
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

CHECKER = Path(__file__).resolve().parents[2] / "deploy/check-service.py"
MOCK_KEY = "non-secret-redirect-test-key"


@pytest.fixture
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pgfacade_deployment_checks", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the deployment checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checker_rejects_failed_health_with_python_optimization() -> None:
    script = '\nimport importlib.util\nimport io\nimport sys\nfrom pgfacade.contracts.admin import Health\nfrom pgfacade.contracts.envelopes import Success, ResponseEnvelope\nfrom pgfacade.contracts.enums import Operation\nfrom pgfacade.configuration.settings import PgSettings, Principal\n\nspec = importlib.util.spec_from_file_location("checker", sys.argv[1])\nchecker = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(checker)\nsettings = PgSettings(_env_file=None, keys={\n    "test-reader": Principal(name="client-reader", role="pgfacade_reader", read_only=True),\n    "test-writer": Principal(name="client-writer", role="pgfacade_writer"),\n})\ndef settings_for_check(**_kwargs: object) -> PgSettings:\n    return settings\nchecker.PgSettings = settings_for_check\nclass UnhealthyOpener:\n    def open(self, *_args: object, **_kwargs: object) -> io.BytesIO:\n        return io.BytesIO(ResponseEnvelope(kind=Operation.SERVER_HEALTH,outcome=Success(data=Health(ok=False, latency_ms=0))).model_dump_json().encode())\ndef opener_for_check(*_args: object) -> UnhealthyOpener:\n    return UnhealthyOpener()\nchecker.build_opener = opener_for_check\ntry:\n    checker.main()\nexcept RuntimeError as error:\n    if "health check" not in str(error):\n        raise\nelse:\n    raise RuntimeError("Optimized checker accepted an unhealthy deployment")\n'
    result = subprocess.run([sys.executable, "-O", "-c", script, str(CHECKER)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_checker_disables_environment_proxies(checker: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    seen: list[object] = []

    def capture_handlers(*handlers: object) -> None:
        seen.extend(handlers)
        raise RuntimeError("captured safe opener construction")

    monkeypatch.setattr(checker, "build_opener", capture_handlers)
    with pytest.raises(RuntimeError, match="captured safe opener"):
        checker.main()
    proxies = [handler for handler in seen if isinstance(handler, ProxyHandler)]
    assert len(proxies) == 1
    assert proxies[0].proxies == {}


def test_checker_never_forwards_bearer_to_redirect_target(checker: ModuleType) -> None:
    destination_hits: list[str | None] = []

    class Destination(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            destination_hits.append(self.headers.get("Authorization"))
            self.send_response(HTTPStatus.OK)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            return None

    destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
    destination_url = f"http://127.0.0.1:{destination.server_port}/capture"

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", destination_url)
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:
            return None

    source = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (source, destination)]
    for thread in threads:
        thread.start()
    try:
        opener = build_opener(ProxyHandler({}), checker.RefuseRedirects())
        request = Request(f"http://127.0.0.1:{source.server_port}/redirect", headers={"Authorization": f"Bearer {MOCK_KEY}"})
        with pytest.raises(HTTPError) as error:
            opener.open(request, timeout=3)
        assert error.value.code == HTTPStatus.FOUND
        assert destination_hits == []
    finally:
        for server in (source, destination):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
