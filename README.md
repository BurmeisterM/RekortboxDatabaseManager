# Rekordbox Database Manager

Deutsche Windows-Desktop-App zur Verwaltung der Rekordbox-`master.db`. Die Datenbank kann auf dem PC oder einem externen Laufwerk liegen. Die erste Verwaltungsfunktion findet und entfernt doppelte Titel.

## Starten

### Mit Setup installieren (empfohlen)

Die vollständige Installationsdatei liegt unter **`dist/Setup/RekordboxDatabaseManager-1.0.0-Setup-x64.exe`**. Zum Weitergeben reicht diese einzelne Datei. Sie enthält das Programm einschließlich Python, Qt, SQLCipher und aller weiteren Laufzeitbibliotheken; auf dem Zielrechner sind weder Python noch ein Internetzugang für die Installation erforderlich.

1. Die Setup-Datei auf einem Windows-PC mit 64 Bit öffnen (Windows 10 ab Version 1809 oder Windows 11).
2. Den Installationsordner wählen und bei Bedarf **Desktopverknüpfung erstellen** aktivieren. Die Installation erfolgt für den aktuellen Benutzer und benötigt keine Administratorrechte.
3. Das Programm über das Startmenü oder die Desktopverknüpfung starten.

Standardmäßig wird unter `%LOCALAPPDATA%\Programs\Rekordbox Database Manager` installiert. Eine spätere Setup-Version aktualisiert dieselbe Installation. Über **Installierte Apps** in den Windows-Einstellungen oder den Startmenüeintrag **Deinstallieren** lässt sich das Programm wieder entfernen. Rekordbox-Datenbanken, Musikdateien, Sicherungen, Änderungsprotokolle und die gespeicherten Programmeinstellungen werden dabei nicht entfernt. Die Setup-Datei ist nicht digital signiert.

### Ohne Installation starten

Die aktuelle Anwendung liegt unter `dist/RekordboxDatabaseManager-1.0.0/RekordboxDatabaseManager.exe`. Python ist dafür nicht erforderlich. Zum Weitergeben den **gesamten Versionsordner** kopieren, einschließlich `_internal`. Neue Builds erhalten einen eigenen Versionsordner, damit eine laufende ältere Instanz nicht überschrieben wird.

Version 1.0.0 führt den bisherigen Funktionsumfang aus Version 0.1.11 unter der neuen Hauptversionsnummer 1 weiter.

Version 0.1.11 erstellt bei Titeländerungen kein Datenbank-Backup mehr. Die Änderung wird direkt in einer Datenbanktransaktion gespeichert. Das Änderungsprotokoll und Sicherungen betroffener Analysedateien liegen unter `RekordboxManager-Protokolle`; die Datenbank und die Playlist-XML werden dabei nicht kopiert. Fehler können weiterhin innerhalb des laufenden Vorgangs zurückgerollt werden. Vor dem Entfernen von Duplikaten wird weiterhin ein Datenbank-Backup erstellt.

Version 0.1.10 beschleunigt Titeländerungen: Jeder Dateipfad wird pro Speichervorgang nur einmal aufgelöst. Die Referenzsuche liest zunächst nur IDs und Dateipfade; vollständige Metadaten werden nur für betroffene Einträge geladen. Anschließend werden die betroffenen Tracks direkt im geladenen Modell aktualisiert und die Duplikatgruppen neu berechnet. Backup, Integritätsprüfung und Schutz gegen fremde Datenbankänderungen bleiben erhalten. Eine zusätzliche Zustandsprüfung ermöglicht die schnelle Aktualisierung auch bei WAL-Datenbanken; bei einem veränderten oder nicht zuverlässig prüfbaren Stand wird vollständig neu geladen.

Version 0.1.9 ordnet die Hauptspalten als Gruppe, Entfernen, Cover, Titel, Interpret, Playlists, Bitrate und Hinzugefügt an. Mehrere Playlist-Zugehörigkeiten lassen sich direkt im Playlist-Feld als Dropdownliste öffnen. Ein Doppelklick auf den Titelnamen ermöglicht das Bearbeiten; Return speichert den Titel, benennt die Musikdatei nach „Interpret - Titel“ mit ihrer bisherigen Dateiendung um und aktualisiert die Dateiverknüpfungen einschließlich der Analysepfade. Vor der Änderung wird ein Backup erstellt. Nach dem Speichern werden die Duplikatgruppen neu berechnet und die Lösch-Auswahl zurückgesetzt.

