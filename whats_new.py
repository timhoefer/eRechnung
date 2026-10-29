"""Kuratierte Neuerungen. ID nur bei neuen Hinweisen ändern, nicht pro Build.

ID, Version und Texte gemeinsam aktualisieren. Nur für ausgewählte größere
Feature-Releases auto_open ausdrücklich auf True setzen; sonst bleiben Hinweise
manuell erreichbar. ANNOUNCEMENT = None deaktiviert auch den Menüeintrag.
"""
from typing import Any

ANNOUNCEMENT: dict[str, Any] | None = {
    "id": "issuer-profiles-1.2.0",
    "version": "1.2.0",
    "auto_open": True,
    "items": [
        {
            "icon": "invoice",
            "title": {"de": "Mehrere Rechnungsaussteller", "en": "Multiple invoice issuers"},
            "text": {
                "de": "Lege weitere Stammdaten an, etwa für deine freiberufliche Tätigkeit und deine Firma. Jedes Profil hat eigene Bankdaten, Rechnungsnummern und ein eigenes Archiv.",
                "en": "Add issuer profiles for your freelance work and your company. Each profile has its own bank details, invoice numbering and archive.",
            },
        },
        {
            "icon": "globe",
            "title": {"de": "Einfach wechseln", "en": "Switch with ease"},
            "text": {
                "de": "Bei mehreren Profilen wechselst du direkt in der Stammdaten-Kopfzeile und legst einen Standard für den App-Start fest. Kunden bleiben gemeinsam nutzbar.",
                "en": "With multiple profiles, switch directly in the issuer header and choose a default for app startup. Your customer list stays shared.",
            },
        },
        {
            "icon": "archive",
            "title": {"de": "Archive bleiben erhalten", "en": "Keep your archives"},
            "text": {
                "de": "Entfernte Profile bleiben mit ihren Belegen im Archiv. Dort kannst du Stornos und Korrekturen erstellen oder das Profil mit seiner bisherigen Nummernfolge reaktivieren.",
                "en": "Removed profiles and their invoices remain in the archive. Create cancellations and corrections there, or reactivate a profile with its existing invoice sequence.",
            },
        },
    ],
}
