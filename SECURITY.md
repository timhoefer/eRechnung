# Security Policy

This is a **local, offline** tool (it binds to `127.0.0.1`). It is a personal
project provided *as is*, without active maintenance or guaranteed response times.

## Reporting a vulnerability

Please report security issues **privately**, not via public issues:

- Preferred: GitHub → **Security → Report a vulnerability** (private advisory).

Helpful details: affected version/commit, steps to reproduce, and impact.

## Scope notes

- The app is intended to run **only on the local machine**. Do not expose it on a
  network or the internet — it has no authentication.
- Built-in protections: Host-header allowlist + Origin/Referer checks (CSRF /
  DNS-rebinding), input validation, a hardened XML parser, and an upload size limit.
- The Werkzeug debugger is **off** by default (only `FLASK_DEBUG=1` enables it) and
  must never be enabled on a shared machine.

## No warranty

The software is provided without warranty of any kind (see `LICENSE`). It generates
tax-relevant documents — always verify generated invoices yourself.
