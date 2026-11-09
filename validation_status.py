"""Disposable validation receipts; invoice files and numbering remain untouched."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path


def receipt_path(document: Path) -> Path:
    # No .json suffix: the invoice-number scan treats those as invoice sidecars.
    return document.with_name(f".{document.name}.validation")


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


def save(document: Path, checked_bytes: bytes, ruleset: str, status: str) -> None:
    """Caller holds the data lock. Cache only the exact bytes actually checked."""
    expected = hashlib.sha256(checked_bytes).hexdigest()
    if _digest(document, _stamp(document)) != expected:
        return  # An external edit must never inherit the previous result.
    target = receipt_path(document)
    if target.is_symlink():
        raise OSError("Linked validation receipts are not supported")
    record = {"version": 1, "sha256": expected, "ruleset": ruleset,
              "status": status, "checked_at": datetime.now(UTC).isoformat()}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=document.parent,
                                         prefix=".validation-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read(document: Path, ruleset: str | None) -> dict | None:
    """Return a current result or a neutral stale state, never guess success."""
    try:
        receipt = receipt_path(document)
        if receipt.is_symlink():
            return None
        record = json.loads(receipt.read_text(encoding="utf-8"))
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
        try:
            if _digest(document, _stamp(document)) != record["sha256"]:
                state = "file_changed"
        except OSError:
            state = "file_changed"
        return {"state": state, "checked_at": checked.astimezone().strftime("%d.%m.%Y %H:%M")}
    except (OSError, ValueError, TypeError, KeyError):
        return None
