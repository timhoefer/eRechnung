# E-Rechnung (ZUGFeRD & XRechnung)

Eine lokale Web-App zur einfachen Erstellung von E-Rechnungen für Freiberufler. Rechnungsexport als PDF/A-3 mit eingebettetem XML (**ZUGFeRD / Factur-X**) oder als XML mit PDF als Sichtexemplar (**XRechnung 3.0** nach EN 16931). Läuft komplett lokal, keine Daten verlassen den Rechner. Optional als macOS-Doppelklick-App.

> **Status:** Persönliches Projekt, bereitgestellt **„wie besehen" (as is)**, ohne aktive Wartung oder Support. Der E-Rechnungs-Standard ändert sich jährlich. Bitte jede erzeugte Rechnung selbst prüfen (siehe Haftungsausschluss unten). Forks willkommen.

## Download (macOS)

Eine fertige, **signierte und notarisierte** macOS-App gibt es unter [Releases](../../releases) — herunterladen, entpacken, in den Programme-Ordner ziehen, fertig. Sie öffnet sich ohne Gatekeeper-Warnung (Apple Silicon). Wer lieber aus dem Quellcode startet oder selbst baut: siehe unten.

## Robustere Rechnungsablage

PDF-Darstellung, Ausstellerverwaltung und Archivablage liegen in eigenständigen
internen Modulen. Vorschau und Erzeugung der App verwenden dieselbe Darstellung.
Es wird keine externe Agentenschnittstelle aktiviert.

Ein Beleg wird nur nach erfolgreicher XSD- und Schematron-Prüfung archiviert.
Fehlt die Prüfung oder schlägt sie fehl, zeigt die App die Fehler; Belegdateien,
Kundendaten und Rechnungsnummernstand bleiben unverändert.

Die Nummer gehört weiterhin zu einem Aussteller. Eine identische Wiederholung
verwendet die ursprünglichen Dateien. Abweichende Inhalte mit derselben Nummer
werden abgewiesen; vorhandene Altbelege bleiben bestehen. Das Archiv wird nicht
umbenannt oder nachträglich bereinigt.

Vor der Veröffentlichung werden die Dateien vollständig vorbereitet; das PDF wird
zuletzt sichtbar. Ein unterbrochener Schreibvorgang bleibt für die Wiederherstellung
vorgemerkt und wird beim nächsten schreibenden Zugriff abgeschlossen. Konflikte
mit zwischenzeitlich geänderten Dateien werden gemeldet, nicht überschrieben.
Die Sperre koordiniert Prozesse dieser App-Version auf demselben Rechner. Sie
koordiniert keine unterschiedlichen Macs über Dropbox oder andere Cloud-Synchronisation
und macht das Arbeitsarchiv nicht revisionssicher.

## Voraussetzungen

- **Python 3.12+**
- **Pango** — native Bibliothek, die WeasyPrint für die PDF-Erzeugung braucht (auch für die Web-App, nicht nur für den App-Build). Auf macOS: `brew install pango`.

## Start

Zwei Wege:

