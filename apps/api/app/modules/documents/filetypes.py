"""What files people may upload, and checking that a file really is what it claims to be.

The type is decided from the file's own bytes (magic numbers, and for Word and Excel files
the parts inside the zip container), never from the name or the browser's declared type.
The extension and the declared type must then agree with what the bytes say. Anything we
cannot positively identify is refused.

Word and Excel files are zip archives, so they are also checked for the usual zip tricks
(huge expansion ratios, thousands of entries, encrypted parts) and for macros. Nothing here
parses document content: files are stored and handed back as downloads, never rendered.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass


class FileRejected(ValueError):
    """The upload is not an allowed file. The message is safe to show to the user."""


@dataclass(frozen=True)
class FileType:
    mime: str
    label: str
    extensions: frozenset[str]
    # Other declared types browsers commonly send for this kind of file.
    aliases: frozenset[str] = frozenset()


PDF = FileType("application/pdf", "PDF", frozenset({"pdf"}))
PNG = FileType("image/png", "PNG image", frozenset({"png"}))
JPEG = FileType("image/jpeg", "JPEG image", frozenset({"jpg", "jpeg"}), frozenset({"image/pjpeg"}))
WEBP = FileType("image/webp", "WebP image", frozenset({"webp"}))
HEIC = FileType("image/heic", "HEIC photo", frozenset({"heic", "heif"}), frozenset({"image/heif"}))
DOCX = FileType(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "Word document",
    frozenset({"docx"}),
)
XLSX = FileType(
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "Excel workbook",
    frozenset({"xlsx"}),
)
TXT = FileType("text/plain", "Text file", frozenset({"txt"}))
CSV = FileType(
    "text/csv",
    "CSV file",
    frozenset({"csv"}),
    frozenset({"application/vnd.ms-excel", "text/x-csv", "application/csv", "text/plain"}),
)

ALLOWED: tuple[FileType, ...] = (PDF, PNG, JPEG, WEBP, HEIC, DOCX, XLSX, TXT, CSV)
# Declared types that say nothing (sent when the browser does not know the type).
GENERIC_DECLARED = frozenset({"", "application/octet-stream", "binary/octet-stream"})

ALLOWED_EXTENSIONS = sorted({ext for t in ALLOWED for ext in t.extensions})
ACCEPT_HINT = "PDF, Word, Excel, CSV, text, or a JPEG, PNG, WebP or HEIC image"

# Zip container limits (Word and Excel files).
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_RATIO = 200

_HEIC_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}


def _zip_type(data: bytes) -> FileType:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise FileRejected("This file looks damaged. Save it again and retry.") from None
    if len(entries) > MAX_ZIP_ENTRIES:
        raise FileRejected("This file has too many parts to accept.")
    total = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise FileRejected("Password-protected files can't be accepted. Remove the password.")
        total += entry.file_size
        if entry.file_size > max(entry.compress_size, 1) * MAX_ZIP_RATIO:
            raise FileRejected("This file expands to an unsafe size and can't be accepted.")
    if total > MAX_ZIP_UNCOMPRESSED:
        raise FileRejected("This file expands to an unsafe size and can't be accepted.")
    names = {e.filename for e in entries}
    if "[Content_Types].xml" not in names:
        raise FileRejected(f"This file type isn't accepted. Upload {ACCEPT_HINT}.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise FileRejected("Files with macros can't be accepted. Save it without macros.")
    if "word/document.xml" in names:
        return DOCX
    if "xl/workbook.xml" in names:
        return XLSX
    raise FileRejected(f"This file type isn't accepted. Upload {ACCEPT_HINT}.")


def _is_text(data: bytes) -> bool:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return not any(unicodedata.category(ch) == "Cc" and ch not in "\t\r\n\f" for ch in text)


def detect(data: bytes, extension: str) -> FileType:
    """The allowed type the bytes are, or ``FileRejected``. ``extension`` only chooses
    between the two text types, which have no magic number."""
    if not data:
        raise FileRejected("This file is empty.")
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return HEIC
    if data.startswith(b"PK\x03\x04"):
        return _zip_type(data)
    if _is_text(data):
        return CSV if extension == "csv" else TXT
    raise FileRejected(f"This file type isn't accepted. Upload {ACCEPT_HINT}.")


_UNSAFE_NAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


def clean_filename(raw: str | None) -> str:
    """A display name safe to store and to send back in Content-Disposition."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFC", name)
    name = _UNSAFE_NAME_CHARS.sub("_", name).strip(" .")
    if not name:
        name = "file"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 200 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 10 else name[:200]
    return name


def extension_of(filename: str) -> str:
    _, dot, ext = filename.rpartition(".")
    return ext.lower() if dot else ""


@dataclass(frozen=True)
class CheckedFile:
    filename: str
    extension: str
    declared_mime: str
    type: FileType


def check(data: bytes, filename: str | None, declared_mime: str | None) -> CheckedFile:
    """Identify an upload and make sure its name and declared type agree with its bytes."""
    name = clean_filename(filename)
    ext = extension_of(name)
    if ext not in ALLOWED_EXTENSIONS:
        raise FileRejected(f"This file type isn't accepted. Upload {ACCEPT_HINT}.")
    found = detect(data, ext)
    if ext not in found.extensions:
        raise FileRejected(
            f"This file's name ends in .{ext} but it is a {found.label}. "
            "Rename it or save it in the right format."
        )
    declared = (declared_mime or "").split(";", 1)[0].strip().lower()
    if (
        declared not in GENERIC_DECLARED
        and declared != found.mime
        and declared not in found.aliases
    ):
        raise FileRejected(f"This file's type doesn't match its contents ({found.label}).")
    return CheckedFile(filename=name, extension=ext, declared_mime=declared, type=found)
