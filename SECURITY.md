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

## Data at rest

The app stores invoice data on your machine, in your data folder (by default next to the app,
or a folder you choose — e.g. a synced Dropbox folder). It is stored **unencrypted**:

- `seller.json`, `customers.json` — your master data and saved customers.
- `output/` — the generated invoice **PDFs**, plus a **JSON "sidecar"** next to each
  PDF (same name) holding the structured source data used for the "reuse as
  template" and archive-preview features.

These files contain **plaintext personal and banking data** (e.g. IBAN/BIC, tax
numbers, customer names and addresses). Note the same payment and contact details
are already printed in the invoice PDFs themselves; the sidecars are a structured
copy. The sidecar may also include fields not shown on the PDF (e.g. your tax
number when "hide tax number" is enabled).

Protect this folder like any financial document folder:

- Enable full-disk encryption (macOS **FileVault**).
- Do not share the data/`output` folder via unprotected links or public locations.
- If you sync it (e.g. Dropbox), be aware the data then also lives with that provider.

## No warranty

The software is provided without warranty of any kind (see `LICENSE`). It generates
tax-relevant documents — always verify generated invoices yourself.

## Confirmation of destructive changes

The app requires an operation-bound confirmation before deleting or changing
existing saved records. Confirmations are single-use, expire, and are invalidated
by cancellation or a changed request/state. This is an accidental-change safeguard,
not human authentication: software controlling the app can confirm the dialog.
It does not cover direct file access or separate command-line tools.

## Experimental MCP access

MCP is off by default, hidden behind `ERECHNUNG_MCP=1`, and additionally requires
explicit opt-in in the app. Each connection has a revocable bearer credential,
selected issuer IDs and read-only or write-request permission. Customer data and
saved items are shared across issuers; there is no per-customer restriction.
Credentials are bound to the selected data directory. A directory change denies
those credentials until the original directory is selected again or a new
connection is granted. Newly created issuers are never automatically granted.

The stdio bridge contacts only `http://127.0.0.1:<port>` on the existing app, with
no proxies or redirects. It does not start another network listener or load
invoice files directly. The app validates credentials and scopes on every call.
Bearer credentials do not authorize access-management or approval pages.
App form submissions additionally require an existing, non-empty session CSRF
token. Missing sessions, empty tokens and guessed fallback values are rejected.

Destructive changes and every final invoice creation wait for an immutable,
operation-bound request to be approved in the app. Requests expire after five
minutes, cannot be replayed, and fail or require new review when data changes.
There is no MCP approval tool. Revocation and disabling access invalidate pending
requests; disabling also permanently removes all grants. Restarting the app
clears pending requests, but leaves configured connections enabled.

This boundary applies only to MCP access. The ordinary local app is not an
authenticated service. Software with general browser control or filesystem access
can act outside this boundary, including clicking approval controls. No OS-level
human-presence check, audit log or undo is provided. Do not expose the app publicly.

The app keeps token hashes in `agent_access.json` beside its local configuration
and writes its loopback address to `mcp-endpoint.json`; these files use mode 0600
on POSIX systems. The agent's own MCP configuration contains the actual bearer
token and must be protected as a password. Its provider may receive the invoice,
customer and banking data returned by tools. Opt-in makes this explicit; local
invoice rendering and validation do not make a remote agent's processing local.
See [docs/mcp.md](docs/mcp.md) for setup and limitations.
