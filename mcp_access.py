"""Local, revocable MCP grants and bounded approval requests. No invoice IO."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path


class AccessError(Exception):
    pass


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Access:
    """Caller holds the app's DATA_LOCK, including execution and revocation."""
    def __init__(self, path, write, *, lifetime=300, limit=64):
        self.path = path
        self.write = write
        self.lifetime = lifetime
        self.limit = limit
        self.pending: dict[str, dict] = {}

    def load(self):
        path = self.path()
        if not path.exists():
            return {"enabled": False, "connections": {}}
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("connections"), dict):
                raise ValueError()
            return data
        except (ValueError, OSError) as exc:
            raise AccessError("Agent settings cannot be read; access is disabled.") from exc

    def save(self, data):
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.write(path, data)  # atomic, private (0600) file from the app

    def enable(self, enabled):
        data = self.load()
        data["enabled"] = enabled
        # Disabling invalidates credentials permanently; re-enable never revives them.
        if not enabled:
            data["connections"] = {}
            self.pending.clear()
        self.save(data)

    def create(self, name: str, issuers: list[str], writable: bool, directory: Path,
               *, customer_mode="none", customer_ids=()):
        data = self.load()
        if not data.get("enabled") or len(data["connections"]) >= 20:
            raise AccessError("Enable access first; at most 20 connections are supported.")
        identifier, token = secrets.token_urlsafe(16), secrets.token_urlsafe(32)
        data["connections"][identifier] = {
            "id": identifier, "name": name, "issuers": sorted(set(issuers)),
            "active": True, "writable": writable,
            "customer_mode": customer_mode, "customer_ids": sorted(set(customer_ids)),
            "scope": digest(str(directory.resolve())), "token_hash": digest(token),
        }
        self.save(data)
        return token

    def set_active(self, identifier, active):
        data = self.load()
        connection = data["connections"].get(identifier)
        if not data.get("enabled") or not connection:
            raise AccessError("Access disabled or connection revoked.")
        connection["active"] = active
        self.save(data)
        if not active:
            self.clear_requests(identifier)

    def clear_requests(self, identifier):
        self.pending = {k: v for k, v in self.pending.items() if v["connection"]["id"] != identifier}

    def renew(self, identifier, expected):
        """Replace only the credential after the UI has reviewed this exact grant."""
        data = self.load()
        connection = data["connections"].get(identifier)
        if not data.get("enabled") or not connection or connection != expected:
            raise AccessError("Connection changed or revoked. Review it again.")
        token = secrets.token_urlsafe(32)
        connection["token_hash"] = digest(token)
        self.save(data)
        self.clear_requests(identifier)
        return token

    def revoke(self, identifier):
        data = self.load()
        data["connections"].pop(identifier, None)
        self.save(data)
        self.clear_requests(identifier)

    def connection(self, identifier, directory):
        data = self.load()
        connection = data["connections"].get(identifier) if data.get("enabled") else None
        if (not connection or connection.get("active", True) is not True
                or connection.get("scope") != digest(str(directory.resolve()))):
            raise AccessError("Access disabled, paused, revoked or bound to another data directory.")
        return connection

    def authenticate(self, token, directory):
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise AccessError("Invalid agent credential.")
        for identifier, candidate in self.load()["connections"].items():
            if secrets.compare_digest(candidate.get("token_hash", ""), digest(token)):
                return self.connection(identifier, directory)
        raise AccessError("Invalid agent credential.")

    def prune(self):
        now = time.monotonic()
        for entry in self.pending.values():
            if entry["status"] == "pending" and entry["expires"] <= now:
                entry.update(status="expired", confirmation=None, arguments={})
        self.pending = {k: v for k, v in self.pending.items() if v["expires"] + 600 > now}

    def propose(self, connection, operation, arguments, confirmation):
        self.prune()
        # Retries return the same request. Do not silently evict an approval the user is reviewing.
        for identifier, entry in self.pending.items():
            if (entry["status"] == "pending" and entry["connection"] == connection
                    and entry["operation"] == operation and entry["arguments"] == arguments
                    and entry["confirmation"]["fingerprint"] == confirmation["fingerprint"]):
                return identifier
        if len(self.pending) >= self.limit:
            raise AccessError("Too many pending requests. Review or wait for older requests to expire.")
        identifier = secrets.token_urlsafe(24)
        self.pending[identifier] = {
            "connection": dict(connection), "operation": operation,
            "arguments": json.loads(json.dumps(arguments)), "confirmation": confirmation,
            "expires": time.monotonic() + self.lifetime, "status": "pending",
        }
        return identifier

    def get(self, identifier, connection=None):
        self.prune()
        entry = self.pending.get(identifier)
        if not entry or (connection is not None and entry["connection"] != connection):
            raise AccessError("Unknown request.")
        return entry
