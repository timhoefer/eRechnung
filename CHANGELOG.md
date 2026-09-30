# Änderungen

## Noch nicht veröffentlicht

- Rechnungsvorlagen stellen internationale Kontonummern korrekt wieder her; ältere Vorlagen mit Konto-Index bleiben unterstützt.
- Die XML-Validierung erkennt XRechnung ausschließlich anhand der Profil-ID. Das Wort „XRechnung“ in Beschreibung, Freitext oder Kontaktdaten löst keine zusätzlichen Prüfungen mehr aus.
- Beim Sprachwechsel bleiben die Rabattbegründungen aller Positionen erhalten.
- Die Rechnungstabelle trennt Menge, Einzelpreis und Betrag durch jeweils 5 mm seitlichen Abstand; lange Beschreibungen brechen entsprechend früher um.
- Haupttext, Datumsangaben, Bankverbindung und Grußformel verwenden einheitlich 10 pt; der Gesamtbetrag wird mit 12 pt hervorgehoben. Damit bleiben vier Schriftgrößen: 8, 10, 12 und 14 pt.

## 1.1.1

- Validierung meldet nur dann Erfolg, wenn XSD und alle erforderlichen Schematron-Prüfungen erfolgreich waren. Fehlende Prüfungen und Ausführungsfehler ergeben keinen Erfolgsstatus; das gilt auch beim Prüfen vorhandener Dateien und beim macOS-Selbsttest.
- Negative Mengen und Einzelpreise werden in Vorschau und Export einheitlich auf null begrenzt.
- Einzelpreise behalten zusätzliche Nachkommastellen in PDF und XML; Positionssummen bleiben auf Cent gerundet.
- Der CSV-Export führt Stornos (Belegart 381) mit negativen Beträgen auf und enthält Belegart und Originalreferenz.
- Gleichzeitige Schreibzugriffe innerhalb der App werden serialisiert. Rechnungsdateien werden exklusiv angelegt; bestehende PDF-Dateien werden nicht überschrieben.
- Stammdaten und Kundenlisten werden atomar gespeichert. Beim Merken der letzten Rechnungsnummer wird der aktuelle Stammdatenstand verwendet.
- Regressionstests für Validierungsfehler, präzise Preise, negative Eingaben, Stornos und parallele Rechnungserzeugung ergänzt.

Bestehende Rechnungen und Archive werden nicht verändert. CSV-Importe müssen gegebenenfalls die beiden neuen Spalten berücksichtigen.
