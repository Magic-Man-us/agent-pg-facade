from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from fastmcp import Client

from pgfacade import PgFacade, PgSettings, Principal
from pgfacade.infrastructure.startup import StartupCommand
from pgfacade.webapp import create_app
from pgfacade.webmcp import create_mcp


class CheckingFacade(PgFacade):
    async def open(self) -> None:
        assert self.settings.startup_command is not None
        ready_file = Path(self.settings.startup_command.argv[-1])
        assert ready_file.exists()

    async def close(self) -> None:
        return None


def transport_settings(tmp_path: Path) -> PgSettings:
    ready_file = tmp_path / "ready"
    startup = StartupCommand(
        argv=(
            sys.executable,
            "-u",
            "-c",
            "import sys,time; from pathlib import Path; Path(sys.argv[1]).touch(); sys.stderr.write('READY\\n'); sys.stderr.flush(); time.sleep(60)",
            str(ready_file),
        ),
        timeout_s=2,
        stop_timeout_s=0.2,
    )
    return PgSettings(_env_file=None, keys={"test": Principal()}, startup_command=startup)


def test_rest_waits_for_command_before_opening_database(tmp_path: Path) -> None:
    settings = transport_settings(tmp_path)
    with TestClient(create_app(settings, CheckingFacade(settings))) as client:
        assert client.get("/healthz").status_code == 200


async def test_mcp_waits_for_command_before_opening_database(tmp_path: Path) -> None:
    settings = transport_settings(tmp_path)
    async with Client(create_mcp(settings, CheckingFacade(settings))):
        assert (tmp_path / "ready").exists()
