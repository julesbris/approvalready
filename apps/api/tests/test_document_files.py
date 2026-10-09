"""File type checks, storage backends, scanners and report rendering (no database)."""

from __future__ import annotations

import asyncio
import io
import struct
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Environment, MalwareScannerKind, StorageBackendKind
from app.modules.documents import filetypes, render
from app.modules.documents.filetypes import FileRejected, check, clean_filename
from app.modules.documents.scanner import (
    EICAR,
    ClamdScanner,
    EicarScanner,
    ScannerUnavailable,
)
from app.modules.documents.storage import (
    LocalStorage,
    S3Storage,
    StorageError,
    content_disposition,
)
from app.modules.documents.templates import load_bundled
from tests.conftest import make_settings

PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32
TXT = "text/plain"
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32


def ooxml(*parts: str, extra: dict[str, bytes] | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for part in parts:
            z.writestr(part, "<x/>")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return out.getvalue()


DOCX = ooxml("word/document.xml")
XLSX = ooxml("xl/workbook.xml")


# --- File types ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name", "declared", "mime"),
    [
        (PDF, "plan.pdf", "application/pdf", "application/pdf"),
        (PDF, "PLAN.PDF", "", "application/pdf"),
        (PNG, "site.png", "image/png", "image/png"),
        (JPEG, "photo.jpeg", "image/pjpeg", "image/jpeg"),
        (JPEG, "photo.jpg", "application/octet-stream", "image/jpeg"),
        (WEBP, "photo.webp", "image/webp", "image/webp"),
        (HEIC, "IMG_0001.HEIC", "image/heif", "image/heic"),
        (DOCX, "letter.docx", filetypes.DOCX.mime, filetypes.DOCX.mime),
        (XLSX, "costs.xlsx", filetypes.XLSX.mime, filetypes.XLSX.mime),
        ("Notes \u2013 caf\u00e9\n".encode(), "notes.txt", "text/plain; charset=utf-8", TXT),
        (b"a,b\n1,2\n", "lots.csv", "application/vnd.ms-excel", "text/csv"),
    ],
)
def test_allowed_files_are_identified_from_their_bytes(
    data: bytes, name: str, declared: str, mime: str
) -> None:
    assert check(data, name, declared).type.mime == mime


@pytest.mark.parametrize(
    ("data", "name", "declared", "message"),
    [
        (b"", "empty.pdf", "application/pdf", "empty"),
        (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00", "setup.exe", "", "isn't accepted"),
        (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00", "report.pdf", "application/pdf", "isn't accepted"),
        (PDF, "plan.png", "image/png", "ends in .png but it is a PDF"),
        (PDF, "plan", "application/pdf", "isn't accepted"),
        (PDF, "plan.pdf", "image/png", "doesn't match"),
        (b"<svg onload=alert(1)>", "logo.svg", "image/svg+xml", "isn't accepted"),
        (b"<html><script>x</script>", "page.html", "text/html", "isn't accepted"),
        (b"text with a \x00 nul", "notes.txt", "text/plain", "isn't accepted"),
        (ooxml("other.xml"), "letter.docx", "", "isn't accepted"),
        (
            ooxml("word/document.xml", extra={"word/vbaProject.bin": b"x"}),
            "letter.docx",
            "",
            "macros",
        ),
        (b"PK\x03\x04 not really a zip", "letter.docx", "", "damaged"),
    ],
)
def test_other_files_are_refused(data: bytes, name: str, declared: str, message: str) -> None:
    with pytest.raises(FileRejected, match=message):
        check(data, name, declared)


def test_zip_bombs_are_refused() -> None:
    bomb = ooxml("word/document.xml", extra={"word/media/big.bin": b"\0" * (50 * 1024 * 1024)})
    assert len(bomb) < 1024 * 1024
    with pytest.raises(FileRejected, match="unsafe size"):
        check(bomb, "letter.docx", "")


def test_filenames_are_made_safe() -> None:
    assert clean_filename("C:\\Users\\me\\Site plan.pdf") == "Site plan.pdf"
    assert clean_filename("../../etc/passwd") == "passwd"
    assert clean_filename('a"b<c>\r\nd.pdf') == "a_b_c_d.pdf"
    assert clean_filename("   ") == "file"
    long = clean_filename("x" * 300 + ".pdf")
    assert len(long) == 200 and long.endswith(".pdf")


# --- Storage ---------------------------------------------------------------------------


async def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path))
    await storage.put("uploads/org/doc", b"hello", "text/plain")
    assert await storage.get("uploads/org/doc") == b"hello"
    assert (tmp_path / "uploads/org/doc").stat().st_mode & 0o777 == 0o600
    await storage.move("uploads/org/doc", "quarantine/org/doc")
    assert not (tmp_path / "uploads/org/doc").exists()
    assert await storage.get("quarantine/org/doc") == b"hello"
    await storage.delete("quarantine/org/doc")
    with pytest.raises(StorageError):
        await storage.get("quarantine/org/doc")
    assert await storage.signed_download_url("uploads/org/doc", "a.txt", "text/plain") is None


