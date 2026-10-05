"""Kuratierte Neuerungen. ID nur bei neuen Feature-Hinweisen ändern, nicht pro Build.

Für ein Feature-Release ID, Version und Texte gemeinsam aktualisieren. Reine
Bugfix-Releases behalten denselben Eintrag; ANNOUNCEMENT = None deaktiviert ihn.
"""
from typing import Any

ANNOUNCEMENT: dict[str, Any] | None = {
    "id": "invoice-layout-1.1.4",
    "version": "1.1.4",
    "items": [
        {
            "icon": "invoice",
            "title": {"de": "Klarere Rechnungen", "en": "Clearer invoices"},
            "text": {
                "de": "Mehr Raum für Leistungen, ruhigere Tabellen und ein deutlich hervorgehobener Rechnungsbetrag.",
                "en": "More room for your services, cleaner tables and a clearly highlighted total due.",
            },
        },
        {
            "icon": "globe",
            "title": {"de": "Für internationale Kunden", "en": "For international customers"},
            "text": {
                "de": "Bei Kunden im Ausland erscheint dein Land automatisch in der Absenderadresse.",
                "en": "When your customer is abroad, your country is automatically included in the sender address.",
            },
        },
        {
            "icon": "archive",
            "title": {"de": "Originale im Archiv", "en": "Originals in your archive"},
            "text": {
                "de": "Die Archivvorschau zeigt die gespeicherte Rechnung – mit ihrem ursprünglichen Layout.",
                "en": "The archive preview shows your saved invoice, with its original layout intact.",
            },
        },
    ],
}
