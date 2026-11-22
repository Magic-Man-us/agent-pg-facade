from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from pgfacade import PgSettings
from pgfacade.infrastructure.startup import StartupCommand, startup_command


def command(source: str, timeout_s: float = 2.0) -> StartupCommand:
    return StartupCommand(argv=(sys.executable, "-u", "-c", source), timeout_s=timeout_s, stop_timeout_s=0.2)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_ready_on_either_stream_and_shutdown_reaps_process(stream: str) -> None:
    config = command(f"import sys,time; sys.{stream}.write('starting\\n  READY \\r\\n'); sys.{stream}.flush(); time.sleep(60)")
    async with startup_command(config) as process:
        assert process is not None
        assert process.returncode is None
    assert process.returncode is not None


async def test_split_ready_writes() -> None:
    config = command("import os,time; os.write(1,b'RE'); time.sleep(.05); os.write(2,b'ADY\\n'); time.sleep(60)")
    async with startup_command(config) as process:
        assert process is not None


async def test_ready_launcher_may_exit_successfully() -> None:
    async with startup_command(command("import os; os.write(1,b'READY\\n')")) as process:
        assert process is not None
        await asyncio.wait_for(process.wait(), 2)
        assert process.returncode == 0


async def test_unterminated_ready_marker_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="before readiness"):
        async with startup_command(command("import os; os.write(1,b'READY')")):
            pytest.fail("An unterminated marker must not pass readiness")


async def test_ready_output_is_drained_after_startup(tmp_path: Path) -> None:
    finished = tmp_path / "drained"
    source = (
        "import os,time; from pathlib import Path; os.write(1,b'READY\\n'); "
        "[os.write(2,b'x'*65536) for _ in range(32)]; "
        f"Path({str(finished)!r}).touch(); time.sleep(60)"
    )
    async with startup_command(command(source)):
        async with asyncio.timeout(2):
            while not finished.exists():
                await asyncio.sleep(0.01)


async def test_timeout_ignores_not_ready_and_reaps_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    config = command(
        f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "os.write(2,b'NOT READY\\n'); time.sleep(60)",
        timeout_s=0.3,
    )
    with pytest.raises(RuntimeError, match="timed out"):
        async with startup_command(config):
            pytest.fail("NOT READY must not pass readiness")
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_early_exit_and_errors_never_include_output() -> None:
    with pytest.raises(RuntimeError, match="before readiness") as error:
        async with startup_command(command("import os; os.write(2,b'synthetic-private-output\\n'); raise SystemExit(7)")):
            pytest.fail("Exited command must not pass readiness")
    assert "synthetic-private-output" not in str(error.value)


async def test_oversized_line_is_bounded() -> None:
    with pytest.raises(RuntimeError, match="size limit"):
        async with startup_command(command("import os,time; os.write(1,b'x'*100000); time.sleep(60)")):
            pytest.fail("Oversized pending output must not pass readiness")


async def test_cancellation_during_startup_reaps_command(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    config = command(f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)")

    async def start() -> None:
        async with startup_command(config):
            pytest.fail("Cancelled command must not pass readiness")

    task = asyncio.create_task(start())
    async with asyncio.timeout(2):
        while not pid_file.exists():
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


async def test_disabled_startup_runs_no_command(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_spawn(*args: object, **kwargs: object) -> None:
        pytest.fail("Disabled configuration must not spawn")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_spawn)
    async with startup_command(None) as process:
        assert process is None


@pytest.mark.parametrize(
    "values",
    [
        {"argv": []},
        {"argv": ["x"], "ready_marker": ""},
        {"argv": ["x"], "ready_marker": "READY\n"},
        {"argv": ["x"], "timeout_s": 0},
        {"argv": ["x"], "timeout_s": float("nan")},
        {"argv": ["x"], "unknown": True},
    ],
)
def test_invalid_startup_configuration_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StartupCommand.model_validate(values)


def test_startup_command_loads_from_yaml_and_toml(tmp_path: Path) -> None:
    yaml = tmp_path / "startup.yaml"
    yaml.write_text("startup_command:\n  argv: [python3, -u, listener.py]\n")
    toml = tmp_path / "startup.toml"
    toml.write_text('[startup_command]\nargv = ["python3", "-u", "listener.py"]\n')
    left = PgSettings(_env_file=None, config_file=yaml).startup_command
    right = PgSettings(_env_file=None, config_file=toml).startup_command
    assert left == right
    assert left is not None
    assert left.ready_marker == "READY"


async def test_noisy_sigterm_resistant_child_is_drained_on_failure(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    source = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "[os.write(1,b'x'*65536) for _ in range(32)]; time.sleep(60)"
    )
    async with asyncio.timeout(3):
        with pytest.raises(RuntimeError, match="size limit"):
            async with startup_command(command(source)):
                pytest.fail("No READY was emitted")
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
