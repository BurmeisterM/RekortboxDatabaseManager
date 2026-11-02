"""SQLCipher access, consistent backups and transactional duplicate removal.

Readers use mode=ro and include the WAL. No unencrypted temporary database is
created. Table/column names come only from SQLite's schema and are quoted.
"""

from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from functools import cache
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET
from uuid import uuid4

import psutil
from sqlcipher3 import dbapi2 as sql

from .domain import Library, ManagerError, RemovalPlan, Track, find_duplicates, validate_plan
from .recycle import recycle_file


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def database_key() -> str:
    from pyrekordbox.masterdb.database import BLOB
    from pyrekordbox.utils import deobfuscate
    return deobfuscate(BLOB)


def connect(path: Path, *, writable: bool = False, encrypted: bool | None = None):
    if not path.is_file():
        raise ManagerError(f"Datenbank nicht gefunden:\n{path}")
    if encrypted is None:
        with path.open("rb") as file:
            encrypted = file.read(16) != b"SQLite format 3\x00"
    conn = sql.connect(path.resolve().as_uri() + ("?mode=rw" if writable else "?mode=ro"),
                       uri=True, timeout=5)
    try:
        if encrypted:
            # SQLCipher does not accept a bound parameter for PRAGMA key.
            conn.execute("PRAGMA key='" + database_key().replace("'", "''") + "'")
        conn.row_factory = sql.Row
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        if not writable:
            conn.execute("PRAGMA query_only=ON")
        return conn
    except Exception:
        conn.close()
        raise


def schema(conn) -> dict[str, set[str]]:
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0]: {c[1] for c in conn.execute(f"PRAGMA table_info({quote(row[0])})")}
            for row in tables if not row[0].startswith("sqlite_")}


def validate_schema(tables: dict[str, set[str]]) -> None:
    required = {
        "djmdContent": {"ID", "Title", "ArtistID", "FolderPath", "StockDate", "ImagePath"},
        "djmdArtist": {"ID", "Name"},
        "djmdSongPlaylist": {"ID", "PlaylistID", "ContentID", "TrackNo"},
        "djmdPlaylist": {"ID"},
        "agentRegistry": {"registry_id", "int_1"},
    }
    for table, columns in required.items():
        if not columns <= tables.get(table, set()):
            raise ManagerError("Diese Datei hat kein unterstütztes Rekordbox-master.db-Schema.\n"
                               "Bitte die master.db auswählen; Geräte-Exporte sind eine andere Datenquelle.")


def fingerprint(path: Path) -> tuple:
    result = []
    for file in (path, Path(str(path) + "-wal"), path.parent / "masterPlaylists6.xml"):
        if not file.exists() or (file.name.endswith("-wal") and file.stat().st_size <= 32):
            result.append(None)
            continue
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result.append(digest.hexdigest())
    return tuple(result)


def require_rekordbox_closed() -> None:
    try:
        for process in psutil.process_iter(["name"]):
            name = (process.info["name"] or "").casefold()
            if name in {"rekordbox", "rekordbox.exe", "rekordboxagent", "rekordboxagent.exe"}:
                raise ManagerError("Bitte Rekordbox und den Rekordbox Agent vollständig schließen, "
                                   "bevor Änderungen gespeichert werden.")
    except (psutil.AccessDenied, psutil.Error) as exc:
        raise ManagerError("Es konnte nicht geprüft werden, ob Rekordbox geschlossen ist.") from exc


def live_filter(columns: set[str], prefix: str = "") -> str:
    return f"COALESCE({prefix}rb_local_deleted, 0)=0" if "rb_local_deleted" in columns else "1=1"


def resolve_cover(value: str, database: Path) -> str:
    if not value:
        return ""
    normalized = value.replace("\\", "/")
    relative = normalized.lstrip("/")
    # External master databases store artwork under share/PIONEER/Artwork.
    candidates = [database.parent / "share" / relative, database.parent / relative]
    for parent in list(database.parents)[:4]:
        candidates.append(parent / relative)
    candidates.append(Path(normalized))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def audio_path(value: str, database: Path) -> Path | None:
    if not value or "://" in value:
        return None
    path = Path(value.replace("\\", "/"))
    # Never guess a new drive for an absolute music path when deleting files.
    return path if path.is_absolute() else database.parent / path


