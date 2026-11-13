# Änderungen

## Unreleased

- Agentenzugriff lässt sich direkt in den Einstellungen ein- und ausschalten. Neue Verbindungen werden über „+“ in einem Dialog angelegt; Konfiguration und Löschen stehen nebeneinander. Aktionsfreigaben und der Hinweis zur Datenverarbeitung sind klarer beschrieben.
- Die einmalig angezeigte MCP-Konfiguration bietet zwei Ansichten: den vollständigen Konfigurationsblock und einzeln kopierbare Befehle, Argumente sowie Namen und Werte der Umgebungsvariablen.
- Die Konfiguration öffnet sich als Dialog über der Verbindung. Der Sprachwechsel bleibt erreichbar und erhält den angezeigten Schlüssel sowie die gewählte Ansicht. Ein neuer Schlüssel entsteht weiterhin nur nach ausdrücklicher Bestätigung.

- Experimentelle lokale MCP-Anbindung, standardmäßig verborgen und ausgeschaltet: ausdrückliches Opt-in, getrennte widerrufbare Verbindungen und Ausstellerfreigaben. Lesen und Vorschauen sind getrennt von Änderungsanfragen. Löschen, Überschreiben und endgültiges Erstellen von Rechnungen warten auf eine einmalige Bestätigung der konkreten Aktion in der App.
- Eingerichtete MCP-Verbindungen öffnen eRechnung bei Bedarf automatisch und verwenden eine laufende App weiter. Opt-in, Widerruf und Bestätigungen gelten unverändert; Testinstanzen starten nicht automatisch neu.
- Gleichzeitige manuelle und automatische Starts teilen eine App-Instanz. Ist der alte Port inzwischen anderweitig belegt, öffnet sich eRechnung auf einem neuen Port, ohne Zugangsdaten an das andere Programm zu senden.
- Die MCP-Archivliste umfasst alle Jahre und undatierte Belege innerhalb der Freigaben. Reine XML-/XRechnung-Belege mit gespeichertem Rechnungsschnappschuss können abgerufen, für Korrekturen verwendet und nach Bestätigung gelöscht werden; gespeicherte XML-Prüfergebnisse werden mit angezeigt.
- Bei Kundenbeschränkungen werden PDF-/XML-Dateien nur ausgeliefert, wenn ihr Inhalt dem ursprünglichen Archivstand entspricht. Extern ersetzte Dateien oder fehlende Prüfnachweise bleiben gesperrt, auch nach erneuter erfolgreicher XML-Prüfung.

## 1.3.0

