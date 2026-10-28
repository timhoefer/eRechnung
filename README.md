# E-Rechnung (ZUGFeRD & XRechnung)

Eine lokale Web-App zur einfachen Erstellung von E-Rechnungen für Freiberufler. Rechnungsexport als PDF/A-3 mit eingebettetem XML (**ZUGFeRD / Factur-X**) oder als XML mit PDF als Sichtexemplar (**XRechnung 3.0** nach EN 16931). Läuft komplett lokal, keine Daten verlassen den Rechner. Optional als macOS-Doppelklick-App.

> **Status:** Persönliches Projekt, bereitgestellt **„wie besehen" (as is)**, ohne aktive Wartung oder Support. Der E-Rechnungs-Standard ändert sich jährlich. Bitte jede erzeugte Rechnung selbst prüfen (siehe Haftungsausschluss unten). Forks willkommen.

## Download (macOS)

Eine fertige, **signierte und notarisierte** macOS-App gibt es unter [Releases](../../releases) — herunterladen, entpacken, in den Programme-Ordner ziehen, fertig. Sie öffnet sich ohne Gatekeeper-Warnung (Apple Silicon). Wer lieber aus dem Quellcode startet oder selbst baut: siehe unten.

## Voraussetzungen

- **Python 3.12+**
- **Pango** — native Bibliothek, die WeasyPrint für die PDF-Erzeugung braucht (auch für die Web-App, nicht nur für den App-Build). Auf macOS: `brew install pango`.

## Start

Zwei Wege:

