"""One local audio preview at a time, starting at the actual file's midpoint."""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .domain import Track


class AudioPreview(QObject):
    changed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.track: Track | None = None
        self.player: QMediaPlayer | None = None
        self.output = QAudioOutput(self)
        self.output.setVolume(0.7)
        self.pending = False
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(15000)
        self.timeout.timeout.connect(lambda: self._fail("Die Musikdatei konnte nicht rechtzeitig geladen werden."))

    def toggle(self, track: Track):
        same_track = self.track is not None and self.track.id == track.id
        self.stop()
        if same_track:
            return
        if not track.path or not Path(track.path).is_file():
            self.failed.emit("Die Musikdatei ist nicht erreichbar:\n" + (track.path or track.title))
            return
        player = QMediaPlayer(self)
        self.player = player
        self.track = track
        self.pending = True
        player.setAudioOutput(self.output)
        # Capture the source player so late signals from a replaced file are ignored.
        player.durationChanged.connect(lambda _: self._start_when_ready(player))
        player.seekableChanged.connect(lambda _: self._start_when_ready(player))
        player.mediaStatusChanged.connect(lambda status: self._status_changed(player, status))
        player.errorOccurred.connect(lambda _, message: self._fail(message, player))
        self.changed.emit(track)
        self.timeout.start()
        player.setSource(QUrl.fromLocalFile(str(Path(track.path).resolve())))

    def _start_when_ready(self, player):
        if player is not self.player or not self.pending:
            return
        if (player.mediaStatus() not in (QMediaPlayer.MediaStatus.LoadedMedia,
                                        QMediaPlayer.MediaStatus.BufferedMedia)
                or player.duration() <= 0 or not player.isSeekable()):
            return
        self.pending = False
        self.timeout.stop()
        player.setPosition(player.duration() // 2)
        player.play()

    def _status_changed(self, player, status):
        if player is not self.player:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()
        else:
            self._start_when_ready(player)

    def _fail(self, message, player=None):
        if player is not None and player is not self.player:
            return
        self.stop()
        self.failed.emit("Die Hörprobe konnte nicht abgespielt werden.\n" + message)

    def stop(self):
        self.timeout.stop()
        player, self.player = self.player, None
        self.track = None
        self.pending = False
        if player is not None:
            player.stop()
            player.setSource(QUrl())
            player.deleteLater()
        self.changed.emit(None)
