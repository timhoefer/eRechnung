"""Shared issuer identities and paths; no Flask import or filesystem writes."""
import hashlib
import json
import re
from pathlib import Path


class IssuerError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def issuer_directory(root: Path, issuer: str) -> Path:
    if issuer != "default" and not re.fullmatch(r"[a-f0-9]{32}", issuer):
        raise IssuerError("invalid_issuer", "Use an issuer ID returned by issuers.")
    directory = root if issuer == "default" else root / "issuers" / issuer
    if ((issuer != "default" and ((root / "issuers").is_symlink() or directory.is_symlink()))
            or (directory / "seller.json").is_symlink() or (directory / "output").is_symlink()):
        raise IssuerError("linked_issuer", "Linked issuer data is not supported.")
    # The root profile may be empty during the app's initial setup.
    if issuer != "default" and not (directory / "seller.json").is_file():
        raise IssuerError("unknown_issuer", "This issuer no longer exists; select an existing profile.")
    return directory


def issuer_profiles(root: Path) -> list[dict]:
    ids = ["default"]
    additional = root / "issuers"
    if additional.is_dir() and not additional.is_symlink():
        ids += sorted(p.name for p in additional.iterdir()
                      if re.fullmatch(r"[a-f0-9]{32}", p.name) and p.is_dir() and not p.is_symlink()
                      and (p / "seller.json").exists())
    profiles = []
    for issuer in ids:
        path = (root if issuer == "default" else additional / issuer) / "seller.json"
        if path.is_symlink():
            continue
        try:
            issuer_directory(root, issuer)
            seller = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            if not isinstance(seller, dict):
                raise ValueError("Invalid issuer data")
            profiles.append({"id": issuer, "label": seller.get("profile_label") or seller.get("name") or "",
                             "name": seller.get("name") or "", "deleted": seller.get("_deleted") is True,
                             "available": path.is_file()})
        except (OSError, ValueError):
            profiles.append({"id": issuer, "label": "", "name": "", "deleted": False, "available": False})
    return profiles


def default_issuer(root: Path, profiles: list[dict]) -> str:
    try:
        preference = json.loads((root / "issuer_preferences.json").read_text(encoding="utf-8"))
        preferred = preference.get("default_issuer") if isinstance(preference, dict) else None
    except (OSError, ValueError):
        preferred = None
    return next((p["id"] for p in profiles if p["id"] == preferred), profiles[0]["id"] if profiles else "default")


def issuer_scope(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]


def seller_revision(seller: dict) -> str:
    fields = {key: value for key, value in seller.items() if key != "last_invoice_number"}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
