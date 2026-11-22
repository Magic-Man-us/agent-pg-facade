from __future__ import annotations

import asyncio
import os
import signal
from asyncio.subprocess import Process
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from pydantic import BaseModel

from pgfacade.shared.config import CONTRACT_CONFIG
from pgfacade.shared.types import CommandArgv, ReadyMarker, StartupTimeoutSeconds, StopTimeoutSeconds

_OUTPUT_CHUNK_BYTES = 4096
_OUTPUT_LINE_LIMIT = 64 * 1024


class StartupCommand(BaseModel):
    model_config = CONTRACT_CONFIG

    argv: CommandArgv
    ready_marker: ReadyMarker = "READY"
    timeout_s: StartupTimeoutSeconds = 30.0
    stop_timeout_s: StopTimeoutSeconds = 5.0


async def _wait_ready(process: Process, marker: ReadyMarker) -> None:
    if process.stdout is None:
        raise RuntimeError("Startup command output is unavailable")
    expected = marker.encode()
    while True:
        try:
            line = await process.stdout.readline()
        except ValueError:
            raise RuntimeError("Startup command output line exceeds the size limit") from None
        if not line.endswith(b"\n"):
            raise RuntimeError("Startup command exited before readiness")
        if process.returncode is not None and process.returncode != 0:
            raise RuntimeError("Startup command failed before readiness")
        if line.strip() == expected:
            return


async def _drain(process: Process) -> None:
    if process.stdout is not None:
        while await process.stdout.read(_OUTPUT_CHUNK_BYTES):
            pass


async def _stop(process: Process, timeout_s: StopTimeoutSeconds) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        async with asyncio.timeout(timeout_s):
            await process.wait()
    except TimeoutError:
        pass
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


@asynccontextmanager
async def startup_command(config: StartupCommand | None) -> AsyncIterator[Process | None]:
    if config is None:
        yield None
        return
    try:
        process = await asyncio.create_subprocess_exec(
            *config.argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            limit=_OUTPUT_LINE_LIMIT,
        )
    except OSError:
        raise RuntimeError("Unable to start configured startup command") from None
    drain: asyncio.Task[None] | None = None
    try:
        try:
            async with asyncio.timeout(config.timeout_s):
                await _wait_ready(process, config.ready_marker)
        except TimeoutError:
            raise RuntimeError("Startup command readiness timed out") from None
        drain = asyncio.create_task(_drain(process))
        yield process
    finally:
        if drain is None:
            drain = asyncio.create_task(_drain(process))
        cleanup = asyncio.create_task(_stop(process, config.stop_timeout_s))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise
        finally:
            if drain is not None:
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
