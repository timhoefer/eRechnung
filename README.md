# E-Rechnung (ZUGFeRD & XRechnung)

Eine lokale Web-App zur einfachen Erstellung von E-Rechnungen für Freiberufler. Rechnungsexport als PDF/A-3 mit eingebettetem XML (**ZUGFeRD / Factur-X**) oder als XML mit PDF als Sichtexemplar (**XRechnung 3.0** nach EN 16931). Läuft komplett lokal, keine Daten verlassen den Rechner. Optional als macOS-Doppelklick-App.

> **Status:** Persönliches Projekt, bereitgestellt **„wie besehen" (as is)**, ohne aktive Wartung oder Support. Der E-Rechnungs-Standard ändert sich jährlich. Bitte jede erzeugte Rechnung selbst prüfen (siehe Haftungsausschluss unten). Forks willkommen.

## Voraussetzungen

- **Python 3.12+**
- **Pango** — native Bibliothek, die WeasyPrint für die PDF-Erzeugung braucht (auch für die Web-App, nicht nur für den App-Build). Auf macOS: `brew install pango`.

## Start

Zwei Wege:

- **Im Browser** (Terminal): `./run.sh` legt beim ersten Mal automatisch ein virtuelles Environment an, installiert die Abhängigkeiten und startet die App. Dann im Browser öffnen: http://127.0.0.1:5000
- **Als macOS-Doppelklick-App** (ohne Terminal/Browser): siehe [Als macOS-App bauen](#als-macos-app-bauen-optional) — eigenes Fenster, self-contained.

Beim ersten Start einmal die **Stammdaten** (Absender) ausfüllen und speichern — sie werden lokal in `seller.json` abgelegt und bei jeder Rechnung wiederverwendet.

## Steuerliche Behandlungen

| Auswahl | EN-16931-Code | Verwendung |
|---|---|---|
| Inland 19 % / 7 % | `S` | Normale Inlandsrechnung |
| Reverse Charge – EU B2B | `AE` | Leistung an EU-Unternehmen (USt-IdNr des Kunden nötig) |
| Reverse Charge – Drittland | `AE` | Dienstleistung an Nicht-EU-Unternehmer (§ 3a Abs. 2 UStG), 0 % mit Begründung |
| Nicht steuerbar – Drittland (ohne USt-IdNr) | `G` | Drittland-Kunde ohne USt-IdNr, 0 % mit Begründung |
| Kleinunternehmer § 19 | `E` | Keine USt nach § 19 UStG |

Bei den 0-%-Varianten wird der gesetzlich erforderliche **Begründungstext** automatisch in PDF und XML eingetragen.

**Eine Rechnung = ein Steuersatz.** Gemischte Sätze auf einer Rechnung (z. B. 19 % Designleistung + 7 % Einräumung von Nutzungsrechten, § 12 Abs. 2 Nr. 7c UStG) werden bewusst nicht unterstützt — stelle dafür einfach **zwei separate Rechnungen**, jede für sich mit einem Satz. Das ist steuerlich einwandfrei und hält das Tool einfach.

## Sprache (Deutsch / Englisch)

- **Oberfläche:** Umschalter **DE/EN** oben rechts (wird per Cookie gemerkt).
- **Rechnungssprache:** pro Rechnung im Dropdown wählbar — so kannst du bei deutscher Oberfläche trotzdem eine **englische Rechnung** an ausländische Kunden senden. Beschriftungen, Pflichthinweise und der steuerliche Begründungstext erscheinen dann in der gewählten Sprache (in PDF *und* XML).

## Was erzeugt wird

Das Format wählst du pro Rechnung oben im Kopf:

- **ZUGFeRD / Factur-X** (Standard): ein **PDF/A-3** mit lesbarem Rechnungslayout und eingebettetem **`factur-x.xml`** (Profil EN 16931 / „COMFORT") — ein Hybrid-Dokument, das zugleich Sicht- und Datenbeleg ist.
- **XRechnung 3.0**: eine eigenständige, einreichbare **`.xml`** (XSD- und BR-DE-valide) plus ein **PDF als Sichtexemplar**. Hier ist die XML die eigentliche Rechnung; das PDF dient nur der menschlichen Ansicht.

Beide werden gegen die offizielle XSD validiert; das Ergebnis lässt sich zusätzlich mit Validatoren wie dem [KoSIT-Validator] oder Mustang prüfen.

## Hinweise

- Die E-Rechnungs-**pflicht** (ab 2025 Empfang, gestaffelt ab 2027/2028 Versand) gilt nur für **inländische B2B-Umsätze**. Rechnungen an Nicht-EU-Kunden sind freiwillig, lassen sich hier aber im selben Format erzeugen.
- Dies ist ein Werkzeug, keine Steuerberatung. Die korrekte steuerliche Einordnung im Einzelfall liegt bei dir bzw. deinem Steuerberater.
- **Aufbewahrung / GoBD:** Dies ist ein **Rechnungs-Generator, kein revisionssicheres Archiv.** Der `output/`-Ordner ist eine Arbeitskopie — Dateien sind dort änder- und löschbar, es gibt kein Änderungsprotokoll. Bewahre deine Rechnungen **revisionssicher** dort auf, wo deine Buchhaltung liegt (z. B. DATEV/Steuerberater oder ein GoBD-konformes System). Aufbewahrungsfrist: **10 Jahre** (§ 14b UStG, § 147 AO).

## Als macOS-App bauen (optional)

Für eine Doppelklick-App ohne Terminal/Browser (eigenes Fenster via pywebview) gibt es einen PyInstaller-Build. Voraussetzung ist Homebrew-Pango (liefert die nativen Bibliotheken, die ins Bundle eingebettet werden):

```bash
brew install pango
.venv/bin/pip install -r requirements-build.txt
./build_macos.sh        # -> dist/eRechnung.app
```

Die App ist self-contained (Pango-Stack + SaxonC sind eingebettet) und legt ihre Daten unter `~/Library/Application Support/eRechnung` ab. Ein headless-Selbsttest prüft die nativen Bibliotheken:

```bash
./dist/eRechnung.app/Contents/MacOS/eRechnung --selftest
```

Die App ist **unsigniert**. Auf einem fremden Mac blockt Gatekeeper sie beim ersten Start; danach unter **Systemeinstellungen › Datenschutz & Sicherheit** auf **„Trotzdem öffnen"** klicken (auf macOS 15 Sequoia und neuer funktioniert der frühere Rechtsklick-›-Öffnen-Weg nicht mehr). Alternativ das Quarantäne-Flag entfernen: `xattr -dr com.apple.quarantine eRechnung.app`.

Für eine Weitergabe **ohne** diese Warnung sind Code-Signing und Notarisierung (Apple Developer Program) nötig — der Build unterstützt das bereits über die Umgebungsvariablen `SIGN_IDENTITY` und `NOTARY_PROFILE` (siehe Kopf von `build_macos.sh`). Der klassische Start über `run.sh` / `start.command` bleibt unverändert nutzbar.

## Lizenz & Haftungsausschluss

Dieser Code steht unter der **Apache License 2.0** – siehe [`LICENSE`](LICENSE). Mitgelieferte Drittkomponenten (u. a. die Schematron-Artefakte und die IBM-Plex-Schriften) stehen unter eigenen Lizenzen; die vollständige Auflistung mit Attribution findest du in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

**Ohne Gewähr.** Dieses Tool wird bereitgestellt „wie besehen", ohne jede Gewährleistung. Es wird keine Haftung für die Richtigkeit, Vollständigkeit oder rechtliche bzw. steuerliche Konformität der erzeugten Rechnungen übernommen. Bitte prüfe jede Rechnung selbst (bei Bedarf mit deinem Steuerberater). Die Nutzung erfolgt auf eigenes Risiko.

[KoSIT-Validator]: https://github.com/itplr-kosit/validator
