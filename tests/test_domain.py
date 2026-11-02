from pathlib import Path

import pytest

from rekordbox_manager.domain import (
    Library, ManagerError, RemovalPlan, Track, display_date, find_duplicates, validate_plan,
)


def test_matching_preserves_mix_names_and_punctuation():
    tracks = [Track("1", "  Searching   Memory", "CROWN (ARG)"),
              Track("2", "searching memory ", "Crown (ARG)"),
              Track("3", "Searching Memory (Extended Mix)", "Crown (ARG)"),
              Track("4", "Searching Memory", "Someone Else"),
              Track("5", "", "Crown (ARG)"), Track("6", "", "Crown (ARG)"),
              Track("7", "Searching-Memory", "Crown (ARG)")]
    groups = find_duplicates(tracks)
    assert len(groups) == 1
    assert {t.id for t in groups[0].tracks} == {"1", "2"}


def test_unicode_normalization():
    assert len(find_duplicates([Track("1", "Café", "Artist"), Track("2", "Cafe\u0301", "artist")])) == 1


def test_recommendation_prefers_bitrate_then_playlist_membership():
    tracks = [Track("missing", "A", "B", bitrate=1411, cues=99),
              Track("available", "A", "B", available=True, bitrate=320),
              Track("cues", "A", "B", available=True, bitrate=128, cues=2),
              Track("playlists", "A", "B", available=True, bitrate=128, cues=2, playlists=2),
              Track("quality", "A", "B", available=True, bitrate=320, cues=2, playlists=2, added="2025-01-01"),
              Track("oldest", "A", "B", available=True, bitrate=320, cues=2, playlists=2, added="2020-01-01")]
    assert find_duplicates(tracks)[0].recommended_id == "missing"
    assert [t.id for t in find_duplicates(tracks)[0].tracks] == ["missing", "oldest", "quality", "available", "playlists", "cues"]


def test_playlist_membership_wins_a_bitrate_tie_over_availability_and_cues():
    tracks = [Track("available", "A", "B", bitrate=320, available=True, cues=99),
              Track("playlist", "A", "B", bitrate=320, playlists=1),
              Track("many-playlists", "A", "B", bitrate=128, playlists=100)]
    assert find_duplicates(tracks)[0].recommended_id == "playlist"


def test_remaining_ties_are_deterministic():
    tracks = [Track("b", "A", "B", bitrate=320, playlists=3, added="2020-01-01"),
              Track("a", "A", "B", bitrate=320, playlists=1, added="2020-01-01")]
    assert find_duplicates(tracks)[0].recommended_id == "a"
    assert find_duplicates(list(reversed(tracks)))[0].recommended_id == "a"


@pytest.mark.parametrize("mapping", [{}, {"a": "a"}, {"a": "b", "b": "a"}, {"a": "c"}, {"a": "unknown"}])
def test_invalid_removal_is_rejected(mapping):
    tracks = (Track("a", "A", "B"), Track("b", "A", "B"), Track("c", "Else", "B"))
    library = Library(Path("master.db"), tracks, (), False, "", find_duplicates(tracks))
    with pytest.raises(ManagerError):
        validate_plan(library, RemovalPlan(mapping))


def test_dates_are_german_and_missing_values_are_explicit():
    assert display_date("2026-10-24 10:12:04.781 +00:00") == "24.10.2026"
    assert display_date("") == "–"
