import time
import wave

import pytest

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from rekordbox_manager.domain import Track
from rekordbox_manager.playback import AudioPreview


@pytest.fixture
def preview(qt_app):
    # Keep Qt objects out of Python's cyclic GC during backend callbacks, and
    # finish deferred native destruction before the next test creates a backend.
    result = AudioPreview(qt_app)
    result.output.setMuted(True)
    yield result
    result.stop()
    result.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_until(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def silent_audio(path):
    if path.suffix == ".mp3":
        # MPEG-1 Layer III, 128 kbit/s, 44.1 kHz, mono. Empty spectral data is silence.
        path.write_bytes((b"\xff\xfb\x90\xc0" + b"\0" * 413) * 400)
    else:
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 80000)


@pytest.mark.parametrize("extension", [".wav", ".mp3"])
def test_real_audio_starts_at_midpoint_and_toggle_releases_file(preview, tmp_path, extension):
    path = tmp_path / ("Hörprobe mit Leerzeichen" + extension)
    silent_audio(path)
    # Deliberately wrong DB duration: the file duration must determine the midpoint.
    track = Track("1", "Test", "Artist", path=str(path), duration=999)
    failures = []
    preview.failed.connect(failures.append)
    try:
        preview.toggle(track)
        player = preview.player
        starts = []
        player.playbackStateChanged.connect(
            lambda state: starts.append(player.position())
            if state == QMediaPlayer.PlaybackState.PlayingState else None)
        wait_until(lambda: starts or failures)
        assert not failures
        assert 10000 <= player.duration() <= 11000
        assert player.duration() // 2 <= starts[0] < player.duration() // 2 + 500
        preview.toggle(track)
        assert preview.track is None and preview.player is None
        path.rename(tmp_path / ("released" + extension))
    finally:
        preview.stop()


def test_switching_tracks_ignores_previous_signals_and_clears_at_end(preview, tmp_path):
    path = tmp_path / "silent.wav"
    silent_audio(path)
    failures = []
    preview.failed.connect(failures.append)
    try:
        preview.toggle(Track("1", "First", "Artist", path=str(path)))
        old_player = preview.player
        preview.toggle(Track("2", "Second", "Artist", path=str(path)))
        new_player = preview.player
        preview._status_changed(old_player, QMediaPlayer.MediaStatus.EndOfMedia)
        preview._fail("stale error", old_player)
        assert preview.player is new_player and preview.track.id == "2"
        wait_until(lambda: not preview.pending or failures)
        assert not failures
        new_player.setPosition(new_player.duration() - 100)
        wait_until(lambda: preview.track is None)
        assert preview.player is None
    finally:
        preview.stop()


def test_stopping_loading_and_late_signals_cannot_restart_audio(preview, tmp_path):
    path = tmp_path / "invalid.mp3"
    path.write_bytes(b"invalid audio")
    track = Track("1", "Test", "Artist", path=str(path))
    failures = []
    preview.failed.connect(failures.append)
    preview.toggle(track)
    old_player = preview.player
    preview.toggle(track)
    preview._start_when_ready(old_player)
    preview._status_changed(old_player, QMediaPlayer.MediaStatus.EndOfMedia)
    preview._fail("stale error", old_player)
    assert preview.player is None and preview.track is None
    assert not failures
    preview.toggle(track)
    wait_until(lambda: bool(failures))
    assert preview.player is None and preview.track is None
    assert not preview.timeout.isActive()


def test_missing_file_is_reported(preview, tmp_path):
    failures = []
    preview.failed.connect(failures.append)
    preview.toggle(Track("1", "Test", "Artist", path=str(tmp_path / "missing.mp3")))
    assert len(failures) == 1
    assert "nicht erreichbar" in failures[0]
    assert preview.player is None


def test_repeated_switching_between_mp3_and_wav(preview, tmp_path):
    paths = [tmp_path / "silent.wav", tmp_path / "silent.mp3"]
    for path in paths:
        silent_audio(path)
    failures = []
    preview.failed.connect(failures.append)
    for index in range(12):
        preview.toggle(Track(str(index), "Test", "Artist", path=str(paths[index % 2])))
        wait_until(lambda: not preview.pending or failures)
        assert not failures
        assert preview.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        assert preview.player.position() >= preview.player.duration() // 2
