"""Kuratierte Neuerungen. ID nur bei neuen Hinweisen ändern, nicht pro Build.

ID, Version und Texte gemeinsam aktualisieren. Nur für ausgewählte größere
Feature-Releases auto_open ausdrücklich auf True setzen; sonst bleiben Hinweise
manuell erreichbar. ANNOUNCEMENT = None deaktiviert auch den Menüeintrag.
"""
from typing import Any

ANNOUNCEMENT: dict[str, Any] | None = {
    "id": "archive-and-csv-1.3.0",
    "version": "1.3.0",
    "auto_open": True,
    "items": [
        {
            "icon": "archive",
            "title": {"de": "Dein Archiv im Überblick", "en": "Your archive at a glance"},
            "text": {
                "de": "Filtere Rechnungen nach Jahr und Aussteller oder zeige alle Aussteller gemeinsam an. Auch reine XML-Rechnungen findest du jetzt im Archiv.",
                "en": "Filter invoices by year and issuer, or view all issuers together. XML-only invoices now appear in the archive too.",
            },
        },
        {
            "icon": "invoice",
            "title": {"de": "CSV-Export nach deiner Auswahl", "en": "Export your selection to CSV"},
            "text": {
                "de": "Wähle einzelne Rechnungen, alle angezeigten Belege oder ganze Quartale aus. Vor dem Export gleicht eRechnung die Werte mit der archivierten XML ab.",
                "en": "Select individual invoices, all displayed invoices or entire quarters. Before exporting, eRechnung checks the values against the archived XML.",
            },
        },
        {
            "icon": "invoice",
            "title": {"de": "XML-Prüfstatus direkt sichtbar", "en": "See the XML validation status"},
            "text": {
                "de": "Der XML-Chip zeigt die technische Prüfung der unveränderten Rechnungsdaten. Über das Zeilenmenü kannst du jederzeit erneut prüfen. Der Status bewertet nicht die steuerliche Richtigkeit.",
                "en": "The XML badge shows technical validation of unchanged invoice data. Run another check at any time from the row menu. This status does not assess tax correctness.",
            },
        },
    ],
}
