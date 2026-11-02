import base64
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from sqlcipher3 import dbapi2 as sql

from rekordbox_manager import database


@pytest.fixture
def collection(tmp_path, monkeypatch):
    """A small encrypted collection with committed changes living in its WAL."""
    monkeypatch.setattr(database, "require_rekordbox_closed", lambda: None)

    def recycle_synthetic(file):
        assert file.resolve().parent == tmp_path.resolve()
        file.unlink()  # Simulate recycling only this fixture's synthetic audio.

    monkeypatch.setattr(database, "recycle_file", recycle_synthetic)
    path = tmp_path / "master.db"
    conn = sql.connect(str(path))
    conn.execute("PRAGMA key='" + database.database_key() + "'")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE djmdContent (
            ID TEXT PRIMARY KEY, Title TEXT, ArtistID TEXT, FolderPath TEXT,
            StockDate TEXT, ImagePath TEXT, Length INTEGER, BitRate INTEGER,
            UUID TEXT, rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER,
            updated_at TEXT, created_at TEXT
        );
        CREATE TABLE djmdArtist (ID TEXT PRIMARY KEY, Name TEXT);
        CREATE TABLE djmdPlaylist (ID TEXT PRIMARY KEY, updated_at TEXT, rb_local_usn INTEGER);
        CREATE TABLE djmdSongPlaylist (
            ID TEXT PRIMARY KEY, PlaylistID TEXT, ContentID TEXT, TrackNo INTEGER,
            updated_at TEXT, rb_local_usn INTEGER, rb_local_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE djmdCue (ID TEXT PRIMARY KEY, ContentID TEXT, ContentUUID TEXT);
        CREATE TABLE contentCue (ID TEXT PRIMARY KEY, ContentID TEXT);
        CREATE TABLE djmdRecommendLike (ID TEXT PRIMARY KEY, ContentID1 TEXT, ContentID2 TEXT);
        CREATE TABLE uuidIDMap (ID TEXT PRIMARY KEY, TableName TEXT, CurrentID TEXT);
        CREATE TABLE imageFile (ID TEXT PRIMARY KEY, TableName TEXT, TargetID TEXT);
        CREATE TABLE djmdProperty (DBID TEXT PRIMARY KEY);
        CREATE TABLE agentRegistry (registry_id TEXT PRIMARY KEY, int_1 INTEGER);
        INSERT INTO djmdArtist VALUES ('artist', 'Crown (ARG)');
        INSERT INTO djmdPlaylist VALUES ('10', '2025-01-01', 10);
        INSERT INTO djmdSongPlaylist VALUES ('p1', '10', 'copy', 1, '', 10, 0);
        INSERT INTO djmdSongPlaylist VALUES ('p2', '10', 'original', 2, '', 10, 0);
        INSERT INTO djmdCue VALUES ('cue-original', 'original', 'uuid-original');
        INSERT INTO djmdCue VALUES ('cue-copy', 'copy', 'uuid-copy');
        INSERT INTO contentCue VALUES ('packed-copy', 'copy');
        INSERT INTO djmdRecommendLike VALUES ('like', 'copy', 'original');
        INSERT INTO uuidIDMap VALUES ('map', 'djmdContent', 'copy');
        INSERT INTO imageFile VALUES ('image', 'djmdContent', 'copy');
        INSERT INTO djmdProperty VALUES ('test-library');
        INSERT INTO agentRegistry VALUES ('localUpdateCount', 10);
    """)
    cover = tmp_path / "share" / "PIONEER" / "Artwork" / "cover.png"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
    for track_id, title, date in (("original", "Searching Memory", "2020-01-01"),
                                  ("copy", "  searching   MEMORY ", "2026-01-01"),
                                  ("remix", "Searching Memory (Remix)", "2026-01-02")):
        music = tmp_path / f"{track_id}.mp3"
        music.write_bytes(b"synthetic test audio; not a real track")
        conn.execute("INSERT INTO djmdContent VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (track_id, title, "artist", str(music), date, "/PIONEER/Artwork/cover.png",
                      380, 320, f"uuid-{track_id}", 0, 10, "", date))
    conn.commit()
    (tmp_path / "masterPlaylists6.xml").write_text(
        '<?xml version="1.0"?><MASTER_PLAYLIST><PLAYLISTS><NODE Id="A" Timestamp="1"/>'
        '</PLAYLISTS></MASTER_PLAYLIST>', encoding="utf-8")
    yield path, conn
    conn.close()


@pytest.fixture(scope="session")
def qt_app(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from rekordbox_manager.ui import STYLE, ensure_fonts
    app = QApplication.instance() or QApplication([])
    ensure_fonts()
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp("settings")))
    return app
