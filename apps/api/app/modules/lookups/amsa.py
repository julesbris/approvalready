"""Vessels by unique vessel identifier (UVI) from AMSA's public list of domestic commercial
vessels with a vessel permission (free, no key).

AMSA publishes the list as one Excel file linked from
https://www.amsa.gov.au/list-commercial-vessels-vessel-permission and replaces it every so
often under a new name, so we find the current link on that page (or use
``AMSA_VESSEL_LIST_URL``), download it, and keep an index by UVI in memory for
``AMSA_VESSEL_LIST_MAX_AGE_HOURS``. If a refresh fails we keep using the copy we have.

AMSA doesn't document the file's columns, so we find the header row by its UVI column and
read the others by name. Every column is passed through as it is, except ones that could
name a person (owner, operator, contact details). The list doesn't include certificates of
operation, and a vessel missing from it may simply not need a vessel permission.
"""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from app.core.config import Settings
from app.modules.lookups.client import LookupUnavailable

MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PRIVATE_HEADERS = re.compile(r"owner|operator|contact|e-?mail|phone|address|name of", re.I)
_UVI = re.compile(r"^[A-Z0-9]{3,12}$")


def normalise_uvi(text: str) -> str | None:
    uvi = re.sub(r"[\s-]", "", text.strip().upper())
    return uvi if _UVI.match(uvi) else None


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - 64)
    return index - 1


def read_first_sheet(data: bytes) -> list[list[str]]:
    """Rows of the workbook's first sheet as text. Just enough of the .xlsx format for a
    plain table: shared strings, inline strings and numbers."""
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = set(book.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))  # noqa: S314
            for si in root.iter(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
        workbook = ET.fromstring(book.read("xl/workbook.xml"))  # noqa: S314
        first = workbook.find(f"{_NS}sheets/{_NS}sheet")
        target = "worksheets/sheet1.xml"
        if first is not None and "xl/_rels/workbook.xml.rels" in names:
            rel_id = first.get(f"{_REL_NS}id")
            rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))  # noqa: S314
            for rel in rels:
                if rel.get("Id") == rel_id and rel.get("Target"):
                    target = str(rel.get("Target")).lstrip("/").removeprefix("xl/")
        sheet = ET.fromstring(book.read(f"xl/{target}"))  # noqa: S314
    rows: list[list[str]] = []
    for row in sheet.iter(f"{_NS}row"):
        cells: dict[int, str] = {}
        for i, c in enumerate(row.iter(f"{_NS}c")):
            ref = c.get("r")
            col = _column_index(ref) if ref else i
            kind = c.get("t")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{_NS}t"))
            else:
                v = c.find(f"{_NS}v")
                value = v.text or "" if v is not None else ""
                if kind == "s" and value.isdigit() and int(value) < len(shared):
                    value = shared[int(value)]
            cells[col] = value.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


@dataclass(frozen=True)
class VesselRecord:
    uvi: str
    name: str | None
    displayed_identifier: str | None
    length_m: str | None
    fields: dict[str, str]  # every published column (except personal ones) by header


@dataclass(frozen=True)
class VesselList:
    records: dict[str, VesselRecord]
    source_url: str
    retrieved_at: datetime


def _find(headers: list[str], *patterns: str, exclude: str | None = None) -> int | None:
    for pattern in patterns:
        for i, h in enumerate(headers):
            if re.search(pattern, h, re.I) and not (exclude and re.search(exclude, h, re.I)):
                return i
    return None


def _length(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match is None:
        return None
    number = float(match.group())
    return f"{number:.2f}".rstrip("0").rstrip(".") if 0 < number < 1000 else None


def parse_vessel_list(rows: list[list[str]]) -> dict[str, VesselRecord]:
    header_at = next(
        (
            i
            for i, row in enumerate(rows[:30])
            if any(re.search(r"\bUVI\b|unique vessel identifier", c, re.I) for c in row)
        ),
        None,
    )
    if header_at is None:
        raise LookupUnavailable("AMSA vessel list has no UVI column")
    headers = rows[header_at]
    uvi_col = _find(headers, r"\bUVI\b", r"unique vessel identifier")
    name_col = _find(headers, r"vessel name", r"^name$")
    ident_col = _find(headers, r"displayed", r"identifier|\bmark", exclude=r"unique|UVI")
    length_col = _find(headers, r"length")
    keep = [i for i, h in enumerate(headers) if h and not _PRIVATE_HEADERS.search(h)]
    if name_col is not None and name_col not in keep:
        keep.append(name_col)  # "Vessel name" is the boat's name, not a person's
    records: dict[str, VesselRecord] = {}
    for row in rows[header_at + 1 :]:

        def cell(i: int | None, row: list[str] = row) -> str | None:
            return (row[i] or None) if i is not None and i < len(row) else None

        uvi = normalise_uvi(cell(uvi_col) or "")
        if uvi is None or uvi in records:
            continue
        records[uvi] = VesselRecord(
            uvi=uvi,
            name=cell(name_col),
            displayed_identifier=cell(ident_col),
            length_m=_length(cell(length_col)),
            fields={headers[i]: v for i in sorted(keep) if (v := cell(i))},
        )
    return records


_XLSX_LINK = re.compile(r"""href=["']([^"']+\.xlsx)["']""", re.I)


class AmsaVesselList:
    def __init__(self, http: httpx.AsyncClient, settings: Settings) -> None:
        self.http = http
        self.page_url = settings.amsa_vessel_list_page_url
        self.file_url = settings.amsa_vessel_list_url
        self.max_age = timedelta(hours=settings.amsa_vessel_list_max_age_hours)
        self._list: VesselList | None = None
        self._refresh_after = datetime.min.replace(tzinfo=UTC)
        self._lock = asyncio.Lock()

    async def _get(self, url: str) -> bytes:
        try:
            async with self.http.stream("GET", url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise LookupUnavailable(f"{url} is larger than expected")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise LookupUnavailable(str(exc)) from exc

    async def _current_file_url(self) -> str:
        if self.file_url:
            return self.file_url
        page = (await self._get(self.page_url)).decode("utf-8", "replace")
        links: list[str] = _XLSX_LINK.findall(page)
        if not links:
            raise LookupUnavailable("No vessel list link on the AMSA page")
        preferred = [link for link in links if re.search(r"dcv|vessel", link, re.I)]
        return urljoin(self.page_url, (preferred or links)[0])

    async def _load(self) -> VesselList:
        url = await self._current_file_url()
        data = await self._get(url)
        try:
            rows = await asyncio.to_thread(read_first_sheet, data)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise LookupUnavailable(f"Can't read the AMSA vessel list: {exc}") from exc
        records = parse_vessel_list(rows)
        if not records:
            raise LookupUnavailable("The AMSA vessel list is empty")
        return VesselList(records, url, datetime.now(UTC))

    def _fresh(self) -> bool:
        return self._list is not None and datetime.now(UTC) < self._refresh_after

    async def current(self) -> VesselList:
        async with self._lock:
            if not self._fresh():
                try:
                    self._list = await self._load()
                    self._refresh_after = datetime.now(UTC) + self.max_age
                except LookupUnavailable:
                    if self._list is None:
                        raise
                    # Keep answering from the copy we have; try again a little later.
                    self._refresh_after = datetime.now(UTC) + timedelta(minutes=15)
            assert self._list is not None
            return self._list

    async def find(self, uvi: str) -> tuple[VesselRecord | None, VesselList]:
        vessels = await self.current()
        return vessels.records.get(uvi), vessels
