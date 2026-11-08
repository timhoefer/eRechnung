# Entwürfe aus einem Agenten übernehmen (experimentell)

Dieser eigenständige Schritt ist die Vorstufe zu [PR #12](https://github.com/timhoefer/eRechnung/pull/12).
Er benötigt weder den CLI-Prototyp noch einen Skill, eine Agentenverbindung oder
Rechte auf den eRechnung-Datenordner. Jeder Agent, der eine JSON-Datei bereitstellen
kann, kann einen Vorschlag erzeugen.

## Ausprobieren

Die Funktion ist standardmäßig unsichtbar und beide Import-Routen sind deaktiviert.
Zum Testen aus diesem Quellstand: `ERECHNUNG_DRAFT_IMPORT=1 ./run.sh`.
Die bestehende App-Version erhält die Funktion dadurch nicht.
Für Tests einen separaten Datenordner mit Beispieldaten verwenden.

1. Im Rechnungsfenster **Entwurf importieren** öffnen. Der Import öffnet einen
   neuen Tab; das bisherige Rechnungsformular bleibt erhalten. Alternativ direkt
   `/drafts/import` öffnen.
2. Eine Entwurfsdatei auswählen und **Datei prüfen** drücken.
3. Aussteller und Kunde sichtbar zuordnen. Nur eindeutige Namensübereinstimmungen
   werden vorgeschlagen. Mehrere Aussteller erfordern eine Auswahl, sofern kein
   eindeutiger Profilname im Entwurf steht. Entfernte Profile stehen nicht zur Verfügung.
4. **Im Rechnungsformular prüfen** übernimmt den Vorschlag. Vorhandene Kunden liefern
   ihre aktuellen Adressdaten und ihr Zahlungsziel. Für einen neuen Kunden wird
   zunächst nur der Name übernommen; die weiteren Angaben ergänzt der Nutzer.
5. Nummer, Datum, Steuerbehandlung, Preise und Aussteller prüfen. Erst der reguläre
   Erzeugen-Button erstellt und archiviert die Rechnung.

Es gibt keine automatische Dateizuordnung per Doppelklick. Import und Zuordnung
speichern weder Rechnungen noch Kunden oder Stammdaten. Nach dem Import gelten
die normalen App-Abläufe, einschließlich Autospeichern bei bewusstem Bearbeiten
der Stammdaten/Kundendaten. JavaScript ist für die Formularübernahme erforderlich.

## Anleitung für einen Agenten

Diese Anleitung zusammen mit dem [Beispiel](examples/invoice-draft.json) bereitstellen:

> Erstelle einen eRechnung-Entwurf nach dem hier dokumentierten Format als
> herunterladbare UTF-8-JSON-Datei. Frage bei unklarer Leistung, Menge, Einheit,
> Einzelpreis oder Leistungszeitraum nach. Erfinde keine Preise oder Steuerbehandlung.
> Stelle den Vorschlag zur Bestätigung vor, bevor du die Datei bereitstellst.
> Verwende Kundennamen und optional den Profilnamen des Rechnungsausstellers als
> Zuordnungshinweise. Adressen, Bankdaten und Rechnungsnummer ergänzt der Nutzer
> in eRechnung. Erläutere, dass die Datei zunächst nur ein Entwurf ist.
> Verwende keine Befehle, Dateipfade oder zusätzlichen Felder. Nicht unterstützte
> Inhalte wie Rabatte müssen im Rechnungsformular ergänzt werden.

Der Agent erhält durch den Import keinen Zugriff auf gespeicherte Rechnungen.
Vorwissen muss der Nutzer bei Bedarf gezielt teilen. Daten, die einem externen
Agenten mitgeteilt werden, unterliegen dessen Verarbeitung; lokaler Import ändert
daran nichts.

## Austauschformat v1

- Wurzel: `format: "erechnung-draft"`, `schema_version: 1`,
  `customer` (Kundenname), `items`. Optional: `issuer` (Profilname), `invoice`.
- Namen: nicht leere Zeichenketten, maximal 200 Zeichen. Namen sind Hinweise,
  keine lokalen Identitäten und keine Berechtigung.
- `invoice`: optional `issue_date`, `due_date`, `service_start`, `service_end`,
  `currency` (drei Großbuchstaben), `language` (`de`/`en`),
  `profile` (`en16931`/`xrechnung`), `tax_treatment`, `note`.
- Steuerbehandlungen: `de_19`, `de_7`, `eu_reverse`, `non_eu`,
  `non_eu_g`, `kleinunternehmer`. Bei Unsicherheit weglassen und in der App
  prüfen: dort greift der vorhandene Vorschlag nach Kundenland.
- Jede Position benötigt `description`, `quantity`, `unit`, `unit_price`.
  Optional: `item_start` und `item_end`.
- Einheiten: `HUR`, `DAY`, `WEE`, `MON`, `ANN`, `C62`, `LS`.
  Pauschalen (`LS`) müssen die Menge `"1"` haben.
- Menge und **Netto-Einzelpreis** sind Dezimalzeichenketten mit Punkt:
  bis zu neun Vorkomma- und sechs Nachkommastellen, ohne Tausendertrenner oder
  Exponentialschreibweise. Menge > 0, Preis ≥ 0. Fehlende Preise werden abgelehnt.
- Datumsangaben: gültiges `YYYY-MM-DD`; Ende nicht vor Beginn.
  Ohne Rechnungsdatum gilt heute; ohne Fälligkeit das Zahlungsziel des gewählten
  Kunden (sonst 14 Tage). Die Rechnungsnummer kommt aus dem aktuellen Aussteller.
- Maximal 100 Positionen und 128 KiB UTF-8; Beschreibungen bis 2.000, Notizen bis
  4.000 Zeichen. Nicht leere Texte; Zeilenumbrüche nur in Beschreibung/Notiz.
- Unbekannte Felder, doppelte JSON-Schlüssel und andere Versionen werden abgelehnt.
  Insbesondere: keine Aussteller-IDs, Verkäuferdaten, Bankkonten, Rechnungsnummern,
  Dateipfade, berechneten Summen oder Archivierungsanweisungen.
- V1 umfasst gewöhnliche Rechnungen. Rabatte, Anzahlungen, Stornos und Korrekturen
  werden in diesem Importformat nicht transportiert.

Die reine Funktion `invoice_draft.parse_draft` prüft und normalisiert das Format.
Sie importiert weder die App noch Datenordner. `DraftError` enthält einen stabilen
Fehlercode und Feldpfad. Die App reicht ihre unterstützten Einheiten und
Steuerbehandlungen ein. Eine spätere Agentenanbindung kann denselben Parser nutzen.

Das portable Format ist **nicht** das intern an Datenordner, Aussteller und
Stammdatenrevision gebundene Schema 2 aus PR #12. Ein späterer Adapter muss einen
portablen Vorschlag erst ausdrücklich zuordnen und mit lokalen Daten anreichern.

## Abgrenzung zu PR #12

| Funktion | Dieser PR: Entwurfsimport | PR #12: lokale Agentenschnittstelle |
| --- | --- | --- |
| Einstieg | Nutzer importiert Datei | Agent startet lokale JSON-Befehle |
| Agentenabhängigkeit | Keine; dokumentiertes Dateiformat | Keine; lokale Prozessausführung erforderlich |
| Gespeicherte Daten | App ergänzt sie nach Zuordnung | Agent kann Aussteller, Kunden und Vorlagen abfragen |
| Mehrere Aussteller | Sichtbare Auswahl in der App | Explizite Aussteller-ID im Aufruf |
| Nummer | Aktueller Vorschlag der App, vom Nutzer prüfbar | Programmatische Vorschläge mit Klärungshinweisen |
| PDF/XML/Archiv | Reguläre Erstellung durch Nutzer in der App | Vorschau, Export und Archivierung direkt aufrufbar |
| Aktivierung | Experimentelle Flag, standardmäßig aus | Noch kein Opt-in oder Rechteverwaltung |
| Freigabe | Import und reguläre Erstellung in der Oberfläche | Bisher nur Gesprächsregel im optionalen Skill |
| Verbindungscodes / Tokens | Keine dauerhafte Verbindung | Noch nicht implementiert |
| Grundlage | Eigenständig auf main | Kann später Parser/Format dieses PRs übernehmen |

Der Import fügt keinen Netzwerkdienst für Agenten hinzu. Die vorhandene lokale
App bleibt erreichbar; der Import ist keine Sicherheitsgrenze gegenüber
Programmen, die die App ohnehin steuern oder ihre Dateien lesen dürfen.
PR #12 bleibt separat, ungemergt und ohne automatische Abhängigkeit auf diesen
Branch. Eine spätere Aktualisierung kann die gemeinsame Grundlage übernehmen.