def _counts(conn, tables: dict, table: str) -> dict[str, int]:
    if not {"ContentID"} <= tables.get(table, set()):
        return {}
    return {str(row[0]): row[1] for row in conn.execute(
        f"SELECT ContentID, count(*) FROM {quote(table)} "
        f"WHERE {live_filter(tables[table])} GROUP BY ContentID")}


def _playlist_usage(conn, tables: dict) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    counts: dict[str, int] = {}
    names: dict[str, dict[str, str]] = {}
    name_column = 'p.Name' if 'Name' in tables['djmdPlaylist'] else 'NULL'
    for row in conn.execute(
        f'SELECT s.ContentID, p.ID, {name_column} AS playlist_name '
        'FROM djmdSongPlaylist s JOIN djmdPlaylist p ON p.ID=s.PlaylistID '
        f'WHERE {live_filter(tables["djmdSongPlaylist"], "s.")} '
        f'AND {live_filter(tables["djmdPlaylist"], "p.")}'):
        track_id, playlist_id = str(row["ContentID"]), str(row["ID"])
        counts[track_id] = counts.get(track_id, 0) + 1
        names.setdefault(track_id, {})[playlist_id] = row["playlist_name"] or f"Playlist {playlist_id}"
    return counts, {track_id: tuple(sorted(playlists.values(), key=str.casefold))
                    for track_id, playlists in names.items()}


def _read_tracks(conn, tables: dict, path: Path) -> tuple[Track, ...]:
    playlists, playlist_names = _playlist_usage(conn, tables)
    cues = _counts(conn, tables, "djmdCue")
    result = []
    for row in conn.execute(
        'SELECT c.*, a.Name AS artist_name FROM djmdContent c '
        'LEFT JOIN djmdArtist a ON a.ID=c.ArtistID '
        f'WHERE {live_filter(tables["djmdContent"], "c.")}'):
        values = dict(row)
        music = audio_path(values.get("FolderPath") or "", path)
        track_id = str(row["ID"])
        result.append(Track(
            id=track_id, title=row["Title"] or "", artist=row["artist_name"] or "",
            added=values.get("StockDate") or values.get("created_at") or "",
            path=str(music) if music else (values.get("FolderPath") or ""),
            cover=resolve_cover(values.get("ImagePath") or "", path),
            duration=int(values.get("Length") or 0), bitrate=int(values.get("BitRate") or 0),
            playlists=playlists.get(track_id, 0), cues=cues.get(track_id, 0),
            available=bool(music and music.is_file()),
            playlist_names=playlist_names.get(track_id, ()),
        ))
    return tuple(sorted(result, key=lambda t: (t.title.casefold(), t.artist.casefold(), t.id)))


def load_library(path: str | Path) -> Library:
    path = Path(path).resolve()
    if path.suffix.casefold() != ".db":
        raise ManagerError("Bitte eine master.db auswählen. export.pdb und XML-Dateien werden nicht bearbeitet.")
    try:
        before = fingerprint(path)
        with path.open("rb") as file:
            encrypted = file.read(16) != b"SQLite format 3\x00"
        with closing(connect(path, encrypted=encrypted)) as conn:
            conn.execute("BEGIN")
            tables = schema(conn)
            validate_schema(tables)
            check_integrity(conn)
            tracks = _read_tracks(conn, tables, path)
            db_id = ""
            if "DBID" in tables.get("djmdProperty", set()):
                row = conn.execute("SELECT DBID FROM djmdProperty LIMIT 1").fetchone()
                db_id = str(row[0]) if row else ""
        after = fingerprint(path)
        if before != after:
            raise ManagerError("Die Datenbank wurde während des Lesens geändert. Bitte Rekordbox schließen und neu laden.")
        return Library(path, tracks, after, encrypted, db_id, find_duplicates(tracks))
    except ManagerError:
        raise
    except (sql.Error, OSError, ValueError) as exc:
        raise ManagerError("Die Datenbank konnte nicht geöffnet werden. Bitte die master.db samt "
                           "zugehörigen WAL-Dateien verwenden und den Laufwerkszugriff prüfen.\n\n"
                           f"Details: {exc}") from exc


