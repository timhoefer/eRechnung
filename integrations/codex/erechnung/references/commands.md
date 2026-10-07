# Local commands

Run `python3 <skill-folder>/scripts/erechnung.py …` with the following arguments.
The launcher supplies the configured source directory; override it with
`--data-dir /absolute/source/path` **before** the command. Quote paths and customer
names; use argument arrays when invoking from code. Only `archive` modifies app data.

| Command | Purpose |
| --- | --- |
| `schema` | Fields, formats, units and supported tax treatments |
| `next-number` | Suggest a standard number; flag unclear/custom/year-change sequences for a user question |
| `customers --query "Beispiel"` | Find customers by part of their name |
| `templates --customer "Beispiel GmbH"` | Matching sidecars, newest issue date first |
| `draft --customer "Beispiel GmbH" --template Rechnung_DEMO-ALT.json --out /work/draft.json` | Draft from template/current source; template is optional |
| `check --draft /work/draft.json` | Validate input, XML structure and business rules |
| `preview --draft /work/draft.json --out /work/preview.pdf` | Labelled draft PDF, without embedded XML |
| `export --draft /work/draft.json --out-dir /work/exports` | Validated files in one separate invoice subfolder; identical retries reuse it |
| `archive --draft /work/draft.json` | Validate and finalize into the selected app archive; updates the last invoice number |

Draft and preview commands refuse to overwrite files. Use a fresh preview filename
after changing a draft. Resolve export conflicts without overwriting or deleting
invoices. Separate exports reject numbers already in the source archive, but do
not reserve them against other app sessions. Use `archive` for final invoices that
should appear in the app. It preserves the issuer/customer snapshot, publishes PDF
and JSON (plus XML for XRechnung) together, and updates only the issuer's last
invoice number; it does not overwrite saved customers or bank details.

`next-number` returns `number`, `suggestion`, `last_invoice_number`,
`requires_clarification`, `reasons`, `duplicate_numbers` (number to filenames) and
`reserved: false`. Duplicate numbers make both `number` and `suggestion` null; ask
for the last actually issued invoice instead of using the highest archived number.
With an unclear scheme
or year transition it leaves `number: null`. Ask the user instead of copying the
suggestion into the invoice automatically. Explicit user choices take precedence.

`archive` uses the same local process lock as the updated app. Changed contents
with an existing number or colliding filename are rejected. Identical retries
return `reused: true` and verify the original files. Interrupted transactions are
completed on retry or the next app write; keep the same draft and data folder.
Older app builds do not use this shared lock: update the app before using both
writers concurrently. Dropbox/iCloud must have the data locally available, and
writing simultaneously from separate computers is not coordinated by this lock.

## Draft data

`draft` returns a JSON path. Keep `schema_version: 1` and the `seller` snapshot.
`buyer` uses app fields such as name, address_line, postcode, city, country, email,
vat_id and reference. Changes apply to this draft only.

Example invoice/items (illustrative values, not user defaults):

```json
{
  "invoice": {
    "number": "DEMO-2026-002",
    "issue_date": "2026-10-07",
    "due_date": "2026-10-21",
    "service_start": "2026-10-01",
    "service_end": "2026-10-03",
    "currency": "EUR",
    "language": "de",
    "profile": "en16931",
    "doc_type": "380",
    "tax_treatment": "de_19"
  },
  "items": [{"description": "Gestaltung", "quantity": "3", "unit": "DAY", "unit_price": "800"}]
}
```

Use decimal **strings** with a dot, no thousands separators (`"800.50"`). Dates are
`YYYY-MM-DD`; periods need both start/end. `DAY` means days, `HUR` hours, `C62`
pieces and `LS` lump sum (quantity `"1"`). Language is `de` or `en`. Profile is
`en16931` (ZUGFeRD PDF with embedded XML) or `xrechnung` (XML plus visual PDF).
Only ordinary invoices (`380`) are supported in this prototype.

Optional discounts use `discount`, `discount_type` (`abs` or `pct`), and
`discount_reason`; line discounts use the `item_` prefix. `prepaid` and
`prepaid_ref` describe a received advance payment. `bank_account` selects a saved
account by its identifier. Payment terms derive from issue/due dates. See `schema`
for all supported fields; unknown keys are errors.

`ok: false` or exit code 2 means failure; do not treat an old file as its result.
