# Prüfung mit mehreren Geräten

Die App verwendet lokale Dateien. Die neue Stammdatenprüfung erkennt einen alten
Formularstand, sobald die neuere Datei auf demselben Gerät vorhanden ist. Eine
bereits synchronisierte Änderung wird ebenfalls erkannt. Die Prüfung reserviert
keine Daten geräteübergreifend: Zwei offline arbeitende Macs können beide denselben
alten Stand für aktuell halten und unterschiedliche Änderungen speichern.

## Automatisch geprüft

- Zwei Fenster derselben App speichern denselben Ausgangsstand gleichzeitig:
  genau eine Änderung wird gespeichert, die andere erhält einen Konflikthinweis.
- Wartende automatische Speicherungen benutzen die jeweils zuletzt bestätigte
  Version. Nach einem Konflikt erfolgen keine weiteren automatischen Schreibzugriffe.
- Zwei unabhängige App-Prozesse nutzen getrennte Kopien eines Testdatenordners.
  Trifft die Datei von A vor dem Speichern auf B ein, wird Bs veraltete Änderung abgewiesen.
- Sind beide Kopien noch unsynchronisiert, werden beide Änderungen angenommen.
  Dieser Test dokumentiert die verbleibende Grenze; er ist keine Freigabe für
  gleichzeitige Nutzung auf mehreren Geräten.

Diese Tests verwenden temporäre, fiktive Daten. Sie testen keinen Dropbox- oder
iCloud-Client. Auch zwei eigenständige App-Prozesse mit demselben lokalen Ordner
haben derzeit keine gemeinsame Transaktionssperre.

## Noch auf zwei echten Macs zu prüfen

Für jeden verwendeten Synchronisationsdienst separat und ausschließlich mit einem
neuen Testdatenordner prüfen. Beide Macs verwenden denselben App-Build. Vor jedem
Durchlauf eine vollständige Kopie des Ausgangsordners sichern.

| Fall | Ablauf | Erwartung bzw. Prüffrage |
| --- | --- | --- |
| Änderung angekommen | Beide öffnen Profil A; Mac A ändert die Adresse. Nach abgeschlossenem Sync speichert Mac B seinen alten Stand. | B meldet einen Konflikt; As Adresse bleibt erhalten. |
| Gleichzeitige Änderungen | Beide bearbeiten dieselben Stammdaten vor dem Sync. | Prüfen, ob beide Fassungen auffindbar bleiben oder eine still überschrieben wird. Ein stiller Verlust verhindert die Freigabe. |
| Offline und wieder online | B wird vom Netz getrennt; beide ändern dasselbe Profil; B verbindet sich später wieder. | Beide Fassungen und eventuelle Konfliktdateien erfassen. Keine automatische sichere Zusammenführung voraussetzen. |
| Gleiche Rechnungsnummer | Beide erzeugen mit demselben Aussteller dieselbe Nummer mit unterschiedlichen Inhalten. | Nach dem Sync müssen beide PDF/XML/JSON-Sätze vollständig und eindeutig zugeordnet sein. |
| Verschiedene Aussteller | A erzeugt einen Beleg als Freiberufler, B als Firma. | Belege und Zähler bleiben im jeweiligen Profil; gemeinsame Kundenänderungen separat prüfen. |
| Aussteller stillgelegt | A entfernt das Profil aus der Auswahl; B bearbeitet einen alten Formularstand. | Nach eingetroffenem Sync keine Wiederherstellung durch spätes Speichern; Archiv bleibt lesbar. |

Vor und nach jedem Durchlauf Dateiliste und SHA-256-Prüfsummen aller PDF-, XML-
und JSON-Dateien vergleichen. Originalbelege müssen unverändert bleiben. Zusätzlich
beide App-Archive öffnen und die betroffenen Rechnungen validieren. App-Version,
macOS-Version, Sync-Dienst, Ablauf und Ergebnis protokollieren.

Bis diese Fälle mit einer geeigneten Koordination gelöst sind, ist paralleles
Schreiben auf mehreren Macs nicht als unterstützt anzusehen. Eine lokale Prüfung
kann die Ergebnisse eines echten Synchronisationsdienstes nicht ersetzen.
