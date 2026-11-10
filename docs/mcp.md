# Lokaler Agentenzugriff über MCP (experimentell)

Diese Anbindung verwendet das Model Context Protocol über **stdio**. Sie ist nicht
an einen bestimmten Agenten oder Anbieter gebunden. Ein kompatibler Client muss
lokale MCP-Prozesse starten können. Ein reiner Cloud-Chat erhält dadurch noch
keinen Zugriff auf deinen Mac; dafür wäre eine zusätzliche lokale Brücke nötig.
Dieser PR enthält keinen Cloud-Dienst und veröffentlicht keinen Netzwerkserver.

## Ausprobieren

Für Entwicklung und manuelle Tests ausschließlich fiktive Daten verwenden:

```sh
ERECHNUNG_TEST_MODE=1 ERECHNUNG_MCP=1 ./run.sh
```

Das startet die App mit einem frischen temporären Datenordner auf Port 5001.
Stammdaten und einen Beispielkunden in dieser Testinstanz anlegen. Für einen
selbst gebauten macOS-Build zuerst `dist/eRechnung.app.zip` in einen Testordner
entpacken. Aus diesem Ordner lautet der entsprechende Teststart:

```sh
ERECHNUNG_TEST_MODE=1 ERECHNUNG_MCP=1 eRechnung.app/Contents/MacOS/eRechnung
```

1. In den Einstellungen zum Abschnitt **Agentenzugriff erlauben** gehen. Ohne `ERECHNUNG_MCP=1` bleibt
   dieser Eintrag unsichtbar und die Werkzeug- und Einstellungsendpunkte sind abgeschaltet.
2. Den Hinweis zur möglichen Datenübertragung an den Agentenanbieter lesen und
   den Schalter **Agentenzugriff erlauben** einschalten. Die Änderung gilt sofort,
   ohne zusätzlichen Speichern-Button. Das allein gibt noch keinem Agenten Zugriff.
   Beim Ausschalten erscheint zuerst eine Bestätigung mit den betroffenen
   Verbindungen. Erst **Ausschalten und Zugänge löschen** widerruft alle Zugänge
   und offenen Anfragen; erneutes Einschalten stellt diese nicht wieder her.
   **Abbrechen** erhält den bisherigen Zustand. Hat sich die Liste seit der
   Anzeige geändert, muss sie vor dem Ausschalten erneut geprüft werden.
3. **Verbindungen und Aktionsfreigaben** öffnen und mit **+** eine neue Verbindung
   anlegen. Im Dialog einen Namen und die gewünschten Aussteller wählen.
   Unter **Kundenzugriff** zwischen **Keine Kundendaten**, **Nur ausgewählte Kunden**
   (Mehrfachauswahl) und **Alle Kunden** wählen. Neue Verbindungen starten ohne
   Kundenfreigabe. Ohne Änderungsrecht bleiben freigegebene Daten auf Lesen,
   Prüfen und Vorschau beschränkt.
4. Optional **Rechnungen erstellen und Datenänderungen anfragen** erlauben.
5. Die einmalig angezeigte Konfiguration in den MCP-Client übernehmen. Manche
   Clients benötigen statt des `mcpServers`-Blocks ein eigenes Konfigurationsformat;
   Befehl, Argumente und Umgebungsvariablen bleiben dieselben.
6. In der App unter **Aktionsfreigaben → Aktualisieren** offene Aktionen prüfen.
   Diese stammen von bereits eingerichteten MCP-Verbindungen und geben keinem
   weiteren Agenten Zugang. Lesen, Prüfen und Vorschauen benötigen keine einzelne
   Bestätigung; endgültige Rechnungen, Änderungen an bestehenden Daten und
   Löschungen benötigen weiterhin die ausdrückliche Freigabe in eRechnung.
7. Jede Verbindung lässt sich mit ihrem eigenen Schalter pausieren und wieder
   einschalten. Schlüssel, Aussteller und Rechte bleiben erhalten. Beim Pausieren
   werden alle Aufrufe sofort gesperrt und ihre offenen Anfragen verworfen; diese
   leben beim Wiedereinschalten nicht wieder auf. Andere Verbindungen bleiben aktiv.
   **Zugang löschen** zeigt zuerst eine Warnung und widerruft den Schlüssel nach
   **Dauerhaft löschen** endgültig. Für einen späteren Zugriff ist dann eine neue
   Verbindung nötig. Rechnungen und gespeicherte Daten bleiben erhalten.