@pytest.mark.parametrize("key", ["../outside", "uploads/../../x", "/etc/passwd", "uploads", ""])
async def test_storage_keys_cannot_escape(tmp_path: Path, key: str) -> None:
    with pytest.raises(StorageError):
        await LocalStorage(str(tmp_path)).put(key, b"x", "text/plain")


def test_content_disposition_is_always_an_attachment() -> None:
    header = content_disposition('Plan "v2" \u2013 caf\u00e9.pdf')
    assert header.startswith('attachment; filename="Plan _v2_ _ caf_.pdf"')
    assert unquote(header.split("filename*=UTF-8''")[1]) == 'Plan "v2" \u2013 caf\u00e9.pdf'


async def test_s3_downloads_are_short_lived_signed_attachments() -> None:
    settings = make_settings(
        storage_backend=StorageBackendKind.S3,
        storage_s3_bucket="ar-docs",
        storage_s3_region="ap-southeast-2",
        storage_s3_access_key_id="AKIAEXAMPLE",
        storage_s3_secret_access_key=SecretStr("secret"),
        storage_signed_url_seconds=60,
    )
    url = await S3Storage(settings).signed_download_url(
        "uploads/org/doc", "plan.pdf", "application/pdf"
    )
    assert url is not None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert "ar-docs" in parsed.netloc + parsed.path and parsed.path.endswith("uploads/org/doc")
    assert query["X-Amz-Expires"] == ["60"]
    assert query["response-content-disposition"][0].startswith("attachment;")


def test_production_needs_a_real_scanner_and_a_bucket_for_s3() -> None:
    safe: dict[str, Any] = {
        "app_env": Environment.PRODUCTION,
        "secret_key": SecretStr("x" * 48),
        "cors_origins": ["https://app.example"],
    }
    with pytest.raises(ValidationError, match="MALWARE_SCANNER"):
        make_settings(**safe, malware_scanner=MalwareScannerKind.EICAR)
    with pytest.raises(ValidationError, match="STORAGE_S3_BUCKET"):
        make_settings(**safe, storage_backend=StorageBackendKind.S3)
    assert make_settings(**safe).malware_scanner == MalwareScannerKind.CLAMAV


# --- Scanners --------------------------------------------------------------------------


async def test_eicar_scanner_finds_only_the_test_file() -> None:
    scanner = EicarScanner()
    assert (await scanner.scan(b"prefix " + EICAR)).infected
    assert not (await scanner.scan(PDF)).infected


