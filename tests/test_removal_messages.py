from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from rekordbox_manager.database import RemovalResult
from rekordbox_manager.ui import removal_message


def test_missing_file_is_visible_as_information(qt_app):
    reason = r"Musikdatei bereits nicht vorhanden oder nicht erreichbar: C:\Music\Sentinel.mp3"
    result = RemovalResult(2, Path("backup"), (r"G:\Music\Sentinel.mp3",), (), (reason,))
    box = removal_message(result)
    assert box.icon() == QMessageBox.Icon.Information
    assert "2 Datenbankeinträge entfernt" in box.text()
    assert "1 Musikdatei(en)" in box.text()
    assert reason in box.informativeText()
    assert not box.detailedText()


@pytest.mark.parametrize("reason", ["Papierkorb fehlgeschlagen: Windows-Status 0x80070005",
                                    "Das Abschlussprotokoll konnte nicht gespeichert werden: Zugriff verweigert"])
def test_actual_failure_is_visible_without_expanding_details(qt_app, reason):
    box = removal_message(RemovalResult(2, Path("backup"), (), (reason,)))
    assert box.icon() == QMessageBox.Icon.Warning
    assert "Warnungen" in box.windowTitle()
    assert reason in box.informativeText()


def test_large_result_retains_all_messages_in_details(qt_app):
    notices = tuple(f"Nicht vorhandene Datei {number}" for number in range(5))
    box = removal_message(RemovalResult(5, Path("backup"), (), ("Papierkorb fehlgeschlagen",), notices))
    assert "Papierkorb fehlgeschlagen" in box.informativeText()
    assert "Nicht vorhandene Datei 0" in box.informativeText()
    assert "2 weitere Hinweise" in box.informativeText()
    assert all(notice in box.detailedText() for notice in notices)
