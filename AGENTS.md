# Testing invoice workflows

- Start manual/browser tests with `ERECHNUNG_TEST_MODE=1` (default port 5001).
- Never create test invoices through an installed production app or its data folder.
  Use fictional issuer/customer data in the temporary test directory.
- The test mode owns a fresh, fixed data directory and invoice-number sequence for
  each start; do not bypass its data-directory restriction during manual tests.
- Run automated checks with pytest; `tests/conftest.py` isolates app startup before
  imports. Fixtures may exercise folder migrations using their own temporary paths.