async def _fake_clamd(reply: bytes, received: list[bytes]) -> tuple[asyncio.Server, int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        body = b""
        while True:
            (size,) = struct.unpack("!I", await reader.readexactly(4))
            if size == 0:
                break
            body += await reader.readexactly(size)
        received.append(body)
        writer.write(reply)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.parametrize(
    ("reply", "infected", "signature"),
    [
        (b"stream: OK\0", False, None),
        (b"stream: Win.Test.EICAR_HDB-1 FOUND\0", True, "Win.Test.EICAR_HDB-1"),
    ],
)
async def test_clamd_scanner_streams_the_file(
    reply: bytes, infected: bool, signature: str | None
) -> None:
    received: list[bytes] = []
    server, port = await _fake_clamd(reply, received)
    async with server:
        data = b"x" * (ClamdScanner.CHUNK * 2 + 5)
        result = await ClamdScanner("127.0.0.1", port, 5).scan(data)
    assert received == [data]
    assert (result.infected, result.signature) == (infected, signature)


async def test_clamd_errors_and_outages_are_not_treated_as_clean() -> None:
    received: list[bytes] = []
    server, port = await _fake_clamd(b"INSTREAM size limit exceeded. ERROR\0", received)
    async with server:
        with pytest.raises(ScannerUnavailable, match="clamd error"):
            await ClamdScanner("127.0.0.1", port, 5).scan(b"data")
    with pytest.raises(ScannerUnavailable, match="unreachable"):
        await ClamdScanner("127.0.0.1", port, 1).scan(b"data")


# --- Rendering -------------------------------------------------------------------------

BODY = "<h2>Findings</h2><p>{{ meta.project_title }}</p>"


def context(**meta: Any) -> dict[str, Any]:
    return {
        "meta": {
            "title": "Planning assessment report",
            "project_title": "Granny flat",
            "project_reference": "PLN-ABC123",
            "project_status": "Assessed",
            "assessed_on": "9 October 2026",
            "generated_at": "9 October 2026, 6:00 PM Brisbane time",
            "document_id": "doc-1",
            "template_key": "PLANNING_ASSESSMENT",
            "template_version": 1,
            "engine_version": "rules-1",
            "facts_hash": "abc",
            "review_status": "Not reviewed by a professional",
            "review_status_detail": "No professional has checked this.",
            **meta,
        },
        "assumptions": [{"label": "Land area", "value": "812.25"}],
        "missing": ["Zone"],
        "sources": [
            {
                "citation": "s 1",
                "document_title": "Test scheme",
                "organisation_name": "Test Council",
                "url": "https://example.com",
                "verification": "verified",
                "in_force": True,
            }
        ],
        "limitations": ["Does not check overlays."],
        "review": {"reviewer": None, "decided_on": None, "notes": None, "changes": []},
    }


def test_every_report_carries_the_required_sections() -> None:
    html = render.render_html(BODY, context())
    for section in render.REQUIRED_SECTIONS:
        assert f'data-section="{section}"' in html
    for text in ("PLN-ABC123", "Not reviewed by a professional", "Land area", "Zone", "s 1"):
        assert text in html
    with pytest.raises(render.RenderError, match="missing required sections: sources"):
        render.check_required(html.replace('data-section="sources"', ""))


def test_reviewed_reports_show_the_reviewer_and_their_changes() -> None:
    ctx = context(review_status="Reviewed and approved by a professional")
    ctx["review"] = {
        "reviewer": "Pat Planner, Town planner, Coastal Planning",
        "decided_on": "10 October 2026",
        "notes": "Checked against the scheme.",
        "changes": [
            {
                "finding": "Secondary dwelling size",
                "before": "Approval likely required (Likely)",
                "after": "Approval required (Verified)",
                "reason": "Table 5.5.1 makes this assessable.",
                "source": "CairnsPlan, cl. 5.5",
            }
        ],
    }
    html = render.render_html(BODY, ctx)
    for text in (
        "Reviewed and approved by a professional",
        "Pat Planner, Town planner, Coastal Planning, 10 October 2026",
        "Checked against the scheme.",
        "Approval required (Verified)",
        "source: CairnsPlan, cl. 5.5",
    ):
        assert text in html, text
    word = render.html_to_docx(html, title="t")
    assert word.startswith(b"PK")


def test_templates_are_sandboxed_and_escaped() -> None:
    html = render.render_html(BODY, context(project_title="<script>alert(1)</script>"))
    assert "<script>" not in html and "&lt;script&gt;" in html
    with pytest.raises(render.RenderError):
        render.render_html("{{ meta.__class__.__mro__ }}", context())
    with pytest.raises(render.RenderError):
        render.render_html("{{ not_in_context }}", context())


def test_pdf_and_word_output() -> None:
    html = render.render_html(BODY, context())
    pdf = render.html_to_pdf(html)
    assert pdf.startswith(b"%PDF-")
    docx = render.html_to_docx(html, title="Planning assessment report - PLN-ABC123")
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        document = z.read("word/document.xml").decode()
        core = z.read("docProps/core.xml").decode()
    for text in ("PLN-ABC123", "Not reviewed by a professional", "Does not check overlays."):
        assert text in document
    assert "PLN-ABC123" in core


def test_pdf_rendering_never_fetches_resources(tmp_path: Path) -> None:
    secret = tmp_path / "secret.css"
    secret.write_text("body { color: red }")
    html = render.render_html(
        f'<img src="file://{tmp_path}/x.png"><link rel="stylesheet" href="file://{secret}">'
        '<img src="http://169.254.169.254/latest/meta-data">',
        context(),
    )
    assert render.html_to_pdf(html).startswith(b"%PDF-")  # rendered without the resources


def test_bundled_templates_load() -> None:
    templates = {t.key: t for t in load_bundled()}
    assert set(templates) == {
        "BUSINESS_APPROVAL_MAP",
        "GRANT_ELIGIBILITY",
        "PLANNING_ASSESSMENT",
        "SMS",
        "VESSEL_PATHWAY",
    }
    for template in templates.values():
        assert {str(f) for f in template.output_formats} == {"PDF", "DOCX", "HTML"}
    assert templates["BUSINESS_APPROVAL_MAP"].vertical == "BUSINESS"
    assert templates["VESSEL_PATHWAY"].vertical == templates["SMS"].vertical == "VESSEL"
    assert templates["GRANT_ELIGIBILITY"].vertical == "GRANT"