8. **Konfiguration einrichten** an einer bestehenden Verbindung öffnet die
   Einrichtung erneut. Eine funktionierende Verbindung benötigt keinen neuen
   Schlüssel. Bei verlorener Konfiguration zuerst die Warnung lesen und dann
   **Neuen Schlüssel erzeugen** bestätigen. Erst dann wird der bisherige Schlüssel
   ungültig und die vollständige neue Konfiguration einmalig angezeigt, mit einem
   Button zum Kopieren. Diese Konfiguration im Agenten ersetzen.

Beim Erneuern bleiben Aussteller, Kundenfreigaben, Lese-/Änderungsrechte und der
pausierte/aktive Zustand exakt erhalten. Offene Anfragen dieser Verbindung werden
verworfen; andere Verbindungen bleiben unverändert. Veraltete Bestätigungen und
doppelte Übermittlung erzeugen keinen weiteren Schlüssel. Hat sich die Verbindung
geändert, muss ihr aktueller Stand erneut geprüft werden. Ein deaktivierter oder
gelöschter Zugang wird dadurch nicht wiederhergestellt. Die Schlüssel bleiben
ausschließlich als Prüfwerte gespeichert; es gibt keine betriebssystemspezifische
Schlüsselspeicherung. Nach Verlassen der einmaligen Anzeige lässt sich ein
verlorener Schlüssel daher nur durch bewusstes Erneuern ersetzen.

Der erzeugte Befehl startet entweder `mcp_server.py` mit dem Python-Interpreter
der App oder die gebündelte macOS-Datei mit `--mcp`. Außerhalb des Testmodus enthält
die erzeugte Konfiguration zusätzlich `ERECHNUNG_MCP_AUTOSTART=1` und den bereits
verwendeten Feature-Schalter `ERECHNUNG_MCP=1`. Beim Verbindungsaufbau wird eine
laufende App wiederverwendet; ist sie geschlossen, öffnet sich dieselbe Installation
automatisch. Auf macOS erscheint das native App-Fenster, beim Quellstart die lokale
Web-App im Browser. Die Brücke wartet höchstens 15 Sekunden auf die Bereitschaft.
Mehrere Verbindungen teilen eine Startsperre; manueller und automatischer Start
verwenden außerdem dieselbe Instanzsperre. So bleibt auch bei gleichzeitigen oder
langsamen Starts nur eine App mit einer gemeinsamen Liste offener Bestätigungen
aktiv. Gehört der zuletzt verwendete Port inzwischen einem anderen Programm,
startet eRechnung auf einem neuen Port. Das andere Programm erhält weder
Zugangsschlüssel noch Rechnungsaufrufe; Weiterleitungen werden nicht verfolgt.

Der Start aktiviert weder das Opt-in noch legt er Zugänge an. Ausgeschalteter oder
widerrufener Zugriff bleibt gesperrt. Eine laufende App mit abgeschaltetem
Feature-Schalter wird ebenfalls nicht ersetzt. Rechnungen und destruktive Aktionen
brauchen weiterhin ihre separate Bestätigung. Fehlgeschlagene Schreibaufrufe
werden nicht automatisch wiederholt.

Eine lokale Datei enthält die aktuelle Adresse, sodass ein geänderter macOS-Port
keine neue Konfiguration erfordert. Der MCP-Prozess liest keine Rechnungsdaten
direkt und übergibt den Zugangsschlüssel nicht an die gestartete App. Beim Trennen
des Agenten bleibt das App-Fenster geöffnet.

Bestehende Konfigurationen können die beiden Schalter ergänzen; der vorhandene
Zugang bleibt verwendbar. Mit `ERECHNUNG_MCP_AUTOSTART=0` bleibt der Start manuell.
Konfigurationen mit fester URL, Testinstanzen und andere Betriebssysteme als macOS
oder Linux starten nicht automatisch. Testkonfigurationen enthalten ausdrücklich
`ERECHNUNG_TEST_MODE=1`, damit sie niemals produktive Daten öffnen; nach Beenden der
Testinstanz muss für eine neue Testinstanz auch eine neue Verbindung angelegt werden.

Die Umgebungsvariablen der Brücke sind `ERECHNUNG_MCP_TOKEN` und
`ERECHNUNG_MCP_ENDPOINT_FILE`. Für eigene lokale Integrationen kann stattdessen
`ERECHNUNG_MCP_URL=http://127.0.0.1:<port>` gesetzt werden. Andere Rechneradressen,
Umleitungen und Proxys werden nicht unterstützt. Keine Schlüssel in Prompts,
Rechnungen, öffentlichen Repositories oder Fehlerberichten teilen.

## Funktionen und Rechte

