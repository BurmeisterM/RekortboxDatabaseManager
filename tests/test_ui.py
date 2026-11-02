import time

import pytest

from PySide6.QtCore import QPoint, Qt, QThread
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFileDialog, QLineEdit, QMessageBox, QStyleOptionViewItem

from rekordbox_manager.database import load_library
from rekordbox_manager.domain import ManagerError, RemovalPlan, validate_plan
from rekordbox_manager.ui import MainWindow, RemovalDialog, Task, TrackModel, app_settings


@pytest.fixture(autouse=True)
def window_settings(qt_app, monkeypatch):
    monkeypatch.setattr("rekordbox_manager.ui.default_database", lambda: None)
    settings = app_settings()
    settings.clear()
    settings.sync()
    yield settings
    settings.clear()
    settings.sync()


def wait_for_window(window):
    deadline = time.monotonic() + 15
    while (window.startup_timer.isActive() or window.busy) and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not window.startup_timer.isActive() and not window.busy


def test_successfully_loaded_path_is_persisted_and_reopened_at_start(qt_app, collection, window_settings):
    path = collection[0]
    first = MainWindow()
    first.loaded(load_library(path))
    first.close()
    assert app_settings().value("last_database") == str(path)
    second = MainWindow()
    wait_for_window(second)
    assert second.library is not None and second.library.path == path
    assert len(second.library.tracks) == 3
    second.close()


@pytest.mark.parametrize("remembered", ["", "missing/master.db"])
def test_missing_remembered_database_leaves_manual_selection_available(qt_app, tmp_path, window_settings, monkeypatch, remembered):
    path = str(tmp_path / remembered) if remembered else ""
    window_settings.setValue("last_database", path)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window = MainWindow()
    wait_for_window(window)
    assert window.library is None and window.open_button.isEnabled()
    assert not warnings
    if path:
        assert "nicht erreichbar" in window.path_label.text()
        assert window.settings.value("last_database") == path
    window.close()


def test_explicit_startup_path_takes_priority_over_saved_path(qt_app, collection, tmp_path, window_settings):
    window_settings.setValue("last_database", str(tmp_path / "wrong.db"))
    window = MainWindow(str(collection[0]))
    wait_for_window(window)
    assert window.library is not None and window.library.path == collection[0]
    assert window.settings.value("last_database") == str(collection[0])
    window.close()


def test_invalid_remembered_database_reports_failure_without_replacing_settings(qt_app, tmp_path, window_settings, monkeypatch):
    path = tmp_path / "master.db"
    path.write_bytes(b"invalid database")
    window_settings.setValue("last_database", str(path))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window = MainWindow()
    wait_for_window(window)
    assert warnings and window.library is None
    assert window.settings.value("last_database") == str(path)
    assert window.open_button.isEnabled()
    window.close()


