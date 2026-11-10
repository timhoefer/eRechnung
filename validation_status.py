"""Disposable validation receipts; invoice files and numbering remain untouched."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

_unsaved: dict[Path, dict] = {}


def receipt_path(document: Path) -> Path:
    # No .json suffix: the invoice-number scan treats those as invoice sidecars.
    return document.with_name(f".{document.name}.validation")


def is_receipt(path: Path) -> bool:
    """Only the reserved archive-cache names may bypass data conflicts."""
    return (path.parent.name == "output" and path.name.startswith(".")
            and path.name.endswith((".pdf.validation", ".xml.validation")))


def _stamp(document: Path) -> tuple[int, ...]:
    if document.is_symlink() or not document.is_file():
        raise OSError("Document is missing or linked")
    info = document.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=4096)
def _digest(document: Path, stamp: tuple[int, ...]) -> str:
    with document.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    if _stamp(document) != stamp:
        raise OSError("Document changed while hashing")
    return value


def _write(target: Path, raw: bytes) -> None:
    if target.is_symlink():
        raise OSError("Linked validation receipts are not supported")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent,
                                         prefix=".validation-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_receipt(source: Path, target: Path) -> None:
    """Replace only a disposable cache, atomically; caller checks directory links."""
    _write(target, source.read_bytes())


def _record(raw: bytes, ruleset: str, status: str, profile: str | None = None) -> dict:
    return {"version": 1, "sha256": hashlib.sha256(raw).hexdigest(), "ruleset": ruleset,
            "status": status, "checked_at": datetime.now(UTC).isoformat(),
            "profile": profile if profile in ("en16931", "xrechnung") else None}


def save(document: Path, checked_bytes: bytes, ruleset: str, status: str, profile: str | None = None) -> bool:
    """Caller holds the data lock. Cache only the exact bytes actually checked."""
    record = _record(checked_bytes, ruleset, status, profile)
    if _digest(document, _stamp(document)) != record["sha256"]:
        return False  # An external edit must never inherit the previous result.
    _write(receipt_path(document), json.dumps(record).encode("utf-8"))
    _unsaved.pop(document.absolute(), None)
    return True


def _forget_saved(document: Path) -> None:
    try:
        receipt_path(document).unlink(missing_ok=True)
    except OSError:
        pass  # The in-memory result still takes precedence in this app session.


def remember_unsaved(document: Path, raw: bytes, ruleset: str, status: str, profile: str | None = None) -> None:
    """Keep a failed write visible on subsequent page loads, not just on POST."""
    _unsaved[document.absolute()] = _record(raw, ruleset, status, profile)
    _forget_saved(document)


def relocate_unsaved(source: Path, target: Path) -> None:
    """Keep pending results visible after the data-folder move has committed."""
    for document, record in list(_unsaved.items()):
        if document.is_relative_to(source.absolute()):
            moved = target.absolute() / document.relative_to(source.absolute())
            _unsaved[moved] = record
            del _unsaved[document]
            _forget_saved(moved)


def read(document: Path, ruleset: str | None, profile: str | None = None) -> dict | None:
    """Return a current result or a neutral stale state, never guess success."""
    try:
        receipt = receipt_path(document)
        pending = _unsaved.get(document.absolute())
        if pending is None and receipt.is_symlink():
            return None
        record = pending if pending is not None else json.loads(receipt.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("version") != 1
                or record.get("status") not in {"valid", "invalid", "unavailable"}
                or not isinstance(record.get("sha256"), str)
                or not isinstance(record.get("ruleset"), str)):
            return None
        checked = datetime.fromisoformat(record["checked_at"])
        if checked.tzinfo is None:
            return None
        state = record["status"]
        if not ruleset or record["ruleset"] != ruleset:
            state = "rules_changed"
        if profile in ("en16931", "xrechnung") and record.get("profile") != profile:
            state = "file_changed"  # The archive's expected profile changed.
        try:
            if _digest(document, _stamp(document)) != record["sha256"]:
                state = "file_changed"
        except OSError:
            state = "file_changed"
        if pending is not None and state == "valid":
            state = "unsaved"
        return {"state": state, "checked_at": checked.astimezone().strftime("%d.%m.%Y %H:%M"),
                "saved": pending is None}
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None