Version 0.1.8 fasst Duplikatgruppen durch gemeinsame Hintergrundfarben zusammen. Vier dezente Farben wechseln sich nach Gruppennummer ab; die Zuordnung bleibt beim Sortieren, Filtern und Wechseln zwischen **Alle Titel** und **Doppelte Titel** erhalten. Die aktuell ausgewählte Zeile erscheint heller. Zum Entfernen markierte Zeilen bleiben vorrangig rot; nach dem Aufheben der Markierung erscheint wieder die Gruppenfarbe.

Version 0.1.7 verschiebt die zugehörigen Musikdateien bei jeder bestätigten Entfernung automatisch in den Windows-Papierkorb. Dafür gibt es keine zusätzliche Rückfrage oder Option mehr. Weiter verwendete Dateien und Hardlinks bleiben geschützt; bei Papierkorb-Fehlern wird weiterhin nicht dauerhaft gelöscht. Beim Start wird zuerst ein ausdrücklich übergebener oder der gespeicherte erreichbare Datenbankpfad verwendet. Andernfalls sucht die App über `masterDbDirectory` in den Rekordbox-Einstellungen nach der `master.db` und öffnet sie automatisch. Rekordbox 7 hat Vorrang vor Rekordbox 6, anschließend wird der Standardpfad geprüft. Auch **Datenbank öffnen** führt diese Suche vor einer manuellen Dateiauswahl aus. Ist die gefundene Sammlung bereits geöffnet, ermöglicht der Dialog die Auswahl einer anderen Datenbank.

Version 0.1.6 lädt beim Start automatisch die zuletzt erfolgreich geöffnete `master.db`. Ihr vollständiger Pfad wird dauerhaft gespeichert. Ist die Datei nicht erreichbar, etwa wegen eines getrennten externen Laufwerks, erscheint ein Hinweis und **Datenbank öffnen** bleibt verfügbar. Ein ausdrücklich beim Programmstart übergebener Pfad hat Vorrang. Die Spalte **Auswahl** steht direkt rechts neben **Entfernen**. Zum Löschen angekreuzte Kontrollkästchen, Zeilen und der Status **Entfernen** werden rot dargestellt, auch bei ausgewählter Zeile. Beim Entfernen werden alle betroffenen Playlist-Einträge durch den gewählten behaltenen Titel derselben Gruppe ersetzt; Positionen und wiederholte Einträge bleiben erhalten. Dies gilt auch für mehrere Playlists und für einen manuell gewählten Behalten-Titel, der vorher in keiner dieser Playlists enthalten war.

Version 0.1.5 empfiehlt immer das Exemplar mit der höchsten Bitrate. Bei gleicher Bitrate werden Titel bevorzugt, die in mindestens einer Playlist enthalten sind. Duplikate mit Playlist-Zugehörigkeit erscheinen mit rotem Titel und Dateinamen, auch in ausgewählten Zeilen und im Detailbereich. Beim Ankreuzen aller Exemplare einer Gruppe erscheint jedes Mal eine Warnung; eine Lösch-Markierung wird automatisch aufgehoben, sodass mindestens ein Exemplar erhalten bleibt. Zusätzlich wird die Auswahl vor der Entfernung geprüft. Ein Klick auf ein Cover in der Tabelle oder im Detailbereich spielt die Musikdatei ab der Mitte ihrer tatsächlichen Spieldauer ab. Ein erneuter Klick auf das Cover desselben Titels stoppt sie. Ein anderes Cover wechselt die Hörprobe; **Hörprobe stoppen** beendet sie auch nach einem Filterwechsel. Vor Datenbankvorgängen und beim Schließen wird die Wiedergabe beendet und die Datei freigegeben.

Version 0.1.4 erlaubt das Ankreuzen aller Exemplare einer Duplikatgruppe, einschließlich **Behalten · Tipp** und manuell gewählter Behalten-Titel. Beim Ankreuzen des Behalten-Titels wird automatisch das bestbewertete andere, nicht markierte Exemplar behalten. Sind alle anderen bereits markiert, wird das bestbewertete davon aus der Lösch-Auswahl genommen. So bleibt mindestens ein Exemplar pro Gruppe erhalten; Playlist-Verweise werden auf dieses Exemplar übertragen.