def check_integrity(conn) -> None:
    if [row[0] for row in conn.execute("PRAGMA quick_check")] != ["ok"]:
        raise ManagerError("Die Datenbankprüfung meldet Fehler. Es wurden keine Änderungen gespeichert.")


def backup_database(path: Path, destination: Path, encrypted: bool) -> None:
    # SQLite's backup API captures committed WAL pages, unlike copying master.db.
    with closing(connect(path, encrypted=encrypted)) as source:
        with closing(sql.connect(str(destination))) as target:
            if encrypted:
                target.execute("PRAGMA key='" + database_key().replace("'", "''") + "'")
            source.backup(target)
            check_integrity(target)


class Mutation:
    """Apply per-row timestamps and local sequence numbers like Rekordbox."""

    def __init__(self, conn, tables: dict):
        self.conn, self.tables = conn, tables
        row = conn.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()
        if row is None:
            raise ManagerError("Der Rekordbox-Änderungszähler fehlt. Die Datenbank wird nicht geändert.")
        self.usn = int(row[0] or 0)
        self.now = datetime.now(timezone.utc).isoformat(sep=" ", timespec="milliseconds")

    def update(self, table: str, row_id: str, values: dict) -> None:
        self.usn += 1
        values = dict(values)
        columns = self.tables[table]
        if "rb_local_usn" in columns:
            values["rb_local_usn"] = self.usn
        if "updated_at" in columns:
            values["updated_at"] = self.now
        if not values:
            return
        assignments = ",".join(f"{quote(key)}=?" for key in values)
        self.conn.execute(f"UPDATE {quote(table)} SET {assignments} WHERE ID=?", (*values.values(), row_id))

    def delete(self, table: str, row_id: str) -> None:
        self.usn += 1
        self.conn.execute(f"DELETE FROM {quote(table)} WHERE ID=?", (row_id,))

    def finish(self) -> None:
        self.conn.execute("UPDATE agentRegistry SET int_1=? WHERE registry_id='localUpdateCount'", (self.usn,))


def _remove_rows(conn, tables: dict, plan: RemovalPlan) -> tuple[set[str], str]:
    change = Mutation(conn, tables)
    affected_playlists: set[str] = set()
    # Retain the playlist positions, including deliberate repeated entries.
    for removed, retained in plan.replacements.items():
        rows = conn.execute("SELECT ID,PlaylistID FROM djmdSongPlaylist WHERE ContentID=?", (removed,)).fetchall()
        for row in rows:
            change.update("djmdSongPlaylist", row["ID"], {"ContentID": retained})
            affected_playlists.add(str(row["PlaylistID"]))

    # Discover every reference in the actual v7 schema, not only library ORM models.
    for table, columns in tables.items():
        if table in {"djmdContent", "djmdSongPlaylist"}:
            continue
        references = sorted(columns & {"ContentID", "ContentID1", "ContentID2", "ContentUUID"})
        for column in references:
            for removed in plan.replacements:
                value = removed
                if column == "ContentUUID":
                    if "UUID" not in tables["djmdContent"]:
                        continue
                    row = conn.execute("SELECT UUID FROM djmdContent WHERE ID=?", (removed,)).fetchone()
                    value = row[0] if row else None
                if value is None:
                    continue
                rows = conn.execute(f"SELECT * FROM {quote(table)} WHERE {quote(column)}=?", (value,)).fetchall()
                if rows and "ID" not in columns:
                    raise ManagerError(f"Eine unbekannte Titelreferenz in {table} verhindert das sichere Entfernen.")
                for row in rows:
                    change.delete(table, row["ID"])

    for removed in plan.replacements:
        # Remove per-content bookkeeping without touching shared artwork files.
        for table in ("uuidIDMap", "imageFile"):
            columns = tables.get(table, set())
            target = "CurrentID" if table == "uuidIDMap" else "TargetID"
            if {"ID", "TableName", target} <= columns:
                for row in conn.execute(f"SELECT ID FROM {quote(table)} WHERE TableName='djmdContent' "
                                        f"AND {quote(target)}=?", (removed,)).fetchall():
                    change.delete(table, row[0])
        change.delete("djmdContent", removed)
    for playlist_id in affected_playlists:
        change.update("djmdPlaylist", playlist_id, {})
    change.finish()
    return affected_playlists, change.now


