# E-Rechnung (ZUGFeRD)

Lokale Web-App zur Erstellung von E-Rechnungen im **ZUGFeRD**-Format (PDF/A-3 mit
eingebettetem EN-16931-XML). Läuft komplett lokal — keine Cloud, keine Daten verlassen
den Rechner.

## Start

```bash
./run.sh
```

Dann im Browser öffnen: http://127.0.0.1:5000

Beim ersten Start einmal die **Stammdaten** (Absender) ausfüllen und speichern — sie
werden lokal in `seller.json` abgelegt und bei jeder Rechnung wiederverwendet.

## Steuerliche Behandlungen

| Auswahl | EN-16931-Code | Verwendung |
|---|---|---|
| Inland 19 % / 7 % | `S` | Normale Inlandsrechnung |
| **Nicht steuerbar – Drittland** | `O` | Dienstleistung an Nicht-EU-Kunden (§ 3a Abs. 2 UStG), 0 % mit Begründung |
| Reverse Charge – EU B2B | `AE` | Leistung an EU-Unternehmen |
| Kleinunternehmer § 19 | `E` | Keine USt nach § 19 UStG |

Bei den 0-%-Varianten wird der gesetzlich erforderliche **Begründungstext** automatisch
in PDF und XML eingetragen.

## Sprache (Deutsch / Englisch)

- **Oberfläche:** Umschalter **DE/EN** oben rechts (wird per Cookie gemerkt).
- **Rechnungssprache:** pro Rechnung im Dropdown wählbar — so kannst du bei deutscher
  Oberfläche trotzdem eine **englische Rechnung** an ausländische Kunden senden. Beschriftungen,
  Pflichthinweise und der steuerliche Begründungstext erscheinen dann in der gewählten Sprache
  (in PDF *und* XML).

## Was erzeugt wird

- **PDF/A-3** mit lesbarem Rechnungslayout
- eingebettetes **`factur-x.xml`** (Profil EN 16931 / „COMFORT"), validiert gegen die
  offizielle Factur-X-XSD

Das Ergebnis lässt sich mit Validatoren wie dem [KoSIT-Validator] oder Mustang prüfen.

## Hinweise

- Die E-Rechnungs-**pflicht** (ab 2025 Empfang, gestaffelt ab 2027/2028 Versand) gilt nur
  für **inländische B2B-Umsätze**. Rechnungen an Nicht-EU-Kunden sind freiwillig, lassen
  sich hier aber im selben Format erzeugen.
- Dies ist ein Werkzeug, keine Steuerberatung. Die korrekte steuerliche Einordnung im
  Einzelfall liegt bei dir bzw. deinem Steuerberater.

[KoSIT-Validator]: https://github.com/itplr-kosit/validator