Version 0.1.3 zeigt Dateiname, Bitrate in kbit/s und die Namen aller zugehörigen Playlists direkt in der Tabelle unter **Alle Titel** und **Doppelte Titel**. Dateinamen ohne Playlist-Zugehörigkeit erscheinen grün, bei vorhandener Playlist in der Standardfarbe. Die vollständigen Playlist-Namen stehen auch im Tooltip und im Detailbereich. Mehrfache Einträge in derselben Playlist werden bei den Namen nur einmal aufgeführt; die Anzahl der Playlist-Einträge bleibt im Detailbereich sichtbar. Gelöschte Playlist-Verweise und gelöschte Playlists werden nicht berücksichtigt.

Version 0.1.2 zeigt die konkreten Gründe für übersprungene Dateien direkt im Ergebnis. Bereits fehlende/nicht erreichbare Dateien sowie weiterhin verwendete Musikdateien werden als Hinweise protokolliert. Sie lösen keine pauschale Fehlerwarnung mehr aus. Tatsächlich fehlgeschlagene Papierkorb-Aufrufe oder Protokollzugriffe bleiben Warnungen und werden ebenfalls direkt angezeigt. Zwei entfernte Datenbankeinträge können zu nur einer verschobenen Musikdatei gehören, etwa wenn eine Datei bereits fehlt oder mehrere Einträge dieselbe Datei verwenden.

Version 0.1.1 korrigiert eine falsche Fehlermeldung beim Papierkorb: Windows kann erfolgreiche Verschiebungen mit einem positiven HRESULT ungleich null bestätigen. Diese Statuswerte werden jetzt korrekt ausgewertet. Bei unklarem Ergebnis wird außerdem geprüft, ob die Datei am ursprünglichen Pfad überhaupt noch vorhanden ist; sie wird dann nicht pauschal als „erhalten“ gemeldet. Betroffene Dateien aus früheren Vorgängen können bereits im Windows-Papierkorb liegen.

Alternativ aus dem Quellcode:

1. Python 3.11 oder neuer in 64 Bit installieren.
2. Einmal `Installieren.cmd` ausführen (Internet für die Pakete erforderlich).
3. `Starten.cmd` öffnen.

Die Entwicklungsumgebung dieses Projekts ist bereits in `.venv` eingerichtet. Optional lässt sich ein Datenbankpfad direkt übergeben:

```powershell
.\.venv\Scripts\python.exe main.py "E:\PIONEER\Master\master.db"
```

## Bedienung

1. Beim Start wird eine erreichbare gespeicherte `master.db` automatisch geladen. Gibt es keinen erreichbaren gespeicherten Pfad, versucht die App zuerst, die Datenbank über die Rekordbox-Einstellungen zu finden und zu öffnen. Für eine manuelle Auswahl **Datenbank öffnen** verwenden; auch dort wird zuerst über die Rekordbox-Einstellungen gesucht. Der Pfad wird nach erfolgreichem Laden gespeichert. Eine externe Datenbank sollte mit ihrem vollständigen Verzeichnis einschließlich `share` und vorhandener `master.db-wal` verwendet werden.
2. **Alle Titel** zeigt die Sammlung mit Cover, Titel, Dateiname, Interpret, Hinzufügedatum, Bitrate und Playlist-Namen. Ist ein Track in mehreren Playlists enthalten, öffnet ein Klick auf sein Playlist-Feld eine Dropdownliste mit allen zugehörigen Playlists. Eine einzelne Playlist wird direkt angezeigt; ohne Zugehörigkeit steht dort **Keine Playlist**. Grüne Dateinamen kennzeichnen Titel ohne Playlist. Im Detailbereich stehen zusätzlich Dateipfad, Erreichbarkeit, Länge, Playlist-Einträge und Cue-Anzahl.
3. **Doppelte Titel** zeigt Gruppen mit gleicher Gruppennummer und gemeinsamer Hintergrundfarbe. Vier Farben wechseln sich zwischen den Gruppen ab und bleiben beim Sortieren und Filtern erhalten. Groß-/Kleinschreibung, Unicode-Schreibvarianten und überzählige Leerzeichen werden ignoriert. Satzzeichen sowie Mix-/Remix-Namen bleiben erhalten. Titel ohne Titel oder Interpret werden nicht gruppiert. Die Suche vergleicht Metadaten, keine Audio-Fingerabdrücke.
4. Die **Behalten-Empfehlung** bevorzugt die höchste Bitrate. Bei gleicher Bitrate werden Titel mit Playlist-Zugehörigkeit bevorzugt. Bei weiterem Gleichstand entscheiden Erreichbarkeit, Cue-Anzahl, früheres Hinzufügedatum und schließlich die Titel-ID. Auch eine aktuell nicht erreichbare Datei kann wegen ihrer höheren Bitrate empfohlen werden; die Erreichbarkeit im Detailbereich prüfen. Die Empfehlung beweist keine höhere Audioqualität. Playlist-Duplikate werden rot angezeigt. Zum Vergleichen auf das Cover klicken: Die Hörprobe beginnt in der Mitte der Aufnahme und stoppt beim erneuten Klick auf das Cover desselben Titels.
5. Bei Bedarf eine Zeile wählen und **Diesen Titel behalten** anklicken. Exemplare über die Kontrollkästchen unter **Entfernen** markieren. Die Spalte **Auswahl** zeigt **Behalten**, **Behalten · Tipp** oder **Entfernen**. Lösch-Markierungen und die zugehörigen Zeilen erscheinen rot. Auch der Behalten-Titel lässt sich ankreuzen; dann wird automatisch ein anderes Exemplar der Gruppe behalten. Sind dabei alle Exemplare markiert, erscheint eine Warnung und die Lösch-Markierung eines Exemplars wird aufgehoben. Mindestens ein Titel bleibt erhalten. **Vorschläge übernehmen** markiert die übrigen Exemplare der aktuell sichtbaren Gruppen. Es schreibt noch nichts in die Datenbank.
6. **Auswahl prüfen & entfernen** zeigt alle markierten Titel einschließlich Markierungen außerhalb des Suchfilters sowie die Anzahl der Musikdateien für den Papierkorb. Die Bestätigung startet Backup und Entfernung; die Musikdateien werden anschließend automatisch in den Papierkorb verschoben.