| Bereich | MCP-Werkzeuge | Verhalten |
| --- | --- | --- |
| Format | `invoice_schema` | Felder, Einheiten und Steuerarten abfragen |
| Stammdaten | `list_issuers`, `get_issuer` | Nur explizit freigegebene Aussteller, einschließlich deaktivierter Profile |
| Kunden | `list_customers` | Nur freigegebene Kunden inklusive ihrer gespeicherten Positionen durchsuchen |
| Archiv | `list_invoices`, `get_invoice`, `get_invoice_file` | Nur Belege innerhalb der Aussteller- und Kundenfreigabe lesen, über alle Jahre einschließlich undatierter und reiner XML-Belege |
| Vorbereitung | `next_number`, `check_invoice`, `preview_invoice` | Nummer vorschlagen, XML prüfen, als Entwurf markiertes PDF erzeugen; ohne Nummernreservierung oder Archivänderung |
| Erstellen | `create_invoice` | Endgültige Rechnung erst nach Prüfung und App-Bestätigung erstellen |
| Bearbeiten | `save_customer`, `save_customer_items`, `save_issuer` | Neue Kundendaten speichern; Änderungen bestehender Daten benötigen App-Bestätigung |
| Löschen | `delete_customer`, `delete_invoice`, `deactivate_issuer` | Auswirkungen anzeigen und auf ausdrückliche App-Bestätigung warten |
| Wiederherstellen | `restore_issuer` | Freigegebenen deaktivierten Aussteller mit bestehender Nummernfolge reaktivieren |
| Rückmeldung | `request_status` | Status ausschließlich eigener Anfragen abfragen; keine Freigabe erteilen |

Beim XML-Abruf wird für ZUGFeRD das unveränderte XML aus dem archivierten PDF
ausgelesen, für XRechnung die archivierte XML-Datei. Die App erzeugt dafür kein
neues XML aus aktuellen Stammdaten.

Die MCP-Archivliste verwendet keinen Jahresfilter der Oberfläche. Sie liefert auch
den gespeicherten XML-Prüfstatus; dieser gilt nur für die geprüften Dateiinhalte und
Prüfregeln, nicht für die steuerliche Richtigkeit. Für Dateiabrufe, Vorlagen und
Korrekturen ist weiterhin ein gespeicherter Rechnungsschnappschuss erforderlich.
Reine XRechnungen mit Schnappschuss können über ihren XML-Dateinamen gelesen,
als Korrekturgrundlage verwendet und nach App-Bestätigung gelöscht werden.

Schreibende Werkzeuge benötigen die zusätzliche Änderungsberechtigung. Neue
Kundendatensätze erfordern zusätzlich **Alle Kunden**. Neue Datensätze und Reaktivierungen sind keine destruktiven Änderungen und
benötigen keine zweite Bestätigung. Bestehende Archivdateien können auch mit einer
Bestätigung nicht durch abweichende Rechnungen gleicher Nummer ersetzt werden.

Rechnungen unterstützen Positions- und Gesamtrabatte, bereits gezahlte Beträge,
Anzahlungsrechnungen, Stornos und Korrekturen. Für deaktivierte Aussteller bleiben
die Regeln der App maßgeblich: Stornos/Korrekturen benötigen die Originalrechnung
als `correction_source` und deren unveränderten Ausstellerstand. Eine neue normale
Rechnung erfordert zuvor eine Reaktivierung. Dafür werden dieselben Routinen wie
in der App genutzt, einschließlich Prüfung, Schreibsperre und Duplikatschutz.

`get_issuer` liefert eine Revision, die zum Prüfen/Erstellen und Bearbeiten nötig
ist. Veraltete Revisionen werden abgewiesen. Geldbeträge sind Dezimalstrings mit
Punkt, Daten sind ISO-Daten, Steuerart und Aussteller müssen ausdrücklich gewählt
werden. `next_number` reserviert nichts; bei unklarem Nummernlauf fordert seine
Antwort zur Rückfrage auf. Die endgültige Nummer wird immer nochmals angezeigt.

## Kunden gezielt freigeben

**Nur ausgewählte Kunden** gilt für Kundendaten, gespeicherte Positionen und
zugeordnete Rechnungen. Auch direkte PDF-/XML-Abrufe, Löschungen, Änderungen,
Vorschauen und neue Rechnungen werden serverseitig geprüft. Ein erratener
Dateiname oder ein gleichlautender Kundenname genügt nicht. Die Prüfung erfolgt
erneut beim Ausführen einer bestätigten Anfrage.