def test_delete_selection_is_red_and_columns_follow_requested_order(qt_app, collection, tmp_path):
    path, conn = collection
    conn.execute("DELETE FROM djmdSongPlaylist WHERE ContentID='copy'")
    conn.commit()
    window = MainWindow()
    window.loaded(load_library(path))
    header = window.table.horizontalHeader()
    visible_headers = [window.model.HEADERS[header.logicalIndex(i)]
                       for i in range(header.count())
                       if not window.table.isColumnHidden(header.logicalIndex(i))]
    assert visible_headers == ["Gruppe", "Entfernen", "Cover", "Titel", "Interpret",
                               "Playlists", "Bitrate (kbit/s)", "Hinzugefügt", "Auswahl", "Dateiname"]
    window.model.apply_recommendations()
    row = next(i for i, track in enumerate(window.model.rows) if track.id == "copy")
    for col in range(window.model.columnCount()):
        index = window.model.index(row, col)
        assert index.data(Qt.ItemDataRole.ForegroundRole) == QColor("#ef8f93")
        assert index.data(Qt.ItemDataRole.BackgroundRole) == QColor("#3b2029")
        option = QStyleOptionViewItem()
        window.table.itemDelegate().initStyleOption(option, index)
        assert option.palette.color(QPalette.ColorRole.HighlightedText) == QColor("#ef8f93")
        assert option.palette.color(QPalette.ColorRole.Highlight) == QColor("#3b2029")
    assert window.model.index(row, 9).data() == "Entfernen"
    window.show()
    window.table.setCurrentIndex(window.model.index(row, 2))
    window.table.scrollTo(window.model.index(row, 9))
    QTest.qWait(30)
    assert window.grab().save(str(tmp_path / "delete-selection.png"))
    state_cell = window.table.visualRect(window.model.index(row, 9))
    pixel = QPoint(state_cell.right() - 10, state_cell.center().y())
    assert window.table.viewport().grab().toImage().pixelColor(pixel) == QColor("#3b2029")
    window.model.clear_selection()
    assert window.model.index(row, 11).data(Qt.ItemDataRole.ForegroundRole) == QColor("#8aefce")
    keeper_row = next(i for i, track in enumerate(window.model.rows) if window.model.is_keeper(track))
    assert window.model.index(row, 2).data(Qt.ItemDataRole.BackgroundRole) == window.model.index(keeper_row, 2).data(Qt.ItemDataRole.BackgroundRole)
    window.close()


def test_filename_color_playlist_names_bitrate_and_detail_reset(qt_app, collection):
    window = MainWindow()
    window.loaded(load_library(collection[0]))
    window.model.duplicates_only = False
    window.model.refresh()
    columns = {name: i for i, name in enumerate(window.model.HEADERS)}
    filename_col = columns["Dateiname"]
    playlist_col = columns["Playlists"]
    bitrate_col = columns["Bitrate (kbit/s)"]
    assert not window.table.isColumnHidden(filename_col)
    assert not window.table.isColumnHidden(playlist_col)
    assert not window.table.isColumnHidden(bitrate_col)
    for track_id, playlist, color in [("remix", "Keine Playlist", QColor("#8aefce")),
                                       ("original", "Playlist 10", QColor("#ef8f93"))]:
        row = next(i for i, t in enumerate(window.model.rows) if t.id == track_id)
        filename_index = window.model.index(row, filename_col)
        assert filename_index.data() == f"{track_id}.mp3"
        assert filename_index.data(Qt.ItemDataRole.ForegroundRole) == color
        assert window.model.index(row, playlist_col).data() == playlist
        assert playlist in window.model.index(row, playlist_col).data(Qt.ItemDataRole.ToolTipRole)
        assert window.model.index(row, bitrate_col).data() == "320"
        window.table.setCurrentIndex(filename_index)
        assert window.detail_filename.text() == f"{track_id}.mp3"
        assert bool(window.detail_filename.styleSheet()) == (color is not None)
        assert playlist in window.detail_playlists.text()
        assert "320 kbit/s" in window.detail_meta.text()
    window.reset_details()
    assert not window.detail_filename.text()
    assert not window.detail_filename.styleSheet()
    assert not window.detail_playlists.text()
    window.close()


