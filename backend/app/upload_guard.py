"""Upload hardening (plan H.3): Office files are ZIP archives; inspect before parsing.

Rejects macro-enabled documents (vbaProject.bin or a macroEnabled content type,
even if renamed to .docx/.pptx), archive bombs (too large unpacked, or an
extreme compression ratio), encrypted entries, and path-traversal names. The
parsers never execute anything; this stops hostile files before they reach them.
"""

from __future__ import annotations

import io
import zipfile

MAX_UNPACKED = 200 * 1024 * 1024  # 200 MB
MAX_RATIO = 150                   # unpacked / packed, per entry
MAX_ENTRIES = 5000


class RejectedUpload(ValueError):
    pass


def check_office_zip(data: bytes, office: bool = True) -> None:
    """office=False checks any ZIP (e.g. a QTI package) for bombs, unsafe paths,
    encryption and macros, without requiring Office structure."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise RejectedUpload("The file isn't a valid DOCX/PPTX (not a ZIP archive).") from e
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise RejectedUpload("The file has too many parts.")
    total = 0
    for i in infos:
        name = i.filename
        if name.startswith(("/", "\\")) or ".." in name.split("/"):
            raise RejectedUpload("The file contains unsafe paths.")
        if i.flag_bits & 0x1:
            raise RejectedUpload("Encrypted or password-protected files aren't accepted.")
        if name.lower().endswith("vbaproject.bin"):
            raise RejectedUpload("Macro-enabled documents aren't accepted. Save it as a plain .docx/.pptx.")
        total += i.file_size
        if i.compress_size and i.file_size / i.compress_size > MAX_RATIO and i.file_size > 10 * 1024 * 1024:
            raise RejectedUpload("The file looks like an archive bomb (extreme compression).")
    if total > MAX_UNPACKED:
        raise RejectedUpload("The file is too large when unpacked.")
    if not office:
        return
    try:
        ct = zf.read("[Content_Types].xml").decode("utf-8", errors="replace").lower()
    except KeyError as e:
        raise RejectedUpload("The file isn't a valid Office document ([Content_Types].xml missing).") from e
    if "macroenabled" in ct or "vbaproject" in ct:
        raise RejectedUpload("Macro-enabled documents aren't accepted. Save it as a plain .docx/.pptx.")