PDF-/XML-Downloads bei **Nur ausgewählte Kunden** prüfen zusätzlich, ob die
tatsächlich gelesene Datei unverändert dem beim Archivieren gespeicherten
Prüfwert entspricht. Extern geänderte Dateien und Belege ohne diesen Nachweis
bleiben gesperrt. Eine erneute erfolgreiche XML-Prüfung hebt diese Sperre nicht
auf: Technische Gültigkeit bestätigt keine Kundenzuordnung. Bei ZUGFeRD gilt
der Abgleich für das gesamte PDF, auch wenn nur dessen XML abgerufen wird;
bei XRechnung für die jeweils angeforderte PDF- oder XML-Datei. Eine inhaltlich
identische Dateikopie bleibt zugänglich. **Alle Kunden** erlaubt weiterhin auch
das Lesen geänderter Belege innerhalb der freigegebenen Aussteller.

Bei der Auswahl erhalten die Kundendatensätze eine feste interne Kennung.
`list_customers` liefert sie als `customer_id`; eingeschränkte Verbindungen müssen
diese bei Kunden- und Rechnungsaktionen mitsenden. Namens- und Adressänderungen
behalten die Kennung. Löschen und gleichnamiges Neuanlegen erzeugt eine andere
Identität und übernimmt keine Freigabe. Fehlt ein Kunde oder ist seine Kennung
mehrdeutig, bleibt auch sein Archiv für die eingeschränkte Verbindung gesperrt.

Neue Rechnungen werden beim Archivieren mit der vorhandenen Kundenkennung
verknüpft – auch bei Erstellung über die normale App. Die Kennung steht nur in
den lokalen Metadaten, nicht im PDF/XML. Belege, die vor der ersten gezielten
Kundenfreigabe erstellt wurden, können noch keine Kennung haben. Sie bleiben bei
eingeschränktem Zugriff gesperrt; auch ein identischer Neuexport ergänzt sie nicht
nachträglich. Es gibt keine automatische Zuordnung alter Belege anhand des Namens.
Korrekturen/Stornos benötigen bei eingeschränktem Zugriff eine freigegebene
Originalrechnung als `correction_source` mit derselben Kundenkennung.

**Keine Kundendaten** sperrt alle Kunden-/Belegaktionen; freigegebene Aussteller
und allgemeine Werkzeuge bleiben zugänglich. **Alle Kunden** umfasst ausdrücklich
auch neue Kunden und alte Belege. Bereits bestehende Verbindungen ohne diese
neue Einstellung behalten ihren bisherigen vollständigen Kundenzugriff. Um sie
einzuschränken, den Zugang löschen und mit der gewünschten Auswahl neu anlegen.
Die Verbindungskarte zeigt ihren aktuellen Kundenumfang.

## Bestätigung einer Änderung

Ein MCP-Aufruf liefert zunächst `status: approval_required` und eine Anfrage-ID.
Zu diesem Zeitpunkt wurde die angefragte Änderung nicht ausgeführt. Die App zeigt
die Verbindung, die konkrete Aktion, Warnung und betroffenen Daten. Bei einer
Rechnung werden zusätzlich Rechnungsfelder, Kunde und Positionen gezeigt.

Die Anzeige verwendet den geprüften Rechnungsstand einschließlich automatisch
übernommener Bezugsdaten bei Korrekturen und des ausgewählten Zahlungskontos.
**Ausdrücklich bestätigen** führt ausschließlich die gespeicherte Anfrage aus.
Die Freigabe gilt einmalig, höchstens fünf Minuten und nur für den zuvor geprüften
Datenstand. Änderungen zwischen Anfrage und Bestätigung führen zu Ablehnung oder
einer neuen, separat zu prüfenden Anfrage. Zusätzliche Felder im Bestätigungsaufruf
können die gespeicherte Aktion nicht verändern. Abbrechen, Pausieren, Widerruf oder Neustart
verhindern ihre spätere Ausführung. Über MCP gibt es keinen Bestätigungsbefehl.

Maximal 20 Verbindungen und 64 kurzlebige Anfragen werden gehalten. Identische
Wiederholungen einer noch offenen Anfrage liefern dieselbe ID. Erledigte Anfragen
sind vorübergehend für die Rückmeldung verfügbar; es gibt kein dauerhaftes
Aktivitätsprotokoll und kein allgemeines Rückgängig.

## Grenzen

- Dies ist ein **App-Dialog**, keine Touch-ID- oder Systembestätigung. Er verhindert
  Selbstfreigaben über diese MCP-Werkzeuge. Ein Agent mit zusätzlichem Browser-,
  App-Bedien- oder Dateizugriff kann außerhalb dieser Schnittstelle handeln.
- Berechtigungen gelten für die ausgewählten Aussteller und den aktuellen
  Datenordner. Neue Aussteller sind nicht automatisch freigegeben. Nach einem
  Ordnerwechsel funktionieren alte Zugänge für den neuen Ordner nicht. Beim
  Zurückwechseln können sie wieder für ihren ursprünglichen Ordner gelten.