Die Tabelle zeigt die Spalten in dieser Reihenfolge: **Gruppe, Entfernen, Cover, Titel, Interpret, Playlists, Bitrate (kbit/s), Hinzugefügt**. Danach folgen **Auswahl** und **Dateiname**. Die Duplikatsuche zeigt bei einem Suchtreffer immer die gesamte zugehörige Gruppe. Spaltenköpfe sortieren die Liste. **Auswahl leeren** entfernt alle Markierungen.

### Titel bearbeiten

Ein **Doppelklick auf den Titelnamen** öffnet das Eingabefeld. **Return** speichert den Titel in der Datenbank und benennt die Musikdatei im bisherigen Ordner nach **Interpret - Titel.mp3** um. Bei anderen Audioformaten bleibt die ursprüngliche Dateiendung erhalten. **Escape**, Tab oder das Verlassen des Feldes verwirft die Eingabe.

Die App aktualisiert den Dateipfad, die vorhandenen Dateinamensfelder und passende lokale beziehungsweise ursprüngliche Pfadverweise in der Datenbank. Verwenden mehrere Datenbankeinträge dieselbe Datei, werden ihre Dateiverknüpfungen ebenfalls angepasst; der Titel wird nur beim bearbeiteten Eintrag geändert. Die Pfade in vorhandenen Rekordbox-Analysedateien werden ebenfalls aktualisiert; Cue-, Wellenform- und sonstige Analysedaten bleiben erhalten. Die Audioinhalte und eingebetteten Tags werden nicht verändert.

Titeländerungen werden **ohne Datenbank-Backup** gespeichert. Unter `RekordboxManager-Protokolle` werden der bisherige und neue Titel, die Dateipfade und Sicherungen der betroffenen Analysedateien protokolliert. Rekordbox und Rekordbox Agent müssen geschlossen sein. Eine fehlende Musik- oder zugehörige Analysedatei sowie ein bereits belegter Zieldateiname verhindern das Speichern. Für Windows ungültige Zeichen werden nur im Dateinamen durch Unterstriche ersetzt. Ein leerer oder zu langer Titel wird abgelehnt. Bei einem Fehler werden Datenbankänderungen zurückgerollt und bereits geänderte Dateinamen und Analysedateien wiederhergestellt; scheitert diese Wiederherstellung, meldet die App die betroffenen Pfade und den Protokollordner.

Nach erfolgreichem Speichern werden die betroffenen Einträge direkt im geladenen Modell aktualisiert und die Duplikatgruppen neu berechnet. Die bisherige Lösch-Auswahl wird zurückgesetzt. Nur bei einem veränderten oder nicht zuverlässig prüfbaren Datenbankstand wird die gesamte Sammlung neu geladen. Ein umbenannter Titel kann dadurch aus **Doppelte Titel** verschwinden; unter **Alle Titel** ist er weiterhin sichtbar, sofern er zum Suchfilter passt.