- Das Archiv lässt sich nach Jahr und Aussteller filtern oder für alle Aussteller gemeinsam anzeigen. Die Liste bleibt kompakt; gleiche Rechnungsnummern verschiedener Aussteller bleiben eindeutig zugeordnet. Das Erstellungsdatum steht im Vordergrund, die Uhrzeit bleibt als Zusatzinformation erreichbar.
- Im Auswahlmodus lassen sich einzelne Rechnungen, alle angezeigten Belege oder ganze Quartale als CSV exportieren. Ein Klick auf die Zeile schaltet die Auswahl um; Sortieren behält die Auswahl. Beim Wechsel von Jahr oder Aussteller wird sie zurückgesetzt.
- Vor dem CSV-Export werden die gespeicherten Rechnungswerte mit der tatsächlichen archivierten XML abgeglichen. Fehlende, geänderte oder widersprüchliche Daten brechen den Export mit einem Hinweis ab, statt unbemerkt abweichende Buchungsdaten auszugeben.
- Eine eigene XML-Spalte zeigt den gespeicherten technischen Prüfstatus. Ein grüner XML-Chip gilt nur für die geprüften Dateiinhalte, das passende Rechnungsprofil und den aktuellen Prüfregelsatz. Geänderte Dateien oder Prüfregeln machen eine erneute Prüfung erforderlich; der Chip ist keine Prüfung des gesamten PDF oder der steuerlichen Richtigkeit.
- Auch reine XML-/XRechnung-Belege erscheinen im Archiv. Rechnungen lassen sich jederzeit über das Zeilenmenü erneut prüfen; Prüfergebnisse können geschlossen werden. Vorhandene Rechnungsdateien werden dabei nicht verändert.
- Der Sprachwechsel erhält die geöffnete Einstellungsansicht, Archivfilter und Auswahl auch während laufender Ladevorgänge. Gespeicherte Prüfnachweise werden beim Datenordnerwechsel mitgenommen.
- macOS-Downloads als gestaltetes DMG mit App und Programme-Verknüpfung; das ZIP bleibt als Alternative verfügbar. Der helle Hintergrund enthält dezente Rechnungsmotive und Installationshinweise auf Deutsch und Englisch.
- Build- und Release-Prüfungen kontrollieren beide Downloads, einschließlich Signierung, Notarisierung und Selbsttest der aus dem DMG kopierten App. Die Verpackung erfolgt außerhalb synchronisierter Projektordner.
- Änderungen an bestehenden Stammdaten, Kunden und gespeicherten Positionen sowie Löschungen erhalten eine zusätzliche Bestätigung mit den betroffenen Daten. Unbestätigte Änderungen bleiben im Formular; beim Kundenwechsel wird vor ihrem Verlust gewarnt.
- Bestätigungen sind einmalig, zeitlich begrenzt und an Sitzung, konkrete Anfrage und bisherigen Datenstand gebunden. Abbrechen widerruft die Bestätigung.
- CSV-Exporte, Rechnungsbegleitdateien und Schreibproben ersetzen keine vorhandenen Dateien. Ein interner Testmodus verwendet ausschließlich temporäre Daten und einen eigenen Nummernlauf.
- Rechnungen werden erst nach erfolgreicher XSD-/Schematron-Prüfung archiviert. Fehlgeschlagene Prüfungen verändern weder Archiv, Kunden noch Nummernstand.
- Gleiche Rechnungsnummern desselben Ausstellers werden bei abweichendem Inhalt abgewiesen. Identische Wiederholungen verwenden den vorhandenen Beleg; verschiedene Aussteller behalten getrennte Nummernfolgen.
- Archivdateien werden vollständig vorbereitet, ohne vorhandene Dateien zu ersetzen. Unterbrochene Schreibvorgänge werden beim nächsten schreibenden Zugriff abgeschlossen. Eine gemeinsame lokale Prozesssperre schützt Stammdaten, Nummernstand und Datenordnerwechsel.

## 1.2.1

- Das Archiv zeigt standardmäßig die neuesten Dateien zuerst. Alternativ lässt es sich nach Rechnungsnummer oder Kunde sortieren. Unterschiedlich lange Nummern wie „2026-07“ und „2026-008“ werden numerisch korrekt eingeordnet.
- Die Sortierauswahl steht neben der Archivüberschrift, wirkt sofort und wird lokal gemerkt. Aussteller-Auswahl und Belege bleiben bei einem Wechsel zusammengehörig; der CSV-Zeitraum bleibt auch beim Wechsel über ein leeres Archiv erhalten.
- SaxonC auf 13.1.1 aktualisiert; die festgeschriebene Paketliste verwendet dieselbe Version. Die Testumgebung verwendet pytest 9.2.0.

Bestehende Rechnungsdateien und Nummernfolgen bleiben unverändert.

## 1.2.0