- **Im Browser** (Terminal): `./run.sh` legt beim ersten Mal automatisch ein virtuelles Environment an, installiert die Abhängigkeiten und startet die App. Dann im Browser öffnen: http://127.0.0.1:5000
- **Als macOS-Doppelklick-App** (ohne Terminal/Browser): siehe [Als macOS-App bauen](#als-macos-app-bauen-optional) — eigenes Fenster, self-contained.

Beim ersten Start einmal die **Stammdaten** (Absender) ausfüllen und speichern — sie werden lokal in `seller.json` abgelegt und bei jeder Rechnung wiederverwendet.

## Mehrere Rechnungsaussteller

Über **Weitere Stammdaten anlegen** unten neben **Stammdaten speichern** kannst du weitere Profile
anlegen, etwa für deine freiberufliche Tätigkeit und eine Gesellschaft. Jedes Profil
hat eigene Stammdaten, Steuerangaben, Logo, Bankverbindungen, Rechnungsnummern und
ein eigenes Archiv. Der Profilname dient nur zur Unterscheidung in der App; auf der
Rechnung steht der in den Stammdaten hinterlegte Name. Die Kundenliste und deren
gespeicherte Positionen werden gemeinsam genutzt.

Solange nur ein Profil vorhanden ist, bleibt die Oberfläche wie gewohnt. Ab dem
zweiten Profil zeigt eine Auswahlleiste oben den aktiven Rechnungsaussteller.
Sie bleibt beim Scrollen sichtbar; über die Auswahl kannst du direkt wechseln.

Die vorhandenen Stammdaten und Rechnungen bilden automatisch das erste Profil;
bestehende Dateien werden dafür weder verschoben noch umgeschrieben. Weitere
Profile liegen unter `issuers/<Profil-ID>/seller.json` und
`issuers/<Profil-ID>/output/` im gemeinsamen Datenordner. Ein Datenordnerwechsel
nimmt alle Profile mit; abweichende Kopien desselben Profils im Ziel stoppen den
Umzug. Sichere immer den vollständigen Datenordner.

Die automatische Nummernfolge `JJJJ-NNN` läuft pro Aussteller unabhängig. Bei einem
neuen Profil beginnt der Vorschlag mit `JJJJ-001`; falls bereits Rechnungen
existieren, trage beim ersten Erstellen die passende nächste Nummer ein. Die App
setzt diese Folge anschließend fort. Abweichende Nummernformate bleiben manuell
eingebbar. Archiv, CSV-Export, Vorlagen und Bezüge für Korrekturen beziehen sich
jeweils auf das ausgewählte Profil. Gespeicherte Originalrechnungen bleiben bei
späteren Änderungen an den Stammdaten unverändert.

Ein Profilwechsel öffnet ein neues Rechnungsformular. Bei bereits eingetragenem
Kunden oder Positionen fragt die App vor dem Verwerfen nach. Jedes Fenster behält
seinen eigenen Aussteller; beim Start über die normale App-Adresse wird das erste
Profil geöffnet. Profile lassen sich über ihren Profilnamen umbenennen; eine
Löschfunktion für komplette Profile ist noch nicht vorgesehen.

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

So gebaut ist die App **unsigniert** — auf einem fremden Mac blockt Gatekeeper sie dann beim ersten Start (danach unter **Systemeinstellungen › Datenschutz & Sicherheit** auf **„Trotzdem öffnen"**; der frühere Rechtsklick-›-Öffnen-Weg ist ab macOS 15 Sequoia weg). Für den fertigen, ohne Warnung lauffähigen Download siehe [Releases](../../releases).

Für einen **signierten + notarisierten** Build (wie in den Releases) unterstützt das Skript Code-Signing und Notarisierung über die Umgebungsvariablen `SIGN_IDENTITY` und `NOTARY_PROFILE` (Apple Developer Program nötig; Details im Kopf von `build_macos.sh`). Der klassische Start über `run.sh` / `start.command` bleibt unverändert nutzbar.

## Lizenz & Haftungsausschluss

Dieser Code steht unter der **Apache License 2.0** – siehe [`LICENSE`](LICENSE). Mitgelieferte Drittkomponenten (u. a. die Schematron-Artefakte und die IBM-Plex-Schriften) stehen unter eigenen Lizenzen; die vollständige Auflistung mit Attribution findest du in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

**Ohne Gewähr.** Dieses Tool wird bereitgestellt „wie besehen", ohne jede Gewährleistung. Es wird keine Haftung für die Richtigkeit, Vollständigkeit oder rechtliche bzw. steuerliche Konformität der erzeugten Rechnungen übernommen. Bitte prüfe jede Rechnung selbst (bei Bedarf mit deinem Steuerberater). Die Nutzung erfolgt auf eigenes Risiko.

[KoSIT-Validator]: https://github.com/itplr-kosit/validator


## Automatische Prüfungen und Releases

### Hinweise auf neue Funktionen

`whats_new.py` enthält die kuratierten Highlights für „Neu in eRechnung“ (Deutsch
und Englisch). Bei neuen Hinweisen die `id`, die zugehörige `version` und die kurzen
Texte gemeinsam aktualisieren. **Nur bei ausgewählten größeren Feature-Releases**
`auto_open: True` setzen. Bei kleineren Neuerungen und Fehlerkorrekturen bleibt es
`False`; ohne dieses Feld öffnet sich der Dialog ebenfalls nur manuell. Eine neue
ID oder Versionsnummer allein löst keine automatische Anzeige aus. Die Hinweise
zu 1.1.4 sind zunächst nur manuell erreichbar. `ANNOUNCEMENT = None` deaktiviert
den Dialog und den Menüeintrag vollständig.

Die App speichert gelesene IDs in ihrer lokalen `config.json`, unabhängig vom
Browser-Speicher und vom gewählten Rechnungsordner. Die erste Ordnerauswahl hat
Vorrang; über „Neuigkeiten“ in den Einstellungen bleiben die Hinweise erreichbar.

### Prüfungen

Bei Pull Requests und Pushes auf `main` laufen Python-Tests einschließlich echter
PDF-Erzeugung, XSD- und Schematron-Prüfung, JavaScript-Tests, Ruff und mypy. Die
Integrationstests prüfen ZUGFeRD und XRechnung jeweils auf Deutsch und Englisch.
Fehlende PDF-/SaxonC-Abhängigkeiten sind in CI ein Fehler.

Ein zusätzlicher Apple-Silicon-Job auf `macos-15` baut die App. Der Build prüft die
Versionsnummer und führt den Selbsttest sowohl im Bundle als auch nach dem
Entpacken des ZIP-Archivs aus. Diese CI-Builds benötigen keine Apple-Zugangsdaten
und gelten nicht als signierte Veröffentlichungen. Der Selbsttest verwendet
bereits beim Laden der App einen temporären Datenordner.

Für lokale Prüfungen:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt pypdf==6.12.2
ERECHNUNG_REQUIRE_INTEGRATION=1 .venv/bin/python -m pytest -q
./build_macos.sh
```

Bei einem Build mit `NOTARY_PROFILE` prüft das Skript den Apple-Zugriff vor dem
Aufräumen und Bauen. Nach Signierung und Notarisierung werden zusätzlich die
Developer-ID-Signatur, das angeheftete Notarisierungsticket und Gatekeeper geprüft,
auch am entpackten Download-ZIP. Eine fehlende Notarisierung ist ein Fehler.

Der manuell startbare GitHub-Ablauf **Release verification** prüft ein bereits
hochgeladenes Release-Archiv (auch aus einem Entwurf): Tag, Quellcode-Version,
Änderungsprotokoll, App-Version, Signatur, Notarisierung und Selbsttest. Dazu unter
**Actions → Release verification → Run workflow** den Tag angeben. Mit der optionalen
Auswahl **Nach erfolgreicher Prüfung veröffentlichen** wird der Entwurf erst nach
allen Prüfungen veröffentlicht; vor der Veröffentlichung wird die Prüfsumme des
hochgeladenen Archivs erneut verglichen. Ohne diese Auswahl wird nur geprüft.
Apple-Zertifikate oder Apple-Passwörter müssen dafür nicht in GitHub gespeichert werden.
