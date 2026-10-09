"""Malware scanning behind an interface, chosen by ``MALWARE_SCANNER``.

* ``clamav``: the clamd daemon (the ``clamav`` service in Docker Compose), spoken to over
  TCP with its ``INSTREAM`` command. No files are shared with the scanner container.
* ``eicar``: flags only the industry-standard EICAR test file. It lets development and
  tests exercise the whole quarantine path without a 1 GB signature database, and is
  refused in production.

A scanner that cannot be reached raises ``ScannerUnavailable``; the job retries later and
the document stays unusable meanwhile (it is never treated as clean by default).
"""

from __future__ import annotations

import asyncio
import contextlib
import struct
from dataclasses import dataclass
from typing import Protocol

from app.core.config import MalwareScannerKind, Settings

# The EICAR anti-malware test file (harmless by design; every scanner detects it). Built from
# two halves so this source file is not itself flagged by scanners.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class ScannerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanResult:
    infected: bool
    signature: str | None = None


class MalwareScanner(Protocol):
    name: str

    async def scan(self, data: bytes) -> ScanResult: ...


class EicarScanner:
    name = "eicar"

    async def scan(self, data: bytes) -> ScanResult:
        if EICAR in data:
            return ScanResult(infected=True, signature="Eicar-Test-Signature")
        return ScanResult(infected=False)


class ClamdScanner:
    """Minimal clamd client: ``zINSTREAM`` with 64 KiB chunks, then a zero-length chunk."""

    name = "clamav"
    CHUNK = 64 * 1024

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def _exchange(self, data: bytes) -> bytes:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        try:
            writer.write(b"zINSTREAM\0")
            for start in range(0, len(data), self.CHUNK):
                chunk = data[start : start + self.CHUNK]
                writer.write(struct.pack("!I", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack("!I", 0))
            await writer.drain()
            return await reader.readuntil(b"\0")
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def scan(self, data: bytes) -> ScanResult:
        try:
            raw = await asyncio.wait_for(self._exchange(data), self.timeout)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise ScannerUnavailable(f"clamd unreachable: {exc!r}") from exc
        reply = raw.rstrip(b"\0").decode("utf-8", "replace").strip()
        # "stream: OK", "stream: Eicar-Signature FOUND", "INSTREAM size limit exceeded. ERROR"
        if reply.endswith("FOUND"):
            signature = reply.removeprefix("stream:").removesuffix("FOUND").strip()
            return ScanResult(infected=True, signature=signature or "unknown")
        if reply.endswith("OK"):
            return ScanResult(infected=False)
        raise ScannerUnavailable(f"clamd error: {reply[:200]}")


def create_scanner(settings: Settings) -> MalwareScanner:
    if settings.malware_scanner == MalwareScannerKind.CLAMAV:
        return ClamdScanner(
            settings.clamav_host, settings.clamav_port, settings.clamav_timeout_seconds
        )
    return EicarScanner()
