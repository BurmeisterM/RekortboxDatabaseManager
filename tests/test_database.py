from contextlib import closing
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from rekordbox_manager import database as db
from rekordbox_manager.domain import ManagerError, RemovalPlan


def test_encrypted_read_includes_wal_and_resolves_artwork(collection):
    path, conn = collection
    before = db.fingerprint(path)
    library = db.load_library(path)
    assert library.encrypted
    assert library.db_id == "test-library"
    assert len(library.tracks) == 3
    assert len(library.groups) == 1
    assert library.by_id["original"].cover.endswith("cover.png")
    assert library.by_id["copy"].playlists == 1
    assert library.by_id["copy"].playlist_names == ("Playlist 10",)
    assert library.by_id["remix"].playlist_names == ()
    assert library.by_id["copy"].bitrate == 320
    assert db.fingerprint(path) == before


def test_playlist_names_cover_multiple_playlists_and_repeated_entries(collection):
    path, conn = collection
    conn.execute("ALTER TABLE djmdPlaylist ADD COLUMN Name TEXT")
    conn.execute("UPDATE djmdPlaylist SET Name='Warmup' WHERE ID='10'")
    conn.execute("INSERT INTO djmdPlaylist (ID, Name) VALUES ('20', 'Club')")
    conn.execute("INSERT INTO djmdPlaylist (ID, Name) VALUES ('30', 'Club')")
    conn.executemany("INSERT INTO djmdSongPlaylist (ID,PlaylistID,ContentID,TrackNo) VALUES (?,?,?,?)",
                     [("p3", "10", "copy", 3), ("p4", "20", "copy", 1),
                      ("p5", "30", "copy", 1)])
    conn.commit()
    library = db.load_library(path)
    assert library.by_id["copy"].playlist_names == ("Club", "Club", "Warmup")
    assert library.by_id["copy"].playlists == 4
    assert library.by_id["original"].playlist_names == ("Warmup",)
    assert library.by_id["remix"].playlist_text == "Keine Playlist"


def test_deleted_playlists_and_memberships_do_not_count_as_usage(collection):
    path, conn = collection
    conn.execute("ALTER TABLE djmdPlaylist ADD COLUMN rb_local_deleted INTEGER DEFAULT 0")
    conn.execute("UPDATE djmdSongPlaylist SET rb_local_deleted=1 WHERE ContentID='copy'")
    conn.commit()
    library = db.load_library(path)
    assert library.by_id["copy"].playlists == 0
    assert library.by_id["copy"].playlist_names == ()
    assert library.by_id["original"].playlists == 1
    conn.execute("UPDATE djmdPlaylist SET rb_local_deleted=1")
    conn.commit()
    library = db.load_library(path)
    assert library.by_id["original"].playlists == 0
    assert library.by_id["original"].playlist_names == ()