@pytest.mark.parametrize("duplicates_only", [True, False])
def test_multiple_playlists_open_read_only_dropdown(qt_app, collection, duplicates_only):
    path, conn = collection
    conn.execute("ALTER TABLE djmdPlaylist ADD COLUMN Name TEXT")
    conn.execute("UPDATE djmdPlaylist SET Name='Warmup' WHERE ID='10'")
    conn.execute("INSERT INTO djmdPlaylist (ID, Name) VALUES ('20', 'Club')")
    conn.executemany(
        "INSERT INTO djmdSongPlaylist (ID,PlaylistID,ContentID,TrackNo) VALUES (?,?,?,?)",
        [("p3", "20", "copy", 1), ("p4", "10", "copy", 3), ("p5", "10", "original", 4)])
    conn.commit()
    memberships = conn.execute("SELECT * FROM djmdSongPlaylist ORDER BY ID").fetchall()
    window = MainWindow()
    window.loaded(load_library(path))
    window.set_view(duplicates_only)
    window.show()
    QTest.qWait(30)
    column = window.model.HEADERS.index("Playlists")

    def playlist_index(track_id):
        row = next(i for i, track in enumerate(window.model.rows) if track.id == track_id)
        return window.model.index(row, column)

    def open_dropdown():
        index = playlist_index("copy")
        window.table.scrollTo(index)
        QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton,
                        pos=window.table.visualRect(index).center())
        QTest.qWait(20)
        editors = [editor for editor in window.table.findChildren(QComboBox) if editor.isVisible()]
        assert len(editors) == 1
        editor = editors[0]
        assert editor.view().isVisible()
        assert [editor.itemText(i) for i in range(editor.count())] == ["Club", "Warmup"]
        return editor

    assert not window.model.flags(playlist_index("original")) & Qt.ItemFlag.ItemIsEditable
    assert playlist_index("original").data() == "Warmup"
    if not duplicates_only:
        assert playlist_index("remix").data() == "Keine Playlist"
        assert not window.model.flags(playlist_index("remix")) & Qt.ItemFlag.ItemIsEditable
    editor = open_dropdown()
    QTest.keyClick(editor, Qt.Key.Key_Down)
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QTest.qWait(20)
    assert not window.model.selected
    assert playlist_index("copy").data() == "Club; Warmup"
    assert window.detail_playlists.text() == "Playlists:\nClub\nWarmup"
    assert conn.execute("SELECT * FROM djmdSongPlaylist ORDER BY ID").fetchall() == memberships

    window.model.sort(window.model.HEADERS.index("Titel"), Qt.SortOrder.DescendingOrder)
    open_dropdown()
    window.filter_rows("no matching track")
    QTest.qWait(20)
    assert window.model.rowCount() == 0
    assert not any(editor.isVisible() for editor in window.table.findChildren(QComboBox))
    window.close()


def edit_title(window, track_id):
    row = next(i for i, track in enumerate(window.model.rows) if track.id == track_id)
    index = window.model.index(row, 2)
    window.table.scrollTo(index)
    position = window.table.visualRect(index).center()
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert not any(editor.isVisible() for editor in window.table.findChildren(QLineEdit))
    QTest.mouseDClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.qWait(20)
    editors = [editor for editor in window.table.findChildren(QLineEdit) if editor.isVisible()]
    assert len(editors) == 1
    return editors[0]


@pytest.mark.parametrize("duplicates_only", [True, False])
def test_double_click_title_and_return_save_database_and_rename_audio(qt_app, collection, monkeypatch, duplicates_only):
    path, _ = collection
    window = MainWindow()
    window.loaded(load_library(path))
    window.set_view(duplicates_only)
    window.model.apply_recommendations()
    assert window.model.selected
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr("rekordbox_manager.ui.load_library",
                        lambda path: pytest.fail("A stable title change must not reload the whole library"))
    window.show()
    QTest.qWait(30)
    editor = edit_title(window, "copy")
    assert editor.text() == window.library.by_id["copy"].title
    editor.setText("Neuer Titel")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    wait_for_window(window)
    assert not warnings
    assert window.library.by_id["copy"].title == "Neuer Titel"
    assert load_library(path).by_id["copy"].title == "Neuer Titel"
    assert (path.parent / "Crown (ARG) - Neuer Titel.mp3").is_file()
    assert not (path.parent / "copy.mp3").exists()
    assert not window.library.groups and not window.model.selected
    assert window.last_backup is None
    assert not path.with_name("RekordboxManager-Backups").exists()
    assert "Titel gespeichert" in window.status_label.text()
    if not duplicates_only:
        assert window.current_track().id == "copy"
        assert window.detail_title.text() == "Neuer Titel"
        assert window.detail_filename.text() == "Crown (ARG) - Neuer Titel.mp3"
    else:
        assert window.model.rowCount() == 0
    window.close()