def _playlist_xml(path: Path, playlists: set[str], timestamp: str) -> bytes | None:
    if not path.is_file() or not playlists:
        return None
    tree = ET.parse(path)
    ids = {format(int(value), "X") for value in playlists if value.isdecimal()}
    milliseconds = str(int(datetime.fromisoformat(timestamp).timestamp() * 1000))
    for node in tree.iter("NODE"):
        if node.get("Id", "").upper() in ids:
            node.set("Timestamp", milliseconds)
    return ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)


def path_identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def audio_candidates(library: Library, plan: RemovalPlan) -> tuple[list[Path], list[str]]:
    remaining = [track for track in library.tracks if track.id not in plan.replacements]
    referenced = {path_identity(Path(track.path)) for track in remaining if track.path and "://" not in track.path}
    existing_inodes = set()
    for track in remaining:
        if track.path:
            try:
                stat = Path(track.path).stat()
                if stat.st_ino:
                    existing_inodes.add((stat.st_dev, stat.st_ino))
            except OSError:
                continue
    candidates, notices, seen = [], [], set()
    for removed in plan.replacements:
        track = library.by_id[removed]
        path = Path(track.path) if track.path else None
        if not path or not path.is_file():
            notices.append(f"Musikdatei bereits nicht vorhanden oder nicht erreichbar: {track.path or track.title}")
            continue
        identity = path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        shared = identity in referenced
        if not shared:
            # Also protect hardlinks and alternate spellings of retained files.
            stat = path.stat()
            shared = bool(stat.st_ino and (stat.st_dev, stat.st_ino) in existing_inodes)
        if shared:
            notices.append(f"Musikdatei wird weiter verwendet und bleibt erhalten: {path}")
            continue
        if path.suffix.casefold() not in {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".alac"}:
            notices.append(f"Dateityp wird nicht als Musikdatei entfernt: {path}")
            continue
        candidates.append(path)
    return candidates, notices


@dataclass(frozen=True)
class RemovalResult:
    removed: int
    backup: Path
    trashed: tuple[str, ...]
    warnings: tuple[str, ...]
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenameResult:
    track_id: str
    title: str
    path: Path
    journal: Path
    warnings: tuple[str, ...] = ()
    library: Library | None = None


def _library_after_rename(library: Library, affected_ids: set[str], track_id: str,
                          title: str, destination: Path, state: tuple) -> Library:
    tracks = tuple(sorted(
        (replace(track, title=title if track.id == track_id else track.title,
                 path=str(destination), available=True) if track.id in affected_ids else track
         for track in library.tracks),
        key=lambda track: (track.title.casefold(), track.artist.casefold(), track.id)))
    return replace(library, tracks=tracks, fingerprint=state, groups=find_duplicates(tracks))


def _renamed_audio_path(source: Path, artist: str, title: str) -> Path:
    if not title.strip() or len(title) > 255 or any(ord(char) < 32 for char in title):
        raise ManagerError("Bitte einen Titel mit 1 bis 255 Zeichen ohne Steuerzeichen eingeben.")
    if source.suffix.casefold() not in {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".alac"}:
        raise ManagerError("Der Dateityp wird nicht als Musikdatei umbenannt.")
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", f"{artist.strip() or 'Unbekannter Interpret'} - {title}").rstrip(" .")
    filename = stem + source.suffix
    if len(filename.encode("utf-16-le")) // 2 > 255:
        raise ManagerError("Interpret und Titel ergeben einen zu langen Dateinamen. Bitte den Titel kürzen.")
    return source.with_name(filename)