def test_removal_transfers_playlist_positions_cleans_references_and_backs_up_wal(collection):
    path, _ = collection
    library = db.load_library(path)
    xml_before = path.with_name("masterPlaylists6.xml").read_bytes()
    result = db.remove_duplicates(library, RemovalPlan({"copy": "original"}))
    assert result.removed == 1
    assert result.trashed == (library.by_id["copy"].path,) and result.warnings == ()
    assert not Path(library.by_id["copy"].path).is_file()
    after = db.load_library(path)
    assert {t.id for t in after.tracks} == {"original", "remix"}
    assert after.by_id["original"].playlists == 2
    assert after.by_id["original"].playlist_names == ("Playlist 10",)
    with closing(db.connect(path)) as conn:
        assert [tuple(r) for r in conn.execute("SELECT ContentID,TrackNo FROM djmdSongPlaylist ORDER BY TrackNo")] == [("original", 1), ("original", 2)]
        for table in ("contentCue", "djmdRecommendLike", "uuidIDMap", "imageFile"):
            assert conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0
        assert conn.execute("SELECT ID FROM djmdCue").fetchone()[0] == "cue-original"
        assert conn.execute("SELECT int_1 FROM agentRegistry").fetchone()[0] > 10
        assert conn.execute("SELECT rb_local_usn FROM djmdPlaylist").fetchone()[0] > 10
    saved = db.load_library(result.backup / "master.db")
    assert len(saved.tracks) == 3
    assert saved.by_id["copy"].playlists == 1
    assert (result.backup / "masterPlaylists6.xml").read_bytes() == xml_before
    assert ET.parse(path.with_name("masterPlaylists6.xml")).find(".//NODE").get("Timestamp") != "1"
    manifest = json.loads((result.backup / "operation.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["plan"]["replacements"] == {"copy": "original"}
    assert (result.backup / "master.db").read_bytes()[:16] != b"SQLite format 3\x00"


def test_stale_library_is_not_modified(collection):
    path, conn = collection
    library = db.load_library(path)
    conn.execute("UPDATE djmdContent SET Title='Changed' WHERE ID='remix'")
    conn.commit()
    with pytest.raises(ManagerError, match="seit dem Laden"):
        db.remove_duplicates(library, RemovalPlan({"copy": "original"}))
    assert len(db.load_library(path).tracks) == 3
    assert not path.with_name("RekordboxManager-Backups").exists()


def test_all_playlists_replace_removed_group_members_with_the_chosen_keeper(collection):
    path, conn = collection
    conn.execute("INSERT INTO djmdContent (ID,Title,ArtistID,BitRate) VALUES ('keeper','Searching Memory','artist',320)")
    conn.executemany("INSERT INTO djmdPlaylist (ID) VALUES (?)", [("20",), ("30",)])
    conn.executemany("INSERT INTO djmdSongPlaylist (ID,PlaylistID,ContentID,TrackNo) VALUES (?,?,?,?)",
                     [("p3", "10", "copy", 3), ("p4", "20", "original", 1),
                      ("p5", "20", "remix", 2), ("p6", "20", "copy", 3),
                      ("p7", "30", "remix", 1)])
    conn.commit()
    before = list(conn.execute("SELECT ID,PlaylistID,ContentID,TrackNo FROM djmdSongPlaylist ORDER BY ID"))
    path.with_name("masterPlaylists6.xml").write_text(
        '<MASTER_PLAYLIST><PLAYLISTS><NODE Id="A" Timestamp="1"/>'
        '<NODE Id="14" Timestamp="1"/><NODE Id="1E" Timestamp="1"/></PLAYLISTS></MASTER_PLAYLIST>',
        encoding="utf-8")
    library = db.load_library(path)
    assert library.by_id["keeper"].playlists == 0
    # An explicitly chosen keeper also replaces members in playlists it never belonged to.
    plan = RemovalPlan({"original": "keeper", "copy": "keeper"})
    db.remove_duplicates(library, plan)
    after = db.load_library(path)
    assert set(after.by_id) == {"keeper", "remix"}
    assert after.by_id["keeper"].playlists == 5
    assert after.by_id["keeper"].playlist_names == ("Playlist 10", "Playlist 20")
    with closing(db.connect(path)) as check:
        rows = [tuple(row) for row in check.execute(
            "SELECT ID,PlaylistID,ContentID,TrackNo FROM djmdSongPlaylist ORDER BY ID")]
    assert rows == [(row_id, playlist, plan.replacements.get(track, track), position)
                    for row_id, playlist, track, position in before]
    stamps = {node.get("Id"): node.get("Timestamp")
              for node in ET.parse(path.with_name("masterPlaylists6.xml")).iter("NODE")}
    assert stamps["A"] != "1" and stamps["14"] != "1"
    assert stamps["1E"] == "1"


def test_backup_failure_prevents_all_changes(collection, monkeypatch):
    path, _ = collection
    library = db.load_library(path)
    xml_before = path.with_name("masterPlaylists6.xml").read_bytes()

    def failed(*args):
        raise OSError("no space")

    monkeypatch.setattr(db, "backup_database", failed)
    with pytest.raises(ManagerError, match="zurückgerollt"):
        db.remove_duplicates(library, RemovalPlan({"copy": "original"}))
    assert len(db.load_library(path).tracks) == 3
    assert path.with_name("masterPlaylists6.xml").read_bytes() == xml_before


def test_unknown_reference_without_id_rolls_back(collection):
    path, conn = collection
    conn.execute("CREATE TABLE futureReference (ContentID TEXT)")
    conn.execute("INSERT INTO futureReference VALUES ('copy')")
    conn.commit()
    library = db.load_library(path)
    with pytest.raises(ManagerError, match="unbekannte Titelreferenz"):
        db.remove_duplicates(library, RemovalPlan({"copy": "original"}))
    assert len(db.load_library(path).tracks) == 3
    assert db.load_library(path).by_id["copy"].playlists == 1


def test_commit_failure_restores_database_and_playlist_xml(collection, monkeypatch):
    path, _ = collection
    library = db.load_library(path)
    xml_before = path.with_name("masterPlaylists6.xml").read_bytes()
    original_connect = db.connect

    class FailingCommit:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            raise OSError("simulated commit failure")

    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        return FailingCommit(conn) if kwargs.get("writable") else conn

    monkeypatch.setattr(db, "connect", connect)
    with pytest.raises(ManagerError, match="zurückgerollt"):
        db.remove_duplicates(library, RemovalPlan({"copy": "original"}))
    assert path.with_name("masterPlaylists6.xml").read_bytes() == xml_before
    assert len(db.load_library(path).tracks) == 3
    assert db.load_library(path).by_id["copy"].playlists == 1


def test_audio_is_only_processed_after_commit_and_failures_are_reported(collection, monkeypatch):
    path, _ = collection
    library = db.load_library(path)
    calls = []

    def fail_to_recycle(file):
        # The primary database must already be committed at this point.
        assert len(db.load_library(path).tracks) == 2
        calls.append(file)
        raise OSError("no recycle bin")

    monkeypatch.setattr(db, "recycle_file", fail_to_recycle)
    result = db.remove_duplicates(library, RemovalPlan({"copy": "original"}))
    assert len(calls) == 1
    assert result.removed == 1 and not result.trashed
    assert "bleibt erhalten" in result.warnings[0]
    assert calls[0].exists()


def test_removal_always_recycles_audio_after_commit(collection, monkeypatch):
    path, _ = collection
    calls = []

    def recycle(file):
        assert "copy" not in db.load_library(path).by_id
        calls.append(file)
        file.unlink()  # only the fixture's synthetic file

    monkeypatch.setattr(db, "recycle_file", recycle)
    result = db.remove_duplicates(db.load_library(path), RemovalPlan({"copy": "original"}))
    assert calls == [path.parent / "copy.mp3"]
    assert result.trashed == (str(calls[0]),)
    assert (path.parent / "original.mp3").is_file()


def test_missing_audio_after_error_is_not_reported_as_retained(collection, monkeypatch):
    path, _ = collection

    def uncertain_result(file):
        file.unlink()  # only the fixture's synthetic music file
        raise OSError("receipt unavailable")

    monkeypatch.setattr(db, "recycle_file", uncertain_result)
    result = db.remove_duplicates(db.load_library(path), RemovalPlan({"copy": "original"}))
    assert result.removed == 1
    assert not result.trashed
    assert "ursprünglichen Pfad nicht mehr vorhanden" in result.warnings[0]
    assert "bleibt erhalten" not in result.warnings[0]


def test_two_entries_one_missing_file_and_one_recycled_is_not_a_failure(collection, monkeypatch):
    path, conn = collection
    conn.execute("UPDATE djmdContent SET Title='Searching Memory' WHERE ID='remix'")
    conn.commit()
    (path.parent / "copy.mp3").unlink()  # only the synthetic test file

    def recycle_test_file(file):
        assert file == path.parent / "remix.mp3"
        file.unlink()  # simulate moving the synthetic file to the bin

    monkeypatch.setattr(db, "recycle_file", recycle_test_file)
    library = db.load_library(path)
    result = db.remove_duplicates(library, RemovalPlan({"copy": "original", "remix": "original"}))
    assert result.removed == 2
    assert len(result.trashed) == 1
    assert not result.warnings
    assert len(result.notices) == 1
    assert "copy.mp3" in result.notices[0]
    manifest = json.loads((result.backup / "operation.json").read_text(encoding="utf-8"))
    assert manifest["notices"] == list(result.notices)
    assert manifest["warnings"] == []
    assert len(db.load_library(path).tracks) == 1


@pytest.mark.parametrize("kind", ["same_path", "hardlink"])
def test_retained_music_is_protected_even_via_hardlinks(collection, kind):
    path, conn = collection
    original = path.parent / "original.mp3"
    if kind == "same_path":
        conn.execute("UPDATE djmdContent SET FolderPath=? WHERE ID='copy'", (str(original),))
        conn.commit()
    else:
        duplicate = path.parent / "copy.mp3"
        duplicate.unlink()  # only the synthetic fixture's known test file
        duplicate.hardlink_to(original)
    candidates, warnings = db.audio_candidates(db.load_library(path), RemovalPlan({"copy": "original"}))
    assert not candidates
    assert "weiter verwendet" in warnings[0]
    result = db.remove_duplicates(db.load_library(path), RemovalPlan({"copy": "original"}))
    assert not result.trashed and original.is_file()
    assert any("weiter verwendet" in notice for notice in result.notices)


def test_running_rekordbox_prevents_writes(collection, monkeypatch):
    path, _ = collection

    def blocked():
        raise ManagerError("Rekordbox läuft")

    monkeypatch.setattr(db, "require_rekordbox_closed", blocked)
    with pytest.raises(ManagerError, match="Rekordbox läuft"):
        db.remove_duplicates(db.load_library(path), RemovalPlan({"copy": "original"}))
    assert not path.with_name("RekordboxManager-Backups").exists()


def test_missing_metadata_is_not_grouped_and_tombstones_are_hidden(collection):
    path, conn = collection
    conn.execute("UPDATE djmdContent SET rb_local_deleted=1 WHERE ID='copy'")
    conn.commit()
    library = db.load_library(path)
    assert len(library.tracks) == 2 and not library.groups


def test_real_testdata_on_an_isolated_copy(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "RecordBox Testdata" / "PIONEER" / "Master" / "master.db"
    if not source.is_file():
        pytest.skip("Local Rekordbox sample is not included in the repository")
    monkeypatch.setattr(db, "require_rekordbox_closed", lambda: None)
    monkeypatch.setattr(db, "recycle_file", lambda file: pytest.fail("Original audio must remain protected"))
    before = db.fingerprint(source)
    library = db.load_library(source)
    assert library.tracks
    assert any(t.cover for t in library.tracks)
    copied = tmp_path / "master.db"
    db.backup_database(source, copied, True)
    with closing(db.connect(copied, writable=True)) as conn:
        first = dict(conn.execute("SELECT * FROM djmdContent LIMIT 1").fetchone())
        first["ID"] = "9876543210"
        first["UUID"] = "isolated-test-duplicate"
        columns = ",".join(db.quote(c) for c in first)
        placeholders = ",".join("?" for _ in first)
        conn.execute(f"INSERT INTO djmdContent ({columns}) VALUES ({placeholders})", tuple(first.values()))
        conn.commit()
    copy_lib = db.load_library(copied)
    group = next(g for g in copy_lib.groups if any(t.id == "9876543210" for t in g.tracks))
    retained = next(t.id for t in group.tracks if t.id != "9876543210")
    result = db.remove_duplicates(copy_lib, RemovalPlan({"9876543210": retained}))
    assert len(db.load_library(copied).tracks) == len(library.tracks)
    assert len(db.load_library(result.backup / "master.db").tracks) == len(library.tracks) + 1
    assert db.fingerprint(source) == before
