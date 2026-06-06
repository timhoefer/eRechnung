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

## Als macOS-App bauen (optional)

Für eine Doppelklick-App ohne Terminal/Browser (eigenes Fenster via pywebview)
gibt es einen PyInstaller-Build. Voraussetzung ist Homebrew-Pango (liefert die
nativen Bibliotheken, die ins Bundle eingebettet werden):

```bash
brew install pango
.venv/bin/pip install -r requirements-build.txt
./build_macos.sh        # -> dist/eRechnung.app
```

Die App ist self-contained (Pango-Stack + SaxonC sind eingebettet) und legt ihre
Daten unter `~/Library/Application Support/eRechnung` ab. Ein headless-Selbsttest
prüft die nativen Bibliotheken:

```bash
./dist/eRechnung.app/Contents/MacOS/eRechnung --selftest
```

Die App ist **unsigniert** – beim ersten Öffnen auf einem fremden Mac per
Rechtsklick › „Öffnen". Für eine Weitergabe ohne Gatekeeper-Warnung sind
Code-Signing und Notarisierung (Apple Developer Program) nötig. Der klassische
Start über `run.sh` / `start.command` bleibt unverändert nutzbar.

## Lizenz & Haftungsausschluss

Dieser Code steht unter der **Apache License 2.0** – siehe [`LICENSE`](LICENSE).
Mitgelieferte Drittkomponenten (u. a. die Schematron-Artefakte und die
IBM-Plex-Schriften) stehen unter eigenen Lizenzen; die vollständige Auflistung
mit Attribution findest du in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

**Ohne Gewähr.** Dieses Tool wird bereitgestellt „wie besehen", ohne jede
Gewährleistung. Es wird keine Haftung für die Richtigkeit, Vollständigkeit oder
rechtliche bzw. steuerliche Konformität der erzeugten Rechnungen übernommen.
Bitte prüfe jede Rechnung selbst (bei Bedarf mit deinem Steuerberater). Die
Nutzung erfolgt auf eigenes Risiko.

[KoSIT-Validator]: https://github.com/itplr-kosit/validator
