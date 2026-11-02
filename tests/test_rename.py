from contextlib import closing
from collections import Counter
import json
from pathlib import Path
import shutil
import struct

import pytest

from rekordbox_manager import database as db
from rekordbox_manager.domain import ManagerError


def add_path_columns(conn):
    for column in ("FileNameL", "FileNameS", "OrgFolderPath", "rb_LocalFolderPath", "AnalysisDataPath"):
        conn.execute(f'ALTER TABLE djmdContent ADD COLUMN "{column}" TEXT')
    conn.execute("UPDATE djmdContent SET FileNameL=ID || '.mp3', FileNameS='OLD~1.MP3', "
                 "OrgFolderPath=FolderPath, rb_LocalFolderPath=FolderPath")
    conn.commit()


def analysis_bytes(path):
    encoded = path.encode("utf-16-be") + b"\x00\x00"
    tag = b"PPTH" + struct.pack(">III", 16, 16 + len(encoded), len(encoded)) + encoded
    unknown = b"ZZZZ" + struct.pack(">II", 12, 20) + b"preserve"
    return b"PMAI" + struct.pack(">IIIIII", 28, 28 + len(tag) + len(unknown), 0, 0, 0, 0) + tag + unknown


def test_title_rename_updates_paths_without_database_backup(collection, monkeypatch):
    path, conn = collection
    add_path_columns(conn)
    library = db.load_library(path)
    source = Path(library.by_id["copy"].path)
    original_audio = source.read_bytes()
    playlists = conn.execute("SELECT * FROM djmdSongPlaylist").fetchall()
    cues = conn.execute("SELECT * FROM djmdCue").fetchall()
    monkeypatch.setattr(db, "backup_database", lambda *args: pytest.fail("Title changes must not back up the database"))
    result = db.rename_track(library, "copy", "Neuer Titel")
    destination = source.with_name("Crown (ARG) - Neuer Titel.mp3")
    assert result.path == destination and result.title == "Neuer Titel"
    assert not source.exists() and destination.read_bytes() == original_audio
    after = db.load_library(path)
    assert after.by_id["copy"].title == "Neuer Titel"
    assert Path(after.by_id["copy"].path) == destination
    assert not after.groups
    row = dict(zip([item[1] for item in conn.execute("PRAGMA table_info(djmdContent)")],
                   conn.execute("SELECT * FROM djmdContent WHERE ID='copy'").fetchone()))
    assert row["FileNameL"] == destination.name
    assert row["FileNameS"] == ""
    assert row["FolderPath"] == row["OrgFolderPath"] == row["rb_LocalFolderPath"] == destination.as_posix()
    assert row["rb_local_usn"] > 10 and row["updated_at"]
    assert conn.execute("SELECT int_1 FROM agentRegistry").fetchone()[0] > 10
    assert conn.execute("SELECT * FROM djmdSongPlaylist").fetchall() == playlists
    assert conn.execute("SELECT * FROM djmdCue").fetchall() == cues
    assert not path.with_name("RekordboxManager-Backups").exists()
    assert not list(result.journal.rglob("*.db"))
    assert not (result.journal / "masterPlaylists6.xml").exists()
    manifest = json.loads((result.journal / "operation.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed" and manifest["operation"] == "rename_track"
    assert manifest["old_path"] == str(source) and manifest["new_path"] == str(destination)


@pytest.mark.parametrize("extension", [".mp3", ".flac", ".wav"])
def test_filename_sanitizes_windows_characters_and_keeps_audio_format(collection, extension):
    path, conn = collection
    source = path.parent / f"audio{extension}"
    (path.parent / "copy.mp3").rename(source)
    conn.execute("UPDATE djmdContent SET FolderPath=? WHERE ID='copy'", (str(source),))
    conn.commit()
    result = db.rename_track(db.load_library(path), "copy", 'Mix: A/B? "Live"')
    assert result.path.name == f"Crown (ARG) - Mix_ A_B_ _Live_{extension}"
    assert db.load_library(path).by_id["copy"].title == 'Mix: A/B? "Live"'


def test_shared_audio_path_updates_every_reference_without_changing_other_titles(collection):
    path, conn = collection
    add_path_columns(conn)
    source = path.parent / "copy.mp3"
    conn.execute("UPDATE djmdContent SET FolderPath=?, OrgFolderPath=?, rb_LocalFolderPath=? WHERE ID='original'",
                 (str(source), str(source), str(source)))
    conn.commit()
    result = db.rename_track(db.load_library(path), "copy", "Edited")
    after = db.load_library(path)
    assert Path(after.by_id["original"].path) == result.path
    assert after.by_id["original"].title == "Searching Memory"
    assert after.by_id["original"].available and after.by_id["copy"].available


@pytest.mark.parametrize("old_style", ["full", "filename"])
def test_analysis_paths_are_updated_and_other_tags_are_preserved(collection, old_style):
    path, conn = collection
    add_path_columns(conn)
    relative = "PIONEER/USBANLZ/test/ANLZ0000.DAT"
    analysis = path.parent / "share" / relative
    analysis.parent.mkdir(parents=True)
    old = "?/copy.mp3" if old_style == "filename" else (path.parent / "copy.mp3").as_posix()
    original = analysis_bytes(old)
    analysis.write_bytes(original)
    conn.execute("UPDATE djmdContent SET AnalysisDataPath=? WHERE ID='copy'", ("/" + relative,))
    conn.commit()
    result = db.rename_track(db.load_library(path), "copy", "Neuer Titel")
    from pyrekordbox.anlz import AnlzFile
    expected = "?/" + result.path.name if old_style == "filename" else result.path.as_posix()
    assert AnlzFile.parse(analysis.read_bytes()).get("path") == expected
    assert analysis.read_bytes()[-20:] == original[-20:]
    assert (result.journal / "analysis-0-ANLZ0000.DAT").read_bytes() == original


@pytest.mark.parametrize("title", ["", "   ", "Line\nBreak", "x" * 256])
def test_invalid_titles_do_not_change_database_or_file(collection, title):
    path, _ = collection
    library = db.load_library(path)
    with pytest.raises(ManagerError):
        db.rename_track(library, "copy", title)
    assert db.load_library(path).by_id["copy"] == library.by_id["copy"]
    assert (path.parent / "copy.mp3").exists()
    assert not path.with_name("RekordboxManager-Backups").exists()


def test_existing_destination_is_never_overwritten(collection):
    path, _ = collection
    library = db.load_library(path)
    destination = path.parent / "Crown (ARG) - New.mp3"
    destination.write_bytes(b"another recording")
    with pytest.raises(ManagerError, match="bereits vorhanden"):
        db.rename_track(library, "copy", "New")
    assert destination.read_bytes() == b"another recording"
    assert (path.parent / "copy.mp3").exists()
    assert db.load_library(path).by_id["copy"].title == library.by_id["copy"].title


@pytest.mark.parametrize("block", ["missing_audio", "stale_database", "rekordbox_running"])
def test_missing_audio_stale_database_and_running_rekordbox_prevent_changes(collection, monkeypatch, block):
    path, conn = collection
    library = db.load_library(path)
    if block == "missing_audio":
        (path.parent / "copy.mp3").unlink()  # Only the fixture's synthetic audio.
    elif block == "stale_database":
        conn.execute("UPDATE djmdContent SET Title='External edit' WHERE ID='remix'")
        conn.commit()
    else:
        def running():
            raise ManagerError("Rekordbox läuft")
        monkeypatch.setattr(db, "require_rekordbox_closed", running)
    with pytest.raises(ManagerError):
        db.rename_track(library, "copy", "New")
    assert db.load_library(path).by_id["copy"].title == library.by_id["copy"].title
    assert not (path.parent / "Crown (ARG) - New.mp3").exists()
    assert not path.with_name("RekordboxManager-Backups").exists()


@pytest.mark.parametrize("failure", ["journal", "rename", "analysis", "commit"])
def test_failed_save_restores_database_filename_and_analysis(collection, monkeypatch, failure):
    path, conn = collection
    add_path_columns(conn)
    analysis = path.parent / "share/PIONEER/USBANLZ/test/ANLZ0000.DAT"
    analysis.parent.mkdir(parents=True)
    original = analysis_bytes("?/copy.mp3")
    analysis.write_bytes(original)
    conn.execute("UPDATE djmdContent SET AnalysisDataPath='/PIONEER/USBANLZ/test/ANLZ0000.DAT' WHERE ID='copy'")
    conn.commit()
    library = db.load_library(path)
    audio = (path.parent / "copy.mp3").read_bytes()

    def fail(*args):
        raise OSError("simulated failure")

    if failure == "journal":
        monkeypatch.setattr(db, "_write_manifest", fail)
    elif failure == "rename":
        monkeypatch.setattr(db, "_rename_file", fail)
    elif failure == "analysis":
        monkeypatch.setattr(db, "_replace_bytes", fail)
    else:
        original_connect = db.connect

        class FailingCommit:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def commit(self):
                raise OSError("simulated commit failure")

        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            return FailingCommit(connection) if kwargs.get("writable") else connection

        monkeypatch.setattr(db, "connect", connect)
    with pytest.raises(ManagerError, match="zurückgerollt"):
        db.rename_track(library, "copy", "New")
    assert db.load_library(path).by_id["copy"] == library.by_id["copy"]
    assert (path.parent / "copy.mp3").read_bytes() == audio
    assert not (path.parent / "Crown (ARG) - New.mp3").exists()
    assert analysis.read_bytes() == original


def test_rename_creates_a_new_duplicate_group(collection):
    path, _ = collection
    db.rename_track(db.load_library(path), "copy", "Searching Memory (Remix)")
    group = db.load_library(path).groups[0]
    assert {track.id for track in group.tracks} == {"copy", "remix"}


def test_case_only_filename_change(collection):
    path, _ = collection
    first = db.rename_track(db.load_library(path), "copy", "new")
    second = db.rename_track(db.load_library(path), "copy", "NEW")
    assert second.path.name == "Crown (ARG) - NEW.mp3"
    assert second.path.read_bytes() and first.path.parent == second.path.parent
    assert db.load_library(path).by_id["copy"].filename == second.path.name


@pytest.mark.parametrize("layout", ["desktop", "external"])
def test_real_schema_and_analysis_on_isolated_copies(tmp_path, monkeypatch, layout):
    source = Path(__file__).resolve().parents[1] / "RecordBox Testdata/PIONEER/Master/master.db"
    if not source.is_file():
        pytest.skip("Local Rekordbox sample is not included in the repository")
    monkeypatch.setattr(db, "require_rekordbox_closed", lambda: None)
    before = db.fingerprint(source)
    copied = tmp_path / ("master.db" if layout == "desktop" else "PIONEER/Master/master.db")
    copied.parent.mkdir(parents=True, exist_ok=True)
    db.backup_database(source, copied, True)
    audio = tmp_path / "isolated.mp3"
    audio.write_bytes(b"synthetic audio for isolated rename test")
    with closing(db.connect(copied, writable=True)) as conn:
        row = conn.execute("SELECT ID, AnalysisDataPath FROM djmdContent WHERE AnalysisDataPath IS NOT NULL LIMIT 1").fetchone()
        track_id, analysis_path = str(row["ID"]), row["AnalysisDataPath"]
        conn.execute("UPDATE djmdContent SET FolderPath=?, OrgFolderPath=?, rb_LocalFolderPath=? WHERE ID=?",
                     (audio.as_posix(), audio.as_posix(), audio.as_posix(), track_id))
        conn.commit()
    relative = Path(analysis_path.replace("\\", "/").lstrip("/"))
    original_analysis = source.parent / "share" / relative
    if not original_analysis.is_file():
        original_analysis = source.parent.parent.parent / relative
    assert original_analysis.is_file()
    original_files = {file: file.read_bytes() for file in original_analysis.parent.iterdir()
                      if file.suffix.upper() in {".DAT", ".EXT", ".2EX"}}
    copied_dir = (tmp_path / "share" / relative if layout == "desktop" else tmp_path / relative).parent
    copied_dir.mkdir(parents=True)
    for file in original_files:
        shutil.copyfile(file, copied_dir / file.name)
    result = db.rename_track(db.load_library(copied), track_id, "Isolated title edit")
    assert db.load_library(copied).by_id[track_id].title == "Isolated title edit"
    assert result.path.is_file() and not audio.exists()
    from pyrekordbox.anlz import AnlzFile
    for file, original in original_files.items():
        updated = AnlzFile.parse((copied_dir / file.name).read_bytes())
        assert updated.get("path") in {result.path.as_posix(), "?/" + result.path.name}
        assert file.read_bytes() == original
    assert db.fingerprint(source) == before


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_unavailable_analysis_prevents_partial_changes(collection, kind):
    path, conn = collection
    add_path_columns(conn)
    analysis = path.parent / "share/PIONEER/USBANLZ/test/ANLZ0000.DAT"
    if kind == "corrupt":
        analysis.parent.mkdir(parents=True)
        analysis.write_bytes(b"damaged analysis")
    conn.execute("UPDATE djmdContent SET AnalysisDataPath='/PIONEER/USBANLZ/test/ANLZ0000.DAT' WHERE ID='copy'")
    conn.commit()
    library = db.load_library(path)
    with pytest.raises(ManagerError, match="Analysedatei"):
        db.rename_track(library, "copy", "New")
    assert db.load_library(path).by_id["copy"] == library.by_id["copy"]
    assert (path.parent / "copy.mp3").exists()
    assert not (path.parent / "Crown (ARG) - New.mp3").exists()


def test_post_commit_log_failure_reports_success_with_warning(collection, monkeypatch):
    path, _ = collection
    original_write = db._write_manifest

    def write(backup, manifest):
        if manifest["status"] == "completed":
            raise OSError("simulated full disk")
        original_write(backup, manifest)

    monkeypatch.setattr(db, "_write_manifest", write)
    result = db.rename_track(db.load_library(path), "copy", "New")
    assert result.warnings and "wurden gespeichert" in result.warnings[0]
    assert result.path.exists()
    assert db.load_library(path).by_id["copy"].title == "New"


def test_failed_filename_rollback_reports_recovery_paths(collection, monkeypatch):
    path, conn = collection
    add_path_columns(conn)
    analysis = path.parent / "share/PIONEER/USBANLZ/test/ANLZ0000.DAT"
    analysis.parent.mkdir(parents=True)
    analysis.write_bytes(analysis_bytes("?/copy.mp3"))
    conn.execute("UPDATE djmdContent SET AnalysisDataPath='/PIONEER/USBANLZ/test/ANLZ0000.DAT' WHERE ID='copy'")
    conn.commit()
    library = db.load_library(path)
    original_rename = db._rename_file

    def rename(source, destination):
        if destination.name == "copy.mp3":
            raise OSError("simulated failure restoring original filename")
        original_rename(source, destination)

    def fail(*args):
        raise OSError("simulated analysis write failure")

    monkeypatch.setattr(db, "_rename_file", rename)
    monkeypatch.setattr(db, "_replace_bytes", fail)
    with pytest.raises(ManagerError, match="nicht vollständig wiederhergestellt") as error:
        db.rename_track(library, "copy", "New")
    assert "copy.mp3" in str(error.value) and "Crown (ARG) - New.mp3" in str(error.value)
    assert db.load_library(path).by_id["copy"].title == library.by_id["copy"].title
    manifest_path = next(path.with_name("RekordboxManager-Protokolle").glob("*/operation.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "recovery_required" and manifest["recovery_errors"]
    assert not (manifest_path.parent / "master.db").exists()
    assert (manifest_path.parent / "analysis-0-ANLZ0000.DAT").is_file()


def test_incremental_snapshot_matches_reload_and_supports_another_write(collection):
    path, _ = collection
    first = db.rename_track(db.load_library(path), "copy", "New")
    assert first.library is not None
    assert first.library == db.load_library(path)
    second = db.rename_track(first.library, "copy", "Searching Memory (Remix)")
    assert second.library is not None
    assert second.library == db.load_library(path)
    assert {track.id for track in second.library.groups[0].tracks} == {"copy", "remix"}


def test_incremental_snapshot_in_wal_mode_without_other_connections(collection):
    path, conn = collection
    conn.close()
    library = db.load_library(path)
    result = db.rename_track(library, "copy", "New")
    assert result.library is not None
    assert result.library == db.load_library(path)
    second = db.rename_track(result.library, "copy", "Another title")
    assert second.library == db.load_library(path)


def test_path_checks_are_cached_and_alias_references_stay_valid(collection, monkeypatch):
    path, conn = collection
    add_path_columns(conn)
    (path.parent / "alias").mkdir()
    alias = str(path.parent / "alias" / ".." / "copy.mp3")
    conn.execute("UPDATE djmdContent SET FolderPath=?, OrgFolderPath=?, rb_LocalFolderPath=? WHERE ID='original'",
                 (alias, alias, alias))
    conn.commit()
    library = db.load_library(path)
    original_identity = db.path_identity
    resolutions = Counter()

    def identity(file):
        resolutions[file] += 1
        return original_identity(file)

    monkeypatch.setattr(db, "path_identity", identity)
    first = db.rename_track(library, "copy", "New")
    assert resolutions and all(count == 1 for count in resolutions.values())
    assert first.library == db.load_library(path)
    assert first.library.by_id["original"].path == str(first.path)
    assert first.library.by_id["original"].title == library.by_id["original"].title
    resolutions.clear()
    second = db.rename_track(first.library, "copy", "Another title")
    assert resolutions and all(count == 1 for count in resolutions.values())
    assert second.library == db.load_library(path)


def test_missing_destination_referenced_by_another_track_is_rejected(collection):
    path, conn = collection
    destination = path.parent / "Crown (ARG) - New.mp3"
    conn.execute("UPDATE djmdContent SET FolderPath=? WHERE ID='remix'", (str(destination),))
    conn.commit()
    library = db.load_library(path)
    with pytest.raises(ManagerError, match="bereits von einem anderen Titel"):
        db.rename_track(library, "copy", "New")
    assert not destination.exists()
    assert db.load_library(path) == library


@pytest.mark.parametrize("when", ["after_commit", "during_snapshot", "after_snapshot"])
def test_concurrent_change_disables_incremental_refresh(collection, monkeypatch, when):
    path, external = collection
    library = db.load_library(path)

    def external_edit():
        external.execute("UPDATE djmdContent SET Title='External change' WHERE ID='remix'")
        external.commit()

    if when == "after_commit":
        original_connect = db.connect

        class ConcurrentCommit:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def commit(self):
                self.connection.commit()
                external_edit()

        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            return ConcurrentCommit(connection) if kwargs.get("writable") else connection

        monkeypatch.setattr(db, "connect", connect)
    else:
        original_fingerprint = db.fingerprint
        checks = 0

        def fingerprint(file):
            nonlocal checks
            checks += 1
            if checks == (3 if when == "during_snapshot" else 4):
                external_edit()
            return original_fingerprint(file)

        monkeypatch.setattr(db, "fingerprint", fingerprint)
    result = db.rename_track(library, "copy", "New")
    assert result.library is None
    after = db.load_library(path)
    assert after.by_id["copy"].title == "New"
    assert after.by_id["remix"].title == "External change"


def test_incremental_refresh_failure_is_not_reported_as_a_rollback(collection, monkeypatch):
    path, _ = collection

    def failed_refresh(*args):
        raise RuntimeError("simulated refresh failure after commit")

    monkeypatch.setattr(db, "_library_after_rename", failed_refresh)
    result = db.rename_track(db.load_library(path), "copy", "New")
    assert result.library is None
    assert result.path.is_file()
    assert db.load_library(path).by_id["copy"].title == "New"