@pytest.mark.parametrize("cancel", ["escape", "tab", "focus"])
def test_title_edit_without_return_does_not_save(qt_app, collection, cancel):
    path, _ = collection
    window = MainWindow()
    window.loaded(load_library(path))
    before = window.library.by_id["copy"]
    window.show()
    QTest.qWait(30)
    editor = edit_title(window, "copy")
    editor.setText("Unsaved title")
    if cancel == "focus":
        QTest.mouseClick(window.search, Qt.MouseButton.LeftButton)
    else:
        QTest.keyClick(editor, Qt.Key.Key_Escape if cancel == "escape" else Qt.Key.Key_Tab)
    QTest.qWait(30)
    assert not window.busy
    assert load_library(path).by_id["copy"] == before
    assert not any(editor.isVisible() for editor in window.table.findChildren(QLineEdit))
    assert not path.with_name("RekordboxManager-Backups").exists()
    window.close()


def test_title_save_failure_keeps_old_title_and_reports_error(qt_app, collection, monkeypatch):
    path, _ = collection
    destination = path.parent / "Crown (ARG) - New.mp3"
    destination.write_bytes(b"existing recording")
    window = MainWindow()
    window.loaded(load_library(path))
    before = window.library.by_id["copy"]
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.show()
    QTest.qWait(30)
    editor = edit_title(window, "copy")
    editor.setText("New")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    wait_for_window(window)
    assert warnings and "bereits vorhanden" in warnings[0][2]
    assert window.library.by_id["copy"] == before
    assert load_library(path).by_id["copy"] == before
    assert (path.parent / "copy.mp3").is_file()
    assert destination.read_bytes() == b"existing recording"
    window.close()


def test_reload_failure_after_title_save_reports_committed_change(qt_app, collection, monkeypatch):
    path, _ = collection
    window = MainWindow()
    window.loaded(load_library(path))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    def failed_reload(path):
        raise ManagerError("simulated reload failure")

    def no_incremental_snapshot(*args):
        raise OSError("simulated incremental refresh failure")

    monkeypatch.setattr("rekordbox_manager.database._library_after_rename", no_incremental_snapshot)
    monkeypatch.setattr("rekordbox_manager.ui.load_library", failed_reload)
    window.show()
    QTest.qWait(30)
    editor = edit_title(window, "copy")
    editor.setText("New")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    wait_for_window(window)
    assert load_library(path).by_id["copy"].title == "New"
    assert (path.parent / "Crown (ARG) - New.mp3").is_file()
    assert warnings and "wurden gespeichert" in warnings[0][2]
    assert "Titel gespeichert" in window.status_label.text()
    assert window.library is None and window.model.rowCount() == 0
    assert window.open_button.isEnabled() and not window.remove_button.isEnabled()
    window.close()


def test_new_columns_sort_and_unknown_bitrate_is_shown_as_missing(qt_app, collection):
    path, conn = collection
    conn.execute("UPDATE djmdContent SET BitRate=96 WHERE ID='copy'")
    conn.execute("UPDATE djmdContent SET BitRate=NULL WHERE ID='remix'")
    conn.commit()
    model = TrackModel()
    model.duplicates_only = False
    model.set_library(load_library(path))
    model.sort(model.HEADERS.index("Bitrate (kbit/s)"))
    assert [t.id for t in model.rows] == ["remix", "copy", "original"]
    assert model.index(0, model.HEADERS.index("Bitrate (kbit/s)")).data() == "–"
    model.sort(model.HEADERS.index("Dateiname"))
    assert [t.id for t in model.rows] == ["copy", "original", "remix"]
    model.sort(model.HEADERS.index("Playlists"))
    assert model.rows[0].id == "remix"