## Entfernung und Sicherungen

Vor jedem Schreibzugriff müssen Rekordbox und Rekordbox Agent geschlossen sein. Die App prüft dies sowie Änderungen an Datenbank, WAL und Playlist-XML seit dem Laden. Bei einer veränderten Sammlung muss die Auswahl nach dem Neuladen erneut geprüft werden.

Jede Entfernung erstellt neben der gewählten Datenbank einen Backup-Ordner:

```text
RekordboxManager-Backups/
  20261024T120000_123456Z/
    master.db
    masterPlaylists6.xml        (falls vorhanden)
    operation.json
```

Das Backup enthält einen konsistenten Stand einschließlich bereits geschriebener WAL-Änderungen. Eine verschlüsselte Quelldatenbank bleibt auch im Backup verschlüsselt. Das Protokoll enthält entfernte Titel, Ziel-IDs und gegebenenfalls Dateiergebnisse. Kann das Backup nicht erstellt werden, wird die Entfernung abgebrochen. Titeländerungen erstellen keine Datenbankkopie.

Playlist-Verweise werden auf das gewählte behaltene Exemplar umgestellt. Vorhandene Positionen und wiederholte Einträge bleiben bestehen. Cues und Analyse des behaltenen Titels werden nicht verändert. Die entfernten Exemplare samt ihren Cue- und weiteren Datenbankreferenzen werden entfernt; deren Cues werden **nicht zusammengeführt**. Gemeinsame Cover- und Analysedateien bleiben auf dem Datenträger.

Die App verschiebt die Musikdateien der entfernten Einträge immer automatisch **nach** der erfolgreichen Datenbankänderung in den Windows-Papierkorb, ohne gesonderte Papierkorb-Rückfrage. Dateien, die noch von anderen Titeln dieser geöffneten Sammlung verwendet werden, bleiben erhalten; dabei werden auch Hardlinks geprüft. Kann Windows eine Datei nicht in den Papierkorb verschieben, bleibt sie erhalten und wird im Ergebnis gemeldet. Es gibt keinen absichtlichen Fallback auf dauerhaftes Löschen. Andere Sammlungen, Geräte-Exporte und Programme werden nicht auf ihre Dateinutzung geprüft.

**Datenbank-Backups enthalten keine Musikdateien.** Entfernte Musikdateien bei Bedarf über den Windows-Papierkorb wiederherstellen. Beim Wiederherstellen eines Titeländerungs-Backups aus Version 0.1.9 oder 0.1.10 muss auch die Musikdatei gemäß `old_path`/`new_path` in `operation.json` zurückbenannt werden; die dort unter `files` aufgeführten Analysedateien aus den jeweils angegebenen Sicherungen wiederherstellen.

### Ein Backup wiederherstellen

1. Rekordbox, Rekordbox Agent und diese App schließen.
2. Den aktuellen Datenbankordner einschließlich vorhandener `master.db-wal`, `master.db-shm` und `masterPlaylists6.xml` separat sichern.
3. Die aktuelle `master.db` und zugehörige `-wal`/`-shm`-Dateien aus dem aktiven Ordner verschieben. WAL-Dateien eines anderen Datenbankstands dürfen nicht mit dem Backup kombiniert werden.
4. `master.db` aus dem gewünschten Backup in den ursprünglichen Ordner kopieren. Falls im Backup vorhanden, auch `masterPlaylists6.xml` zurückkopieren.
5. Sammlung zuerst in dieser App prüfen, anschließend in Rekordbox öffnen. Musikdateien gegebenenfalls separat wiederherstellen.

SQLite-Änderungen erfolgen in einer Transaktion. Bei normalen Fehlern wird zurückgerollt und eine bereits ersetzte Playlist-XML wiederhergestellt. Datenbank, Musikdatei und Analysedateien sind getrennte Dateien. Nach einem Stromausfall oder Prozessabbruch die Pfade und den Status in `operation.json` prüfen; Titeländerungen verfügen ab Version 0.1.11 über ein Änderungsprotokoll und gesicherte Analysedateien, aber keine Datenbankkopie. Ein Protokoll mit `prepared`, `database_committed` oder `recovery_required` statt `completed` beziehungsweise `rolled_back` weist auf einen möglicherweise unvollständigen Vorgang hin.

## Umfang und Prüfung

