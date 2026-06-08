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

All data stays on your machine, in your data folder (by default next to the app,
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