- Mehrere auswählbare Rechnungsaussteller mit eigenen Stammdaten, Bankverbindungen, Nummernfolgen und Archiven. Kunden bleiben gemeinsam nutzbar. Bestehende Daten bilden unverändert das erste Profil; weitere Profile werden im gleichen Datenordner getrennt gespeichert.
- Weitere Stammdaten lassen sich unten links anlegen. Erst ab zwei Profilen erscheint die Aussteller-Auswahl in der Kopfzeile der Stammdaten; sie ist auch im eingeklappten Zustand bedienbar. Der Statuswechsel zwischen vollständig und unvollständig verschiebt die Auswahl nicht.
- „Löschen“ und „Stammdaten speichern“ stehen unten rechts. „Löschen“ erscheint nur bei mindestens zwei aktiven Profilen und entfernt den Aussteller aus der normalen Auswahl. Seine Stammdaten und Belege bleiben im Archiv als „Nur Archiv“ erhalten. Über eine Originalrechnung lassen sich weiterhin Stornos und Korrekturen erstellen; andere neue Belege bleiben gesperrt. Alte Fenster können entfernte Profile nicht durch automatisches Speichern wiederherstellen.
- Veraltete Stammdatenformulare können neuere Änderungen nicht mehr überschreiben. Bei einem Konflikt lassen sich die aktuellen Stammdaten laden, während der Rechnungsentwurf erhalten bleibt. Die Prüfung erkennt auch bereits eingetroffene Synchronisationsänderungen; gleichzeitige Offline-Änderungen auf mehreren Macs bleiben unkoordiniert.
- Profilwechsel und Export warten auch auf Stammdatenänderungen, die während des Speicherns hinzukommen. Der Export prüft die bestätigte Stammdatenversion nochmals direkt vor dem Erzeugen; bei einem Konflikt bleiben Rechnungsnummer, Positionen und weitere Eingaben zur erneuten Prüfung erhalten. Es werden dabei keine Rechnungsdateien oder Nummernstände geändert; wiederholte Klicks währenddessen erzeugen keinen zweiten Export. Archivvorlagen behalten Positionsrabatte. Stornos und Korrekturen entfernter Aussteller übernehmen zusätzlich die ursprünglichen Leistungszeiträume. Galt ursprünglich das Rechnungsdatum als Leistungsdatum, wird dieses ausdrücklich übernommen, damit das neue Rechnungsdatum es nicht verändert. Die geprüfte Belegart bleibt auch bei unvollständigen Anfragen erhalten.
- Bei mehreren aktiven Profilen lässt sich ein Standardaussteller für den App-Start festlegen. Manuelle Wechsel und bereits offene Formulare behalten ihren jeweiligen Aussteller. Die Standardauswahl und erhaltene Archive werden beim Datenordnerwechsel mitgenommen.
- Entfernte Aussteller lassen sich im Archiv und beim Anlegen weiterer Stammdaten reaktivieren, auch ohne vorhandene Belege. Stammdaten, Archiv und Profilidentität bleiben erhalten; der aktuelle Standard bleibt unverändert. Der Nummernvorschlag berücksichtigt den gespeicherten Zähler und die höchste archivierte Nummer des laufenden Jahres. Adress- und Namensänderungen innerhalb eines Profils beginnen keine neue Nummernfolge.
- Der Datenordnerwechsel prüft auch im ursprünglichen Archiv abweichende Dateien und meldet Kopierfehler direkt. Stammdaten und Belege werden erst nach vollständiger Kopie aus dem alten Ordner entfernt. Sprachwechsel behalten den Rechnungsentwurf auch nach einem Datenumzug.
- Beim Archivwechsel passen Aussteller-Auswahl und Belege auch während des Ladens und nach Fehlern zusammen. Verspätete Antworten öffnen ein bereits geschlossenes Archiv nicht erneut.
- Vorschau, PDF/XML, Archivaktionen, Vorlagen und CSV-Export verwenden das ausgewählte Profil auch bei mehreren geöffneten Fenstern. Ein ausgefülltes Rechnungsformular wird beim Profilwechsel erst nach Bestätigung verworfen. Während Bestätigung und Speichern ist die Auswahl gesperrt; bei Abbruch oder Fehler zeigt sie weiter das tatsächlich geladene Profil.
- Ein Dialog stellt ausgewählte größere Feature-Releases einmalig automatisch vor. Kleinere Neuerungen sind nur über „Neuigkeiten“ in den Einstellungen erreichbar. Bereits gelesene Hinweise werden lokal gemerkt. Der Dialog unterstützt Deutsch, Englisch sowie Hell- und Dunkelmodus.

## 1.1.4