Ziel ist Rekordbox 7.2.18 mit einer frei wählbaren `master.db`. Die mitgelieferten lokalen Testdaten konnten entschlüsselt, samt Covern gelesen und in einer separaten Kopie bearbeitet werden. Sie enthalten vier Titel und keine Duplikatgruppen; Entfernungstests ergänzen deshalb künstliche Duplikate in isolierten Datenbanken. Die Original-Testdaten werden nicht verändert. Ein vollständiger Funktionstest durch erneutes Öffnen in Rekordbox 7.2.18 steht noch aus.

Die eigenständigen Geräte-Exportformate `export.pdb`, `exportLibrary.db`, XML-Import/Export sowie Cloud Library Sync sind nicht Bestandteil dieser Version. Pfade zu Musikdateien werden beim Löschen nicht automatisch auf andere Laufwerksbuchstaben umgebogen. Eine nicht erreichbare Datei wird entsprechend angezeigt.

## Entwicklung

Technik: Python, native Qt Widgets mit PySide6 Essentials und Addons (Qt Multimedia für Hörproben), SQLCipher und pyrekordbox. Datenbankarbeit läuft außerhalb des UI-Threads. Lesezugriffe erfolgen über `mode=ro`; Änderungen werden nur nach der Auswahlprüfung ausgeführt. Die Audiowiedergabe wartet auf Dateidauer und Seek-Bereitschaft, bevor sie auf die Mitte springt und startet; siehe [QMediaPlayer-Dokumentation](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html).

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm RekordboxManager.spec
```

Alternativ führt `Build.ps1` Installation, Tests und Build aus. `dist` und `build` sind generierte Dateien und werden nicht versioniert.

### Setup erstellen

Zusätzlich zu den Python-Build-Abhängigkeiten wird [Inno Setup 6 ab Version 6.3](https://jrsoftware.org/isdl.php) benötigt. Anschließend im Projektordner ausführen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build-Setup.ps1
```

Das Skript führt zunächst `Build.ps1` einschließlich Tests aus und verpackt anschließend den gesamten aktuellen EXE-Ordner mit `installer/RekordboxDatabaseManager.iss`. Version und Dateiname werden automatisch aus `rekordbox_manager.__version__` übernommen. Ausgabe: `dist/Setup/RekordboxDatabaseManager-<Version>-Setup-x64.exe` und eine zugehörige SHA-256-Prüfsummendatei.

Für einen bereits frisch erstellten und geprüften EXE-Ordner kann der Anwendungs-Build mit `-SkipBuild` übersprungen werden. Ein eigener Compilerpfad lässt sich mit `-IsccPath "C:\Pfad\ISCC.exe"` angeben. Das Skript findet Inno Setup auch im lokalen Werkzeugordner `.artifacts/tools/inno-setup`; dieser gehört nicht zur ausgelieferten Anwendung.

Die Tests prüfen unter anderem Metadatenabgleich, Behalten-Regeln, verschlüsselte WAL-Backups, Ersetzung in mehreren Playlists einschließlich unveränderter Positionen und Wiederholungen, Referenzbereinigung, Rollback bei Fehlern, Schutz weiterhin verwendeter Musikdateien, automatisches Recycling nach dem Datenbank-Commit sowie die Oberfläche einschließlich Hintergrundladen, gespeichertem Startpfad, Datenbanksuche über die Rekordbox-Einstellungen und roter Lösch-Auswahl.

Ein zusätzlicher Windows-Integrationstest nutzt nur eine künstliche Datei im Testverzeichnis und verschiebt diese tatsächlich in den System-Papierkorb. Er benötigt Zugriff auf den Windows-Papierkorb und wird ausschließlich auf ausdrücklichen Aufruf aktiviert:

```powershell
$env:RBM_TEST_WINDOWS_RECYCLE = '1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_recycle.py -k real_windows
Remove-Item Env:RBM_TEST_WINDOWS_RECYCLE
```

Ein Diagnoseaufruf liest nur die Datenbank und schreibt optional einen Bericht:

```powershell
.\.venv\Scripts\python.exe main.py --diagnose "E:\PIONEER\Master\master.db" --report diagnose.json
```

Formatgrundlagen und Bibliotheksverhalten: [pyrekordbox-Dokumentation](https://pyrekordbox.readthedocs.io/en/stable/), [Quellcode des Datenbankhandlers](https://github.com/dylanljones/pyrekordbox/tree/v0.5.0/pyrekordbox/masterdb). Der Windows-Papierkorb verwendet [IFileOperation](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags).