- Kunden und gespeicherte Positionen sind appweit gemeinsam; die Freigabe filtert
  den Agentenzugriff, sie trennt die Datenbestände nicht. Freigegebene Datensätze
  und Belege werden vollständig angezeigt, ohne Feldmaskierung oder automatische
  Entfernung fremder Kundennamen aus Freitexten. Die gemeinsame Nummernfolge des
  Ausstellers bleibt auch bei eingeschränkter Kundenfreigabe sichtbar.
- Der Verbindungsname ist eine frei vergebene Bezeichnung, keine verifizierte
  Identität eines Anbieters. Wer den Schlüssel besitzt, kann diese Verbindung nutzen.
- Der globale Schalter **Agentenzugriff erlauben** entfernt beim Ausschalten alle
  Zugänge dauerhaft. Wieder einschalten erfordert neue Verbindungen. Der Schalter
  einer einzelnen Verbindung pausiert dagegen nur diesen Zugang. Ein gewöhnlicher
  App-Neustart erhält bestehende Zugänge einschließlich ihres pausierten Zustands.
- Die Verarbeitung in eRechnung bleibt lokal. Ein verbundener Agent kann gelesene
  Finanz- und Kontaktdaten an seinen Anbieter senden. Das Opt-in ersetzt keine
  Prüfung der Datenverarbeitung des gewählten Anbieters.
- Die App muss lokal bleiben. Gleichzeitige Änderungen auf mehreren Macs über
  synchronisierte Ordner werden dadurch nicht koordiniert.
- Diese erste Werkzeugliste umfasst Rechnungsarbeit und gespeicherte Daten, nicht
  jede Verwaltungsfunktion der Oberfläche: z. B. keine Datenordnermigration,
  Vergabe eigener Zugriffsrechte, Logo-Uploads oder Änderung des Standardausstellers.

PR #12 und #17 bleiben eigenständige offene Entwürfe. Die dortigen CLI-/Dateiimport-
Wege werden von dieser Anbindung nicht vorausgesetzt oder aktiviert.

## Technische Prüfung

`tests/test_mcp_access.py` prüft Opt-in, Rechte, Zustandswechsel und die echte
Rechnungserzeugung. `tests/test_mcp_customer_scope.py` prüft Mehrfachauswahl,
stabile Kundenidentitäten, gesperrte Altbelege, Dateiabrufe und erneute Prüfung
bei Bestätigung. `tests/test_mcp_protocol.py` verbindet einen SDK-Client über
stdio mit einer isolierten App und prüft Widerruf sowie die fehlende Möglichkeit,
über MCP zu bestätigen. Beide Tests verwenden ausschließlich temporäre Testdaten.
`tests/test_mcp_key_rotation.py` prüft die bestätigte Schlüsselerneuerung,
unveränderte Kundenfreigaben/Rechte/Pausen, gesperrte alte Schlüssel und veraltete
oder parallele Bestätigungen. Ein echter SDK-Test prüft zusätzlich den nötigen
Schlüsselwechsel im Client und die weiter geltenden Kunden- und Bestätigungsregeln.
`tests/test_mcp_archive_integration.py` prüft die Verbindung mit dem Archiv ab
Version 1.3: alle Jahre, undatierte Belege, reine XML-Rechnungen, gespeicherte
Prüfergebnisse und erneute Löschbestätigung nach einer externen Dateiänderung.
Die Kunden- und Ausstellerfreigaben gelten dabei unverändert. Die Protokolltests
prüfen auch undatierte Archivzeilen über einen echten MCP-Client.
Die macOS-CI startet zusätzlich die gebündelte App mit `--mcp` und prüft
Protokollinitialisierung, Werkzeugliste und Ablehnung ohne Freigabe.
Sie prüft auch den tatsächlichen App-Start aus dem ZIP in einem neuen temporären
Testordner und verifiziert, dass dadurch kein Opt-in erteilt wird.
`tests/test_mcp_startup.py` prüft Start, Wiederverwendung, parallele Verbindungen,
gleichzeitige manuelle Starts, anderweitig belegte alte Ports, Startfehler,
unveränderte Rechte und die weiterhin erforderlichen Bestätigungen.

Beim Quellstart bleibt der Debugger über `FLASK_DEBUG=1` verfügbar; der automatische
Entwicklungs-Neustart ist deaktiviert, damit kein zweiter Prozess die Instanzsperre
des Servers übernimmt. Nach Codeänderungen die App manuell neu starten.
