# Drittanbieter-Komponenten

Die Anwendung verwendet Python und Bibliotheken Dritter. Die im Build enthaltenen Paketmetadaten (`_internal/*.dist-info`) enthalten die jeweiligen Lizenzangaben und mitgelieferten Lizenztexte.

- **PySide6 / Qt for Python** und **Shiboken6**: LGPLv3/GPLv3 beziehungsweise kommerzielle Lizenz, abhängig von der Komponente. In dieser Anwendung werden dynamisch geladene Qt-Bibliotheken verwendet. Projekt und Quellcode: https://code.qt.io/pyside/pyside-setup.git/ und https://code.qt.io/qt/qtbase.git/. Lizenzinformationen: https://doc.qt.io/qtforpython-6/licenses.html.
- **Qt Multimedia / FFmpeg**: Audio-Hörproben verwenden Qt Multimedia aus PySide6 Addons. Je nach Qt-Backend werden dynamische FFmpeg-Bibliotheken mitgeliefert. Lizenzhinweise und Quellcode: https://doc.qt.io/qt-6/qtmultimedia-index.html, https://ffmpeg.org/legal.html und https://ffmpeg.org/download.html.
- **pyrekordbox**: MIT. https://github.com/dylanljones/pyrekordbox
- **SQLCipher / sqlcipher3-wheels**: BSD-artige Lizenzen; enthaltene Kryptografie-Bibliotheken haben eigene Lizenzbedingungen. https://github.com/coleifer/sqlcipher3 und https://github.com/zetetic/sqlcipher
- **Send2Trash**: BSD. https://github.com/arsenetar/send2trash
- **pywin32**: PSF-artige Lizenz. https://github.com/mhammond/pywin32
- **SQLAlchemy**, **bidict**: MIT.
- **NumPy**, **psutil**: BSD-artige Lizenzen; siehe zusätzlich mitgelieferte Hinweise für Binärkomponenten.
- **construct**: MIT.
- **python-dateutil**: Apache 2.0 / BSD-3-Clause.
- **Python**: Python Software Foundation License. https://docs.python.org/3/license.html

Der vollständige Quellcode dieser Anwendung und die Build-Konfiguration befinden sich im Projektordner. Der EXE-Ordner enthält austauschbare dynamische Qt-Bibliotheken unter `_internal/PySide6`; die Anwendung setzt keine technische Sperre gegen deren Austausch. Lokale Testdaten, Musikdateien und Coverbilder werden nicht mit der Anwendung ausgeliefert.
