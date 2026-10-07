# Änderungen

## Unveröffentlicht

- Optionaler, separat entfernbarer eRechnung-Skill mit lokaler Schnittstelle für Kunden, Vorlagen, Entwürfe, PDF-Vorschauen und validierte Exporte. Der Prototyp liest vorhandene App-Daten nur und speichert Ergebnisse in einem getrennten Arbeitsordner.
- App und Assistent verwenden denselben Rechnungskern. Die App bleibt ohne Skill und ohne LLM-Abhängigkeit nutzbar.

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