- **Im Browser** (Terminal): `./run.sh` legt beim ersten Mal automatisch ein virtuelles Environment an, installiert die Abhängigkeiten und startet die App. Dann im Browser öffnen: http://127.0.0.1:5000
- **Als macOS-Doppelklick-App** (ohne Terminal/Browser): siehe [Als macOS-App bauen](#als-macos-app-bauen-optional) — eigenes Fenster, self-contained.

Beim ersten Start einmal die **Stammdaten** (Absender) ausfüllen und speichern — sie werden lokal in `seller.json` abgelegt und bei jeder Rechnung wiederverwendet.

## Mehrere Rechnungsaussteller

Über **Weitere Stammdaten anlegen** unten links in den Stammdaten kannst du weitere Profile
anlegen, etwa für deine freiberufliche Tätigkeit und eine Gesellschaft. Jedes Profil
hat eigene Stammdaten, Steuerangaben, Logo, Bankverbindungen, Rechnungsnummern und
ein eigenes Archiv. Der Profilname dient nur zur Unterscheidung in der App; auf der
Rechnung steht der in den Stammdaten hinterlegte Name. Die Kundenliste und deren
gespeicherte Positionen werden gemeinsam genutzt.

Solange nur ein Profil vorhanden ist, bleibt die Oberfläche wie gewohnt. Ab dem
zweiten Profil zeigt die Kopfzeile der Stammdaten den aktiven Rechnungsaussteller
als Auswahl. Sie bleibt auch bei eingeklappten Stammdaten bedienbar. Beim Wechsel
bleibt eine geöffnete Stammdatenansicht geöffnet.

Die vorhandenen Stammdaten und Rechnungen bilden automatisch das erste Profil;
bestehende Dateien werden dafür weder verschoben noch umgeschrieben. Weitere
Profile liegen unter `issuers/<Profil-ID>/seller.json` und
`issuers/<Profil-ID>/output/` im gemeinsamen Datenordner. Ein Datenordnerwechsel
nimmt alle Profile mit; abweichende Kopien desselben Profils im Ziel stoppen den
Umzug. Sichere immer den vollständigen Datenordner.

Die automatische Nummernfolge `JJJJ-NNN` läuft pro Aussteller unabhängig. Der
Vorschlag folgt der höchsten Nummer des laufenden Jahres aus gespeichertem Zähler
und Archiv dieses Profils. Bei einem neuen Profil beginnt er mit `JJJJ-001`;
existieren Rechnungen außerhalb dieses Archivs, trage beim ersten Erstellen die
passende nächste Nummer ein. Abweichende Nummernformate bleiben manuell
eingebbar. Archiv, CSV-Export, Vorlagen und Bezüge für Korrekturen beziehen sich
jeweils auf das ausgewählte Profil. Gespeicherte Originalrechnungen bleiben bei
späteren Änderungen an den Stammdaten unverändert.

Bei einer **neuen Anschrift oder einem geänderten Namen** die vorhandenen
Stammdaten bearbeiten. Die Identität des Profils und seine Nummernfolge ändern
sich dabei nicht; neue Belege verwenden die aktualisierten Angaben.

Ein Profilwechsel öffnet ein neues Rechnungsformular. Bei bereits eingetragenem
Kunden oder Positionen fragt die App vor dem Verwerfen nach. Jedes Fenster behält
seinen eigenen Aussteller. Bei mehreren aktiven Profilen kannst du unter dem
Profilnamen **Als Standard verwenden** wählen. Dieses Profil wird beim nächsten
App-Start ausgewählt; ein manueller Profilwechsel verändert den Standard nicht.
Die Auswahl liegt in `issuer_preferences.json` im Datenordner und wird beim Umzug
mitgenommen. Ohne Auswahl oder nach dem Löschen des Standards wird das erste
noch aktive Profil geöffnet. Profile lassen sich über ihren Profilnamen umbenennen.

**Löschen** erscheint erst ab zwei aktiven Profilen und steht unten rechts neben
**Stammdaten speichern**. Nach Bestätigung wird das Profil aus der normalen Auswahl
entfernt, etwa nach Stilllegung einer Firma. Seine Stammdaten und Nummernfolge
bleiben für spätere Stornos und Korrekturen erhalten und sind nicht mehr bearbeitbar.
Alte Fenster können das Profil nicht durch automatisches Speichern wiederherstellen.

**Aussteller reaktivieren** macht dasselbe Profil wieder auswählbar, mit seinen
bisherigen Stammdaten, Rechnungen und seiner Nummernfolge. Die Aktion steht im
Archiv und im Dialog **Weitere Stammdaten anlegen** zur Verfügung, auch für
entfernte Profile ohne Belege. Der bisherige Standardaussteller bleibt bestehen.
Fenster aus der Zeit vor dem Löschen müssen ihre Stammdaten neu laden, bevor sie
Änderungen speichern können. Ein bewusst neu angelegtes Profil bleibt unabhängig;
gleiche Namen oder Adressen führen nicht zu einer automatischen Zusammenlegung.

**Das Archiv bleibt erhalten.** In den Einstellungen hat das Archiv eine eigene
Aussteller-Auswahl. Entfernte Profile sind dort als
**Nur Archiv** gekennzeichnet. Ihre Rechnungen lassen sich ansehen, herunterladen,
prüfen und als CSV exportieren. Im Menü einer Rechnung mit vollständig gespeicherten
Formulardaten stehen **Storno erstellen** und **Korrektur erstellen** zur Verfügung.
Der Aussteller und der Originalbezug sind fest hinterlegt; normale Rechnungen und
Vorausrechnungen bleiben gesperrt. Positionsrabatte und die ursprünglichen
Leistungszeiträume werden übernommen; Rechnungsnummer und Ausstellungsdatum sind neu.
Bereits früher entfernte Profile können die Absenderdaten aus der ausgewählten
Originalrechnung übernehmen. PDF, XML und
gespeicherte Rechnungsdaten einschließlich der damaligen Absenderangaben bleiben
unverändert. Ein Wechsel des Archivs lässt den aktuellen Rechnungsentwurf und seinen
Aussteller unangetastet.

**Schutz vor veralteten Stammdaten:** Ein geöffnetes Formular merkt sich den
geladenen Stand. Hat ein anderes Fenster oder eine bereits eingetroffene
Synchronisation die Stammdaten inzwischen geändert, wird das Speichern abgewiesen.
Die App zeigt einen Hinweis und bietet **Aktuelle Stammdaten laden** an; der
Rechnungsentwurf bleibt dabei erhalten. Die Prüfung reserviert keine Rechnungsnummern.
Der Export wartet auf das Speichern und die Konfliktprüfung der Stammdaten.

Paralleles Schreiben auf mehreren Macs mit getrennten synchronisierten Kopien ist
weiterhin nicht abgesichert. Die lokalen Simulationen und der noch ausstehende Test
mit zwei echten Macs sind in [Mehrgeräte-Prüfung](docs/multi-device-validation.md)
beschrieben.

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

## Lokale Agenten-Schnittstelle (Prototyp)

Die Schnittstelle `assistant_cli.py` ist agentenunabhängig: Jeder Agent mit lokalem
Prozesszugriff kann Kunden und Rechnungsvorlagen lesen, JSON-Entwürfe vorbereiten und
PDF-Vorschauen oder validierte ZUGFeRD-/XRechnung-Dateien erzeugen. Sie verwendet
denselben Rechnungskern und dieselbe Vorlage wie die App. Es gibt keine Abhängigkeit
von Codex, einem Modellanbieter oder einem LLM-API-Schlüssel und keinen zusätzlichen
Server. Der separat installierbare Codex-Skill ist ein optionaler Adapter.
Die [Agenten-Schnittstelle](docs/agent-interface.md) beschreibt die direkte Nutzung,
Rückgaben und Grenzen für andere Agenten und Automatisierungen.

`issuers` listet die Aussteller mit stabilen IDs und dem App-Standard auf.
Bei mehreren aktiven Profilen muss für Nummernvorschlag, Vorlagen und neue Entwürfe
`--issuer ID` vor dem Befehl angegeben werden. Der Standard wird bei Unklarheit
vorgeschlagen, aber nicht stillschweigend ausgewählt. Kunden und gespeicherte
Positionen bleiben gemeinsam; Bankdaten, Nummern und Archive gehören zum gewählten
Aussteller. Deaktivierte Profile können über die Schnittstelle keine neuen
Rechnungen ausstellen; Reaktivierung, Stornos und Korrekturen bleiben App-Aktionen.

Ein Entwurf enthält eine feste Aussteller-ID, den Datenordner-Bezug und den
geprüften Stammdatenstand. Ein geänderter Standard leitet ihn nicht um. Nach einer
Adress-/Bankdatenänderung, Reaktivierung oder einem Ordnerwechsel muss ein neuer
Entwurf erstellt und bestätigt werden. Alte Entwürfe im Format 1 werden ebenfalls
neu erstellt. Separate Exporte liegen in Unterordnern pro Aussteller, sodass beide
dieselbe Rechnungsnummer verwenden können.

Vor dem Erzeugen einer PDF oder dem finalen Export fasst der Skill die geplante
Rechnung zusammen und wartet auf eine ausdrückliche Bestätigung. Offene Angaben
fragt er mit passenden Vorschlägen aus dem Gespräch, Kundendaten und früheren
Rechnungen ab; die Herkunft eines Vorschlags wird benannt. Erst nach Bestätigung
erstellt er die vereinbarte Vorschau, den Export oder den Archiveintrag. Der
gewählte Aussteller ist Teil dieser Zusammenfassung. Diese
Gesprächsregel gilt für den Skill; direkte CLI-Aufrufe haben keinen Bestätigungsdialog.

Der Prototyp unterstützt gewöhnliche Rechnungen (`380`) auf macOS/Linux. Kunden,
Vorlagen und Nummernvorschläge werden gelesen; Entwürfe, Vorschauen und separate
Exporte liegen außerhalb des Datenordners. Nur der ausdrückliche Befehl `archive`
finalisiert eine geprüfte Rechnung im App-Archiv und aktualisiert die zuletzt
verwendete Rechnungsnummer. Die Rechnung erscheint nach Aktualisieren des Archivs
mit Vorschau, Vorlagenfunktion und CSV-Export. Beispielrechnungen bleiben Entwürfe.

App und Skill verwenden dafür denselben Speicherweg und eine gemeinsame lokale
Sperre. Identische Wiederholungen geben den bestehenden Beleg zurück; andere
Inhalte mit derselben Nummer oder einem belegten Dateinamen werden abgelehnt.
Die PDF wird erst sichtbar, wenn die zugehörigen Dateien vollständig bereitliegen.
Bei einer Unterbrechung bleibt ein Wiederaufnahmeprotokoll erhalten; derselbe
Auftrag oder der nächste schreibende App-Zugriff schließt die Speicherung ab.
XML-Prüfungen müssen vor der Archivierung erfolgreich sein. Auch die App archiviert
keine Rechnungen mit fehlgeschlagener oder nicht verfügbarer Validierung mehr.

`next-number` berücksichtigt das Archiv, reserviert die vorgeschlagene Nummer aber
noch nicht. Bei unklaren oder eigenen Nummernkreisen sowie einem Jahreswechsel
fordert der Skill eine Klärung an, statt selbst eine Nummer festzulegen. Klare
Vorgaben des Nutzers werden übernommen; Konflikte führen zu einer Rückfrage.
Doppelte Nummern im Altbestand werden als Unklarheit gemeldet. Bei bekannten
Testrechnungen ist die höchste Archivnummer kein verlässlicher Ausgangspunkt;
der Skill fragt nach der letzten tatsächlich ausgestellten Rechnung. Bestehende
Belege werden nicht automatisch als Tests eingeordnet oder umnummeriert. Ein separates `export` registriert ebenfalls keine Nummer im Archiv.
Vor gleichzeitiger Nutzung von App und Skill muss die App auf diesen gemeinsamen
Speicherweg aktualisiert sein; auch die veröffentlichte Version 1.2.0 kennt diese
Sperre noch nicht. Für parallele Tests die App aus diesem PR verwenden. Sie gilt nur
auf demselben Rechner, nicht über Dropbox/iCloud zwischen verschiedenen Geräten.
Die Dateien im Datenordner müssen lokal verfügbar sein.

Zum Ausprobieren mit ausschließlich fiktiven Daten (vorher Python-Abhängigkeiten
und Pango wie oben installieren):

```bash
.venv/bin/python scripts/create_assistant_demo.py /tmp/erechnung-demo-daten
.venv/bin/python assistant_cli.py --data-dir /tmp/erechnung-demo-daten issuers
.venv/bin/python scripts/install_assistant_skill.py --data-dir /tmp/erechnung-demo-daten
```

Mit `--multiple-issuers` beim Erstellen der Beispieldaten werden zwei fiktive
Aussteller angelegt. Die Skill-Installation ist für direkte CLI-Aufrufe nicht nötig.

Der Installer speichert die Pfade dieses Checkouts und dieser Python-Umgebung im
Skill. Beide müssen nach der Installation erhalten bleiben. In Codex lässt sich
der Skill als `$erechnung` verwenden; falls er noch nicht aufgelistet wird, einen
neuen Chat öffnen. Ein Beispielauftrag:

> Nutze eRechnung mit den Beispieldaten. Erstelle nur eine Vorschau für Beispiel
> GmbH: drei Tage Gestaltung à 800 EUR netto, Leistungszeitraum 1.–3. Oktober 2026,
> Rechnungsdatum 7. Oktober 2026, fällig am 21. Oktober 2026, 19 % USt,
> Rechnungsnummer DEMO-2026-002.

Zum Entfernen ausschließlich des Skills:

```bash
.venv/bin/python scripts/install_assistant_skill.py --uninstall
```

Rechnungen, Arbeitsordner und App bleiben erhalten. Die Schnittstelle lässt sich
auch direkt mit `.venv/bin/python assistant_cli.py --help` verwenden; sie ist keine
Abhängigkeit der App. Befehle und Datenformat stehen in
[`integrations/codex/erechnung/references/commands.md`](integrations/codex/erechnung/references/commands.md).
Für echte Daten muss der betreffende Datenordner explizit ausgewählt werden.
Die Dateien werden lokal erzeugt; Angaben, die der Assistent liest, gelangen aber
in seinen Modellkontext und gegebenenfalls zum Cloud-Anbieter.
Eine Freigabe-Oberfläche und Berechtigungen pro Agent sind noch nicht enthalten.
Die Bestätigung im Skill ist eine Gesprächsregel, keine technische Zugriffssperre.
Dieses Konzept wird separat entworfen; der PR bleibt vorerst ein Prototyp.

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
zur Aussteller-Verwaltung in 1.2.0 erscheinen einmalig automatisch. `ANNOUNCEMENT = None` deaktiviert
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
