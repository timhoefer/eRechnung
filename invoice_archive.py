"""Shared local archive writer for the app and optional assistant.

The PDF is published last, so the archive only lists complete file sets. A durable
pending transaction lets a retry finish after an interrupted write, including the
invoice-number update. Existing files are never replaced. Locks coordinate local
processes, not different computers connected through a cloud sync service.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from invoice_core import safe_name


class ArchiveError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


_mutex = threading.RLock()
_held = threading.local()


@contextmanager
def data_lock(directory: Path):
    """Reentrant in a thread and exclusive across app/CLI processes."""
    directory = directory.resolve()
    with _mutex:
        held: set[Path] = getattr(_held, "directories", set())
        if directory in held:
            yield
            return
        lock_path = directory / ".erechnung.lock"
        if lock_path.is_symlink():
            raise ArchiveError("linked_archive", "The data lock must not be a link.")
        with lock_path.open("a+b") as lock:
            if sys.platform == "win32":
                import msvcrt
                lock.write(b"\0")
                lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
            _held.directories = held | {directory}
            try:
                yield
            finally:
                _held.directories = held
                if sys.platform == "win32":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)


def canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seller_details(seller: dict) -> dict:
    # Bookkeeping changes must not invalidate another prepared invoice/retry.
    return {key: value for key, value in seller.items() if key != "last_invoice_number"}


def _read(path: Path) -> dict:
    if path.is_symlink():
        raise ArchiveError("linked_archive", "Linked archive files are not supported.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ArchiveError("invalid_archive", f"Invalid JSON in {path.name}.") from exc
    if not isinstance(value, dict):
        raise ArchiveError("invalid_archive", "Expected an archive JSON object.")
    return value


def _sync_dir(path: Path) -> None:
    if sys.platform != "win32":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _remember_number(seller_file: Path, number: str) -> None:
    seller = _read(seller_file)
    previous = seller.get("last_invoice_number", "")
    # A delayed/older invoice must not move the normal YYYY-NNN counter back.
    old = re.fullmatch(r"(\d{4})-(\d+)", previous or "")
    new = re.fullmatch(r"(\d{4})-(\d+)", number)
    if old and new and tuple(map(int, old.groups())) >= tuple(map(int, new.groups())):
        return
    if number == previous:
        return
    seller["last_invoice_number"] = number
    fd, name = tempfile.mkstemp(prefix=".seller-", dir=seller_file.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(seller))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, seller_file)
        _sync_dir(seller_file.parent)
    finally:
        temporary.unlink(missing_ok=True)


def archived_number_files(output: Path, *, strict: bool = False) -> dict[str, list[str]]:
    numbers: dict[str, list[str]] = {}
    for path in output.glob("*.json"):
        try:
            invoice = _read(path).get("invoice")
            if not isinstance(invoice, dict):
                raise ValueError("Missing invoice data")
            number = invoice.get("number")
            if not isinstance(number, str) or not number.strip():
                raise ValueError("Missing invoice number")
            numbers.setdefault(number.strip(), []).append(path.name)
        except (OSError, ValueError, ArchiveError) as exc:
            if strict:
                raise ArchiveError("invalid_archive", f"Cannot check invoice numbers in {path.name}.") from exc
    for path in output.glob("Rechnung_*.pdf"):
        if not path.with_suffix(".json").exists():
            # Older app versions used " (2)", " (3)" for duplicate filenames.
            number = re.sub(r" \(\d+\)$", "", path.stem[len("Rechnung_"):])
            numbers.setdefault(number, []).append(path.name)
    return numbers


def archived_numbers(output: Path, *, strict: bool = False) -> set[str]:
    return set(archived_number_files(output, strict=strict))


def _matches(path: Path, checksum: str) -> bool:
    return not path.is_symlink() and path.is_file() and digest(path.read_bytes()) == checksum


def recover_archive(output: Path, seller_file: Path) -> None:
    """Finish a previously authorized transaction. Caller holds data_lock."""
    pending = output / ".archive-pending"
    if output.is_symlink() or pending.is_symlink():
        raise ArchiveError("linked_archive", "The archive must not be a link.")
    if not pending.exists():
        return
    manifest = _read(pending / "manifest.json")
    number, checksums = manifest.get("number"), manifest.get("sha256")
    if not isinstance(number, str) or not isinstance(checksums, dict):
        raise ArchiveError("invalid_archive", "Invalid pending archive transaction.")
    stem = "Rechnung_" + safe_name(number)
    if set(checksums) not in ({stem + ".pdf", stem + ".json"},
                              {stem + ".pdf", stem + ".json", stem + ".xml"}):
        raise ArchiveError("invalid_archive", "Invalid pending archive transaction.")
    # Check everything before publishing anything. A changed file is a conflict,
    # even during recovery; never repair it by overwriting the user's version.
    for name, checksum in checksums.items():
        if not _matches(pending / name, checksum):
            raise ArchiveError("changed_archive", "A pending invoice file changed.")
        target = output / name
        if (target.exists() or target.is_symlink()) and not _matches(target, checksum):
            raise ArchiveError("changed_archive", f"Archive recovery conflict: {name}.")
    for name in sorted(checksums, key=lambda name: name.endswith(".pdf")):
        target = output / name
        if not target.exists():
            # Atomic and exclusive: the PDF cannot be observed half-written.
            os.link(pending / name, target)
            _sync_dir(output)
    _remember_number(seller_file, number)
    # Rename first: a crash during cleanup must not leave half a journal to replay.
    completed = output / ".archive-completed"
    if completed.exists():
        shutil.rmtree(completed)
    pending.rename(completed)
    _sync_dir(output)
    shutil.rmtree(completed)


def archive_invoice(data: dict, pdf: bytes, xml: bytes, output: Path,
                    seller_file: Path, *, expected_seller: dict | None = None) -> dict:
    """Publish already validated invoice files; identical retries reuse originals."""
    number = data["invoice"]["number"].strip()
    if not number:
        raise ArchiveError("missing_number", "An invoice number is required.")
    sidecar = {key: data[key] for key in ("seller", "buyer", "invoice", "items")}
    identity = dict(sidecar, seller=seller_details(sidecar["seller"]))
    fingerprint = digest(canonical(identity))
    stem = "Rechnung_" + safe_name(number)
    with data_lock(seller_file.parent):
        recover_archive(output, seller_file)
        if expected_seller is not None and seller_details(_read(seller_file)) != seller_details(expected_seller):
            raise ArchiveError("stale_seller", "Issuer details changed. Create and review a fresh draft.")
        output.mkdir(parents=True, exist_ok=True)
        sidecar_path = output / (stem + ".json")
        if sidecar_path.exists():
            stored = _read(sidecar_path)
            receipt = stored.get("_archive", {})
            if not isinstance(receipt, dict):
                raise ArchiveError("invalid_archive", "Invalid archive receipt.")
            if receipt.get("fingerprint") == fingerprint:
                hashes = receipt.get("sha256")
                if not isinstance(hashes, dict) or any(key not in stored for key in ("seller", "buyer", "invoice", "items")):
                    raise ArchiveError("invalid_archive", "Invalid archive receipt.")
                expected = {stem + ".pdf"}
                if data["invoice"]["profile"] == "xrechnung":
                    expected.add(stem + ".xml")
                stored_identity = {key: stored[key] for key in ("seller", "buyer", "invoice", "items")}
                stored_identity["seller"] = seller_details(stored_identity["seller"])
                if (set(hashes) != expected or digest(canonical(stored_identity)) != fingerprint
                        or not all(_matches(output / name, checksum) for name, checksum in hashes.items())):
                    raise ArchiveError("changed_archive", "An archived invoice file changed; no files were overwritten.")
                return {"reused": True, "filename": stem + ".pdf",
                        "files": [str(output / name) for name in [stem + ".json", *sorted(hashes)]]}
        if number in archived_numbers(output, strict=True) or any(
            (output / (stem + suffix)).exists() or (output / (stem + suffix)).is_symlink()
            for suffix in (".pdf", ".json", ".xml")
        ):
            raise ArchiveError("number_conflict", "The archive already contains this number or filename. Nothing was overwritten.")
        payloads = {stem + ".pdf": pdf}
        if data["invoice"]["profile"] == "xrechnung":
            payloads[stem + ".xml"] = xml
        sidecar["_archive"] = {"fingerprint": fingerprint,
                               "sha256": {name: digest(content) for name, content in payloads.items()}}
        payloads[stem + ".json"] = canonical(sidecar)
        staging = Path(tempfile.mkdtemp(prefix=".archive-stage-", dir=output))
        try:
            for name, content in payloads.items():
                _write(staging / name, content)
            _write(staging / "manifest.json", canonical({"number": number,
                "sha256": {name: digest(content) for name, content in payloads.items()}}))
            _sync_dir(staging)
            staging.rename(output / ".archive-pending")
            _sync_dir(output)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        # On an I/O failure the durable journal stays intact for the next attempt.
        recover_archive(output, seller_file)
        return {"reused": False, "filename": stem + ".pdf",
                "files": [str(output / name) for name in payloads]}