def test_keeper_is_checkable_and_filter_keeps_complete_group(qt_app, collection):
    library = load_library(collection[0])
    model = TrackModel()
    model.set_library(library)
    assert model.rowCount() == 2
    keeper = library.groups[0].recommended_id
    index = next(model.index(i, 0) for i, t in enumerate(model.rows) if t.id == keeper)
    assert model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert keeper in model.selected
    assert not model.is_keeper(library.by_id[keeper])
    validate_plan(library, model.plan())
    model.search = "copy.mp3"
    model.refresh()
    assert model.rowCount() == 2
    model.apply_recommendations()
    assert len(model.selected) == 1
    plan = model.plan()
    assert keeper not in plan.replacements
    model.keep(library.by_id["copy"])
    assert "copy" not in model.selected
    assert model.keepers[library.by_id["copy"].duplicate_key] == "copy"


@pytest.mark.parametrize("apply_recommendations", [False, True])
def test_checking_keeper_switches_retained_track_and_keeps_plan_valid(qt_app, collection, apply_recommendations):
    library = load_library(collection[0])
    model = TrackModel()
    model.set_library(library)
    if apply_recommendations:
        model.apply_recommendations()
    changed_rows = []
    model.dataChanged.connect(lambda first, last: changed_rows.append(first.row()))
    for removed, retained in [("original", "copy"), ("copy", "original")]:
        row = next(i for i, t in enumerate(model.rows) if t.id == removed)
        assert model.setData(model.index(row, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
        assert model.selected == {removed}
        assert model.plan().replacements == {removed: retained}
        validate_plan(library, model.plan())
        retained_row = next(i for i, t in enumerate(model.rows) if t.id == retained)
        assert model.index(retained_row, 0).data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
        assert row in changed_rows and retained_row in changed_rows
    model.keep(library.by_id["copy"])
    copy_row = next(i for i, t in enumerate(model.rows) if t.id == "copy")
    assert model.setData(model.index(copy_row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.plan().replacements == {"copy": "original"}


def test_checking_keeper_prefers_an_unselected_alternative(qt_app, collection):
    path, conn = collection
    conn.execute("UPDATE djmdContent SET Title='Searching Memory' WHERE ID='remix'")
    conn.commit()
    library = load_library(path)
    model = TrackModel()
    model.set_library(library)
    for track_id in ("copy", "original"):
        row = next(i for i, t in enumerate(model.rows) if t.id == track_id)
        assert model.setData(model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert model.selected == {"copy", "original"}
    assert model.plan().replacements == {"copy": "remix", "original": "remix"}
    validate_plan(library, model.plan())


def test_checkbox_changes_removal_plan(qt_app, collection):
    library = load_library(collection[0])
    model = TrackModel()
    model.set_library(library)
    other = next(t for t in model.rows if not model.is_keeper(t))
    row = next(i for i, t in enumerate(model.rows) if t.id == other.id)
    assert model.setData(model.index(row, 0), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert other.id in model.plan().replacements
    assert model.setData(model.index(row, 0), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert not model.selected


def test_review_dialog_shows_automatic_recycling_without_an_option(qt_app, collection):
    library = load_library(collection[0])
    dialog = RemovalDialog(library, RemovalPlan({"copy": "original"}))
    assert not dialog.findChildren(QCheckBox)
    dialog.candidates = [collection[0].parent / "copy.mp3"]
    dialog.update_files()
    assert "1 Musikdatei(en) werden automatisch" in dialog.file_info.text()
    assert "copy.mp3" in dialog.file_info.toolTip()
    assert dialog.review_model.rowCount() == 1
    dialog.close()


def test_window_loads_in_background_and_renders(qt_app, collection, tmp_path):
    window = MainWindow()
    failures = []
    callback_threads = []
    original_loaded = window.loaded

    def loaded(result):
        callback_threads.append(QThread.currentThread())
        original_loaded(result)

    window.loaded = loaded
    window.task_failed = failures.append
    window.open_database(str(collection[0]))
    deadline = time.monotonic() + 45
    while window.busy and time.monotonic() < deadline and not failures:
        QTest.qWait(20)
    assert not failures
    assert not window.busy
    assert callback_threads == [qt_app.thread()]
    assert window.library and window.model.rowCount() == 2
    window.show()
    QTest.qWait(30)
    assert window.grab().save(str(tmp_path / "window.png"))
    window.model.apply_recommendations()
    assert window.remove_button.isEnabled()
    # A real click must toggle the checkbox even with editor widgets disabled.
    row = next(i for i, t in enumerate(window.model.rows) if not window.model.is_keeper(t))
    index = window.model.index(row, 0)
    window.table.scrollTo(index)
    rectangle = window.table.visualRect(index)
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton,
                     pos=rectangle.topLeft() + QPoint(12, rectangle.height() // 2))
    assert not window.model.selected
    window.model.apply_recommendations()
    window.table.setCurrentIndex(window.model.index(0, 2))
    QTest.qWait(50)
    assert window.detail_title.y() >= window.detail_cover.y() + window.detail_cover.height()
    window.search.setText("nothing matches")
    assert "außerhalb" in window.summary.text()
    assert window.remove_button.isEnabled()
    window.close()


def test_complete_ui_removal_refreshes_collection(qt_app, collection, monkeypatch):
    window = MainWindow()
    window.loaded(load_library(collection[0]))
    failures = []
    monkeypatch.setattr(window, "task_failed", failures.append)
    monkeypatch.setattr(RemovalDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.model.apply_recommendations()
    assert len(window.model.selected) == 1
    window.show()
    QTest.qWait(30)
    row = next(i for i, t in enumerate(window.model.rows) if window.model.is_keeper(t))
    index = window.model.index(row, 0)
    window.table.scrollTo(index)
    rectangle = window.table.visualRect(index)
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton,
                     pos=rectangle.topLeft() + QPoint(12, rectangle.height() // 2))
    assert window.model.plan().replacements == {"original": "copy"}
    assert len(warnings) == 1
    assert "Alle Titel" in warnings[0][2]
    window.review_removal()
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        QTest.qWait(20)
        if failures or (not window.busy and window.library and len(window.library.tracks) == 2):
            break
    assert not failures
    assert not window.busy
    assert len(window.library.tracks) == 2
    assert "original" not in window.library.by_id
    assert window.library.by_id["copy"].playlists == 2
    assert not window.model.selected
    assert not window.remove_button.isEnabled()
    assert window.last_backup and (window.last_backup / "master.db").is_file()
    assert (collection[0].parent / "copy.mp3").is_file()
    assert not (collection[0].parent / "original.mp3").is_file()
    window.close()


@pytest.mark.parametrize("remembered", ["", "missing.db"])
def test_startup_discovers_rekordbox_database_before_manual_selection(qt_app, collection, window_settings, monkeypatch, remembered):
    window_settings.setValue("last_database", str(collection[0].parent / remembered) if remembered else "")
    monkeypatch.setattr("rekordbox_manager.ui.default_database", lambda: collection[0])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: pytest.fail("Discovery must precede a file dialog"))
    window = MainWindow()
    wait_for_window(window)
    assert window.library is not None and window.library.path == collection[0]
    assert window.settings.value("last_database") == str(collection[0])
    window.close()


def test_open_button_uses_discovered_database_and_still_allows_other_paths(qt_app, collection, monkeypatch):
    monkeypatch.setattr("rekordbox_manager.ui.default_database", lambda: collection[0])
    dialogs = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: dialogs.append(args) or ("", ""))
    window = MainWindow()
    window.choose_database()
    wait_for_window(window)
    assert window.library is not None and window.library.path == collection[0]
    assert not dialogs
    # Once the discovered collection is loaded, the same button permits another file.
    window.choose_database()
    wait_for_window(window)
    assert len(dialogs) == 1 and dialogs[0][2] == str(collection[0])
    window.close()


def test_file_dialog_is_only_shown_after_unsuccessful_discovery(qt_app, monkeypatch):
    events = []
    monkeypatch.setattr("rekordbox_manager.ui.default_database", lambda: events.append("settings") or None)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: events.append("dialog") or ("", ""))
    window = MainWindow()
    window.choose_database()
    wait_for_window(window)
    assert events == ["settings", "dialog"]
    window.close()


def test_unusable_discovered_database_falls_back_to_file_dialog(qt_app, tmp_path, monkeypatch):
    path = tmp_path / "master.db"
    path.write_bytes(b"invalid database")
    monkeypatch.setattr("rekordbox_manager.ui.default_database", lambda: path)
    dialogs = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: dialogs.append(args) or ("", ""))
    window = MainWindow()
    window.choose_database()
    wait_for_window(window)
    assert len(dialogs) == 1
    assert window.library is None and window.open_button.isEnabled()
    window.close()


def test_every_attempt_to_select_the_whole_group_warns_even_when_filtered(qt_app, collection):
    library = load_library(collection[0])
    model = TrackModel()
    model.set_library(library)
    model.search = "copy.mp3"
    model.refresh()
    warnings = []
    model.safety_warning.connect(warnings.append)
    model.apply_recommendations()
    for _ in range(3):
        keeper = next(t for t in model.rows if model.is_keeper(t))
        row = model.rows.index(keeper)
        model.setData(model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
        validate_plan(library, model.plan())
        assert len(model.selected) == 1
    assert len(warnings) == 3
    assert all("Alle Titel" in warning for warning in warnings)


def test_invalid_full_group_selection_is_blocked_before_review(qt_app, collection, monkeypatch):
    window = MainWindow()
    window.loaded(load_library(collection[0]))
    window.model.selected = {"original", "copy"}
    window.search.setText("no matches")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.review_removal()
    assert len(warnings) == 1
    assert "mindestens ein Titel" in warnings[0][2]
    assert not window.busy
    with pytest.raises(ManagerError):
        RemovalDialog(window.library, RemovalPlan({"copy": "original", "original": "copy"}))
    window.close()


def test_playlist_duplicates_stay_red_in_selection_and_detail(qt_app, collection):
    window = MainWindow()
    window.loaded(load_library(collection[0]))
    row = next(i for i, t in enumerate(window.model.rows) if t.id == "original")
    index = window.model.index(row, 2)
    assert index.data(Qt.ItemDataRole.ForegroundRole) == QColor("#ef8f93")
    option = QStyleOptionViewItem()
    window.table.itemDelegate().initStyleOption(option, index)
    assert option.palette.color(QPalette.ColorRole.HighlightedText) == QColor("#ef8f93")
    window.table.setCurrentIndex(index)
    assert "#ef8f93" in window.detail_title.styleSheet()
    window.set_view(False)
    row = next(i for i, t in enumerate(window.model.rows) if t.id == "remix")
    assert window.model.index(row, 2).data(Qt.ItemDataRole.ForegroundRole) is None
    window.table.setCurrentIndex(window.model.index(row, 2))
    assert not window.detail_title.styleSheet()
    window.close()


def test_both_cover_clicks_toggle_preview_and_other_cells_do_not(qt_app, collection, monkeypatch):
    window = MainWindow()
    window.loaded(load_library(collection[0]))
    toggled = []
    monkeypatch.setattr(window.preview, "toggle", lambda track: toggled.append(track.id))
    window.show()
    QTest.qWait(30)
    row = next(i for i, t in enumerate(window.model.rows) if t.id == "original")
    for column in (2, 1, 1):
        index = window.model.index(row, column)
        window.table.scrollTo(index)
        QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton,
                        pos=window.table.visualRect(index).center())
    QTest.mouseClick(window.detail_cover, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.detail_cover, Qt.MouseButton.LeftButton)
    assert toggled == ["original"] * 4
    window.close()


def test_unexpected_worker_error_is_reported_without_a_console(qt_app, monkeypatch):
    import sys
    failures = []

    def unexpected():
        raise RuntimeError("simulated background failure")

    task = Task(unexpected)
    task.signals.failed.connect(failures.append)
    monkeypatch.setattr(sys, "stderr", None)
    task.run()
    assert len(failures) == 1
    assert "simulated background failure" in failures[0]
