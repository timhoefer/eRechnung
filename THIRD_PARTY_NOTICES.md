# Third-Party Notices

eRechnung is licensed under the Apache License 2.0 (see `LICENSE`).
It uses the following third-party software and data artefacts, each under its
own license. The license of each component continues to apply to that
component; nothing here relicenses them.

## Python dependencies

| Component | License | Copyright / Project |
|---|---|---|
| Flask | BSD-3-Clause | © Pallets — https://palletsprojects.com/p/flask/ |
| Werkzeug | BSD-3-Clause | © Pallets — https://palletsprojects.com/p/werkzeug/ |
| Jinja2 | BSD-3-Clause | © Pallets — https://palletsprojects.com/p/jinja/ |
| WeasyPrint | BSD-3-Clause | © Kozea / CourtBouillon — https://weasyprint.org |
| pydyf | BSD-3-Clause | © CourtBouillon — https://github.com/CourtBouillon/pydyf |
| tinycss2 | BSD-3-Clause | © Kozea / CourtBouillon — https://github.com/Kozea/tinycss2 |
| cssselect2 | BSD-3-Clause | © Kozea / CourtBouillon — https://github.com/Kozea/cssselect2 |
| Pillow | MIT-CMU (HPND/PIL) | © Jeffrey A. Clark and contributors — https://python-pillow.github.io |
| fonttools | MIT | © Just van Rossum, Cosimo Lupo and contributors — https://github.com/fonttools/fonttools |
| lxml | BSD-3-Clause | © lxml contributors — https://lxml.de |
| pypdf | BSD-3-Clause | © Mathieu Fenniak and contributors — https://github.com/py-pdf/pypdf |
| drafthorse | Apache-2.0 | © Raphael Michel and contributors — https://github.com/pretix/python-drafthorse |
| SaxonC-HE (`saxonche`) | MPL-2.0 | © Saxonica Limited — https://www.saxonica.com |

Notes:
- **SaxonC-HE** is the Home Edition under the Mozilla Public License 2.0. MPL is
  a file-level copyleft: it covers Saxon's own files only, not this application's
  code. If you modify Saxon's files, those modifications must stay under MPL-2.0.

## Bundled data artefacts

| File | License | Source / Copyright |
|---|---|---|
| `schematron/EN16931-CII-validation.xslt` | **EUPL-1.2** | ConnectingEurope/eInvoicing-EN16931 — © European Union |
| `schematron/XRechnung-CII-validation.xsl` | Apache-2.0 | itplr-kosit/validator-configuration-xrechnung — © KoSIT |
| Factur-X EN16931 XSD (loaded from the `drafthorse` package) | per FNFE-MPE Factur-X specification | © FNFE-MPE |
| `static/fonts/IBMPlexSans-*.woff2`, `static/fonts/IBMPlexMono-*.woff2` | **SIL Open Font License 1.1** | © IBM Corp., Reserved Font Name "IBM Plex" |

Notes:
- **EN16931 XSLT (EUPL-1.2):** the EUPL copyleft applies to this file and its
  derivative works only. It is bundled here unmodified; this application merely
  executes it at runtime and is not a derivative of it. If you modify the XSLT,
  your modifications fall under the EUPL-1.2.
- **IBM Plex (OFL-1.1):** the fonts may be bundled and used (including
  commercially) but may not be sold on their own; the Reserved Font Name
  "IBM Plex" may not be used for modified versions. The full OFL text must
  accompany the font files.
