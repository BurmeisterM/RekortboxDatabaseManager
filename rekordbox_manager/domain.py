"""Track data and deterministic duplicate detection, independent of the UI."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from pathlib import Path
import unicodedata


class ManagerError(Exception):
    """An actionable error that can be shown directly to the user."""


def normalize(value: str) -> str:
    # Keep punctuation and all mix/remix designations intact.
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def date_key(value: str) -> str:
    try:
        return datetime.fromisoformat(value.strip()[:10]).date().isoformat()
    except (ValueError, AttributeError):
        return "9999-12-31"


def display_date(value: str) -> str:
    key = date_key(value)
    return datetime.fromisoformat(key).strftime("%d.%m.%Y") if key != "9999-12-31" else "–"


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    added: str = ""
    path: str = ""
    cover: str = ""
    duration: int = 0
    bitrate: int = 0
    playlists: int = 0
    cues: int = 0
    available: bool = False
    playlist_names: tuple[str, ...] = ()

    @property
    def filename(self) -> str:
        return Path(self.path.replace("\\", "/")).name if self.path else ""

    @property
    def playlist_text(self) -> str:
        return "; ".join(self.playlist_names) if self.playlists else "Keine Playlist"

    @property
    def duplicate_key(self) -> tuple[str, str] | None:
        title, artist = normalize(self.title), normalize(self.artist)
        return (title, artist) if title and artist else None

    @property
    def duration_text(self) -> str:
        return f"{self.duration // 60}:{self.duration % 60:02d}" if self.duration else "–"


@dataclass(frozen=True)
class DuplicateGroup:
    key: tuple[str, str]
    tracks: tuple[Track, ...]
    recommended_id: str


def recommendation_rank(track: Track) -> tuple:
    # Bitrate wins even over availability/cues; playlist membership breaks ties.
    return (-track.bitrate, -int(track.playlists > 0), -int(track.available), -track.cues,
            date_key(track.added), track.id)


def find_duplicates(tracks: tuple[Track, ...] | list[Track]) -> tuple[DuplicateGroup, ...]:
    buckets: dict[tuple[str, str], list[Track]] = defaultdict(list)
    for track in tracks:
        if track.duplicate_key:
            buckets[track.duplicate_key].append(track)
    return tuple(
        DuplicateGroup(key, tuple(sorted(items, key=recommendation_rank)),
                       min(items, key=recommendation_rank).id)
        for key, items in sorted(buckets.items()) if len(items) > 1
    )


@dataclass(frozen=True)
class Library:
    path: Path
    tracks: tuple[Track, ...]
    fingerprint: tuple
    encrypted: bool
    db_id: str
    groups: tuple[DuplicateGroup, ...]

    @cached_property
    def by_id(self) -> dict[str, Track]:
        return {track.id: track for track in self.tracks}


@dataclass(frozen=True)
class RemovalPlan:
    # Each removed track maps to the explicitly retained member of its group.
    replacements: dict[str, str]


def validate_plan(library: Library, plan: RemovalPlan) -> None:
    if not plan.replacements:
        raise ManagerError("Bitte zuerst Duplikate zum Entfernen markieren.")
    tracks = library.by_id
    duplicate_ids = {t.id for g in library.groups for t in g.tracks}
    for removed, retained in plan.replacements.items():
        if removed not in tracks or retained not in tracks:
            raise ManagerError("Die Auswahl enthält einen nicht mehr vorhandenen Titel. Bitte neu laden.")
        if removed == retained or retained in plan.replacements:
            raise ManagerError("In jeder Duplikatgruppe muss mindestens ein Titel behalten werden.")
        if removed not in duplicate_ids or tracks[removed].duplicate_key != tracks[retained].duplicate_key:
            raise ManagerError("Ein Titel darf nur durch ein Duplikat derselben Gruppe ersetzt werden.")