- Überarbeitetes Rechnungslayout mit ruhigen Tabellenüberschriften, mehr Abstand vor der Leistungstabelle und einem hinterlegten Gesamtbetrag. Die Datumsangaben bleiben unter der Rechnungsnummer.
- Bankdaten behalten gut lesbare 10 pt; ihre Labels verwenden 8 pt und die Zeilen sind kompakter. Zahlungsinformationen und Grußformel bleiben nach Möglichkeit zusammen.
- Bei Kunden in einem anderen Land enthält die Absenderadresse den Ländernamen in der Rechnungssprache.
- Einseitige Rechnungen verzichten auf die Fußzeile. Mehrseitige Rechnungen behalten Rechnungsnummer und Seitenzählung auf jeder Seite.
- Lange Einzelpositionen können über mehrere Seiten umbrechen; die Tabellenüberschriften werden dabei wiederholt.
- Die Archivvorschau und ihre vergrößerte Ansicht zeigen das unveränderte Original-PDF, auch ohne gespeicherte Vorlagendaten.

## 1.1.3

- WeasyPrint auf 70.0 aktualisiert. Das Sicherheitsupdate behebt CVE-2026-55073 (Umgehung von Zugriffsbeschränkungen beim Laden von PDF-Metadaten und Stylesheets) und unterbindet die Verarbeitung von EPS-Bildern über Ghostscript.
- Die macOS-ZIP-Verpackung hält Zusatzmetadaten außerhalb der signierten App. Dadurch hinterlässt das Entpacken keine zusätzlichen Dateien in eingebetteten Frameworks, die Gatekeeper blockieren würden. Die Release-Prüfung erkennt fehlerhaft gepackte Archive vor dem Entpacken.

## 1.1.2

- Rechnungsvorlagen stellen internationale Kontonummern korrekt wieder her; ältere Vorlagen mit Konto-Index bleiben unterstützt.
- Die XML-Validierung erkennt XRechnung ausschließlich anhand der Profil-ID. Das Wort „XRechnung“ in Beschreibung, Freitext oder Kontaktdaten löst keine zusätzlichen Prüfungen mehr aus.
- Beim Sprachwechsel bleiben die Rabattbegründungen aller Positionen erhalten.
- Die Rechnungstabelle trennt Menge, Einzelpreis und Betrag durch jeweils 5 mm seitlichen Abstand; lange Beschreibungen brechen entsprechend früher um.
- Haupttext, Datumsangaben, Bankverbindung und Grußformel verwenden einheitlich 10 pt; der Gesamtbetrag wird mit 12 pt hervorgehoben. Damit bleiben vier Schriftgrößen: 8, 10, 12 und 14 pt.
- Die Fußzeile enthält ein sichtbares Leerzeichen nach dem Mittelpunkt vor der Seitenangabe.

## 1.1.1

- Validierung meldet nur dann Erfolg, wenn XSD und alle erforderlichen Schematron-Prüfungen erfolgreich waren. Fehlende Prüfungen und Ausführungsfehler ergeben keinen Erfolgsstatus; das gilt auch beim Prüfen vorhandener Dateien und beim macOS-Selbsttest.
- Negative Mengen und Einzelpreise werden in Vorschau und Export einheitlich auf null begrenzt.
- Einzelpreise behalten zusätzliche Nachkommastellen in PDF und XML; Positionssummen bleiben auf Cent gerundet.
- Der CSV-Export führt Stornos (Belegart 381) mit negativen Beträgen auf und enthält Belegart und Originalreferenz.
- Gleichzeitige Schreibzugriffe innerhalb der App werden serialisiert. Rechnungsdateien werden exklusiv angelegt; bestehende PDF-Dateien werden nicht überschrieben.
- Stammdaten und Kundenlisten werden atomar gespeichert. Beim Merken der letzten Rechnungsnummer wird der aktuelle Stammdatenstand verwendet.
- Regressionstests für Validierungsfehler, präzise Preise, negative Eingaben, Stornos und parallele Rechnungserzeugung ergänzt.

Bestehende Rechnungen und Archive werden nicht verändert. CSV-Importe müssen gegebenenfalls die beiden neuen Spalten berücksichtigen.