def _analysis_path_bytes(data: bytes, destination: Path) -> bytes:
    """Replace only PPTH; retain cues, waveforms and unknown analysis tags byte for byte."""
    if len(data) < 28 or data[:4] != b"PMAI":
        raise ManagerError("Eine Rekordbox-Analysedatei hat ein unbekanntes Format.")
    offset, length = struct.unpack_from(">II", data, 4)
    if not 28 <= offset <= length == len(data):
        raise ManagerError("Eine Rekordbox-Analysedatei ist beschädigt.")
    parts = [data[:offset]]
    while offset < len(data):
        if offset + 12 > len(data):
            raise ManagerError("Eine Rekordbox-Analysedatei ist unvollständig.")
        header, size = struct.unpack_from(">II", data, offset + 4)
        if not 12 <= header <= size or offset + size > len(data):
            raise ManagerError("Eine Rekordbox-Analysedatei enthält einen ungültigen Abschnitt.")
        tag = data[offset:offset + size]
        if tag[:4] == b"PPTH":
            if header != 16 or size < 18 or struct.unpack_from(">I", tag, 12)[0] != size - 16:
                raise ManagerError("Der Pfad einer Rekordbox-Analysedatei hat ein unbekanntes Format.")
            old = tag[16:-2].decode("utf-16-be")
            new = "?/" + destination.name if old.startswith("?/") else destination.as_posix()
            encoded = new.encode("utf-16-be") + b"\x00\x00"
            tag = b"PPTH" + struct.pack(">III", 16, 16 + len(encoded), len(encoded)) + encoded
        parts.append(tag)
        offset += size
    updated = bytearray(b"".join(parts))
    struct.pack_into(">I", updated, 8, len(updated))
    return bytes(updated)


def _rename_analysis_files(rows: list[dict], database: Path, destination: Path) -> dict[Path, tuple[bytes, bytes]]:
    result = {}
    for row in rows:
        value = row.get("AnalysisDataPath")
        if not value:
            continue
        relative = value.replace("\\", "/").lstrip("/")
        candidates = [database.parent / "share" / relative, database.parent / relative]
        candidates.extend(parent / relative for parent in list(database.parents)[:4])
        candidates.append(Path(value.replace("\\", "/")))
        analysis = next((candidate for candidate in candidates if candidate.is_file()), None)
        if analysis is None:
            raise ManagerError(f"Die zugehörige Analysedatei ist nicht erreichbar:\n{value}")
        for file in analysis.parent.iterdir():
            if re.fullmatch(r"ANLZ\d{4}\.(DAT|EXT|2EX)", file.name, re.IGNORECASE):
                file = file.resolve()
                if file not in result:
                    original = file.read_bytes()
                    result[file] = original, _analysis_path_bytes(original, destination)
    return result


def _replace_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.rbm-tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _rename_file(source: Path, destination: Path) -> None:
    # Windows rename refuses an existing target, including one created after this check.
    if os.path.lexists(destination) and os.path.normcase(str(source)) != os.path.normcase(str(destination)):
        raise ManagerError(f"Der Zieldateiname ist bereits vorhanden:\n{destination}")
    source.rename(destination)


def rename_track(library: Library, track_id: str, title: str, *, journal_root: Path | None = None) -> RenameResult:
    """Save a title and audio/analysis paths without copying the database."""
    title = title.strip()
    track = library.by_id.get(track_id)
    if track is None:
        raise ManagerError("Der Titel ist nicht mehr vorhanden. Bitte die Sammlung neu laden.")
    source = Path(track.path)
    destination = _renamed_audio_path(source, track.artist, title)
    require_rekordbox_closed()
    if fingerprint(library.path) != library.fingerprint:
        raise ManagerError("Die Sammlung wurde seit dem Laden geändert. Bitte neu laden.")
    if not track.path or not source.is_file() or source.is_symlink():
        raise ManagerError(f"Die Musikdatei ist nicht erreichbar oder eine symbolische Verknüpfung:\n{track.path}")
    source_stat = source.stat()
    # Cache only for this operation: a rename can invalidate resolved aliases.
    identity = cache(path_identity)
    source_identity, destination_identity = identity(source), identity(destination)
    journal_root = journal_root or library.path.parent / "RekordboxManager-Protokolle"
    journal = journal_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    renamed = False
    replaced = []
    refreshed = None
    observer = None
    observer_version = None
    manifest = {"format": 1, "operation": "rename_track", "database": str(library.path),
                "db_id": library.db_id, "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "prepared", "track_id": track_id, "old_title": track.title, "title": title,
                "old_path": str(source), "new_path": str(destination), "files": []}
    try:
        with closing(connect(library.path, writable=True, encrypted=library.encrypted)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                require_rekordbox_closed()
                if fingerprint(library.path) != library.fingerprint:
                    raise ManagerError("Die Sammlung wurde inzwischen geändert. Bitte neu laden.")
                tables = schema(conn)
                validate_schema(tables)
                data_version = conn.execute("PRAGMA data_version").fetchone()[0]
                # Every entry using this filename must keep a working link, including tombstones.
                affected_ids = set()
                for row in conn.execute("SELECT ID, FolderPath FROM djmdContent"):
                    linked = audio_path(row["FolderPath"], library.path)
                    if linked is None:
                        continue
                    linked_identity = identity(linked)
                    if linked_identity == source_identity:
                        affected_ids.add(str(row["ID"]))
                    elif linked_identity == destination_identity:
                        raise ManagerError("Der Zieldateipfad wird bereits von einem anderen Titel verwendet.")
                if track_id not in affected_ids:
                    raise ManagerError("Die Dateiverknüpfung wurde geändert. Bitte die Sammlung neu laden.")
                rows = [dict(conn.execute("SELECT * FROM djmdContent WHERE ID=?", (row_id,)).fetchone())
                        for row_id in sorted(affected_ids)]
                analysis = _rename_analysis_files(rows, library.path, destination)
                journal.mkdir(parents=True, exist_ok=False)
                manifest["tracks"] = rows
                for number, (file, (original, updated)) in enumerate(analysis.items()):
                    saved = f"analysis-{number}-{file.name}"
                    (journal / saved).write_bytes(original)
                    manifest["files"].append({"path": str(file), "backup": saved})
                _write_manifest(journal, manifest)
                change = Mutation(conn, tables)
                for row in rows:
                    values = {"FolderPath": destination.as_posix()}
                    if str(row["ID"]) == track_id:
                        values["Title"] = title
                    if "FileNameL" in tables["djmdContent"]:
                        values["FileNameL"] = destination.name
                    if row.get("FileNameS"):
                        values["FileNameS"] = ""
                    for column in ("OrgFolderPath", "rb_LocalFolderPath"):
                        linked = audio_path(row.get(column) or "", library.path)
                        if linked is not None and identity(linked) == source_identity:
                            values[column] = destination.as_posix()
                    change.update("djmdContent", str(row["ID"]), values)
                change.finish()
                check_integrity(conn)
                require_rekordbox_closed()
                if source.stat() != source_stat:
                    raise ManagerError("Die Musikdatei wurde inzwischen geändert. Bitte erneut laden.")
                if source != destination:
                    _rename_file(source, destination)
                    renamed = True
                for file, (original, updated) in analysis.items():
                    if file.read_bytes() != original:
                        raise ManagerError("Eine Analysedatei wurde inzwischen geändert. Bitte erneut laden.")
                    _replace_bytes(file, updated)
                    replaced.append((file, original))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                recovery_errors = []
                for file, original in reversed(replaced):
                    try:
                        _replace_bytes(file, original)
                    except Exception as recovery:
                        recovery_errors.append(f"{file}: {recovery}")
                if renamed:
                    try:
                        _rename_file(destination, source)
                    except Exception as recovery:
                        recovery_errors.append(f"{destination} → {source}: {recovery}")
                manifest.update(status="recovery_required" if recovery_errors else "rolled_back", error=str(exc),
                                recovery_errors=recovery_errors)
                if journal.is_dir():
                    try:
                        _write_manifest(journal, manifest)
                    except OSError:
                        pass
                if recovery_errors:
                    raise ManagerError("Die Datenbankänderung wurde zurückgerollt, aber Dateien konnten nicht vollständig "
                                       f"wiederhergestellt werden. Bitte das Änderungsprotokoll prüfen:\n{journal}\n"
                                       + "\n".join(recovery_errors)) from exc
                raise
            # Reacquire the write lock after commit before adopting an incremental
            # snapshot. data_version detects commits by other connections in the gap.
            # Any failure here is post-commit: the caller can still reload normally.
            try:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("PRAGMA data_version").fetchone()[0] == data_version:
                    refreshed = _library_after_rename(library, affected_ids, track_id, title,
                                                      destination, ())
                    # Keep a read-only observer open across writer shutdown. This
                    # retains the WAL and detects any other commit after the lock
                    # is released, without rereading every track and cover.
                    observer = connect(library.path, encrypted=library.encrypted)
                    observer_version = observer.execute("PRAGMA data_version").fetchone()[0]
            except Exception:
                refreshed = None
            finally:
                conn.rollback()
    except ManagerError:
        raise
    except Exception as exc:
        raise ManagerError(f"Der Titel konnte nicht gespeichert werden. Die Änderungen wurden zurückgerollt.\n{exc}") from exc
    warnings = []
    try:
        if refreshed is not None:
            state = fingerprint(library.path)
            if observer.execute("PRAGMA data_version").fetchone()[0] != observer_version:
                refreshed = None
            else:
                refreshed = replace(refreshed, fingerprint=state)
    except (sql.Error, OSError):
        refreshed = None
    finally:
        if observer is not None:
            observer.close()
    if refreshed is not None:
        try:
            # Never adopt an intermediate fingerprint if closing the observer
            # changed physical files, or another writer committed in the gap.
            if fingerprint(library.path) != refreshed.fingerprint:
                refreshed = None
        except OSError:
            refreshed = None
    manifest["status"] = "completed"
    try:
        _write_manifest(journal, manifest)
    except OSError as exc:
        warnings.append(f"Titel und Dateipfad wurden gespeichert; das Abschlussprotokoll konnte nicht aktualisiert werden: {exc}")
    return RenameResult(track_id, title, destination, journal, tuple(warnings), refreshed)


def remove_duplicates(library: Library, plan: RemovalPlan, *, backup_root: Path | None = None) -> RemovalResult:
    validate_plan(library, plan)
    require_rekordbox_closed()
    path = library.path
    if fingerprint(path) != library.fingerprint:
        raise ManagerError("Die Sammlung wurde seit dem Laden geändert. Bitte neu laden und die Auswahl erneut prüfen.")
    backup_root = backup_root or path.parent / "RekordboxManager-Backups"
    backup = backup_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    xml_path = path.parent / "masterPlaylists6.xml"
    xml_original = None
    xml_replaced = False
    committed = False
    manifest = {"format": 1, "database": str(path), "db_id": library.db_id,
                "created_at": datetime.now(timezone.utc).isoformat(), "status": "prepared",
                "plan": asdict(plan), "tracks": [asdict(library.by_id[i]) for i in plan.replacements],
                "trashed": [], "warnings": [], "notices": []}
    try:
        with closing(connect(path, writable=True, encrypted=library.encrypted)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                require_rekordbox_closed()
                if fingerprint(path) != library.fingerprint:
                    raise ManagerError("Die Sammlung wurde inzwischen geändert. Bitte neu laden.")
                tables = schema(conn)
                validate_schema(tables)
                backup.mkdir(parents=True, exist_ok=False)
                backup_database(path, backup / "master.db", library.encrypted)
                if xml_path.is_file():
                    xml_original = xml_path.read_bytes()
                    (backup / xml_path.name).write_bytes(xml_original)
                _write_manifest(backup, manifest)
                affected, timestamp = _remove_rows(conn, tables, plan)
                check_integrity(conn)
                updated_xml = _playlist_xml(xml_path, affected, timestamp)
                require_rekordbox_closed()
                if updated_xml is not None:
                    staged = backup / "masterPlaylists6.updated.xml"
                    staged.write_bytes(updated_xml)
                    # Same filesystem as the database by default; copy then replace
                    # also supports a user-supplied backup directory on another drive.
                    temp_xml = xml_path.with_name(f"masterPlaylists6.xml.{uuid4().hex}.rbm-tmp")
                    try:
                        with temp_xml.open("xb") as stream:
                            stream.write(updated_xml)
                        os.replace(temp_xml, xml_path)
                        xml_replaced = True
                    finally:
                        temp_xml.unlink(missing_ok=True)
                conn.commit()
                committed = True
            except Exception:
                conn.rollback()
                if xml_replaced and xml_original is not None:
                    xml_path.write_bytes(xml_original)
                raise
    except ManagerError:
        raise
    except Exception as exc:
        raise ManagerError(f"Die Entfernung wurde abgebrochen. Die Datenbankänderungen wurden zurückgerollt.\n{exc}") from exc

    # Audio is handled only after a successful DB commit. A file failure must
    # never be reported as a rollback of an already committed database change.
    warnings, trashed, notices = [], [], []
    if committed:
        manifest["status"] = "database_committed"
        try:
            _write_manifest(backup, manifest)
        except OSError as exc:
            warnings.append(f"Das Änderungsprotokoll konnte nicht aktualisiert werden: {exc}")
    try:
        candidates, messages = audio_candidates(library, plan)
    except OSError as exc:
        candidates = []
        warnings.append(f"Musikdateien bleiben erhalten. Die Dateiprüfung ist fehlgeschlagen: {exc}")
    else:
        notices.extend(messages)
    for file in candidates:
        try:
            # Always recycle after commit; never fall back to permanent deletion.
            recycle_file(file)
            trashed.append(str(file))
        except Exception as exc:
            if file.exists():
                warnings.append(f"Musikdatei bleibt erhalten (Papierkorb-Vorgang fehlgeschlagen): {file}\n{exc}")
            else:
                warnings.append(f"Papierkorb-Status unklar: {file}\n{exc}\n"
                                "Die Datei ist am ursprünglichen Pfad nicht mehr vorhanden. Bitte den Windows-Papierkorb prüfen.")
    manifest.update(status="completed", trashed=trashed, warnings=warnings, notices=notices)
    try:
        _write_manifest(backup, manifest)
    except OSError as exc:
        warnings.append(f"Das Abschlussprotokoll konnte nicht gespeichert werden: {exc}")
    return RemovalResult(len(plan.replacements), backup, tuple(trashed), tuple(warnings), tuple(notices))


def _write_manifest(backup: Path, data: dict) -> None:
    temp = backup / "operation.json.tmp"
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(backup / "operation.json")


def default_database() -> Path | None:
    # Prefer the configured database (including external drives) over the default.
    root = Path(os.environ.get("APPDATA", str(Path.home())))
    candidates = []
    for settings in (root / "Pioneer" / "rekordbox7" / "rekordbox3.settings",
                     root / "Pioneer" / "rekordbox6" / "rekordbox3.settings",
                     root / "Pioneer" / "rekordbox" / "rekordbox3.settings"):
        if settings.is_file():
            try:
                for node in ET.parse(settings).iter("VALUE"):
                    if node.get("name") == "masterDbDirectory" and node.get("val"):
                        directory = Path(os.path.expandvars(node.get("val"))).expanduser()
                        if not directory.is_absolute():
                            directory = settings.parent / directory
                        candidates.append(directory / "master.db")
            except (ET.ParseError, OSError):
                continue
    candidates.append(root / "Pioneer" / "rekordbox" / "master.db")
    return next((p for p in candidates if p.is_file()), None)
