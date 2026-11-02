"""Native Qt Widgets interface. Database and filesystem work runs off the UI thread."""

from collections import OrderedDict
from pathlib import Path
import os
import sys
import traceback

from PySide6.QtCore import (
    QAbstractTableModel, QEvent, QModelIndex, QObject, QRunnable, QSettings,
    QSize, Qt, QThreadPool, QTimer, QUrl, Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSplitter, QStyle, QStyledItemDelegate, QStyleOptionComboBox, QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget,
)

from . import __version__
from .database import (
    RemovalResult, audio_candidates, default_database, load_library, remove_duplicates, rename_track,
)
from .domain import Library, ManagerError, RemovalPlan, Track, display_date, normalize, validate_plan
from .playback import AudioPreview


STYLE = """
QWidget { background: #11151c; color: #e9edf5; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #11151c; }
QFrame#sidebar { background: #0c1016; border-right: 1px solid #252c38; }
QFrame#sidebar QLabel, QFrame#sidebar QWidget { background: transparent; }
QLabel#brand { color: #8aefce; font-size: 24px; font-weight: 800; }
QLabel#eyebrow { color: #8aefce; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#heading { font-size: 27px; font-weight: 700; }
QLabel#muted { color: #98a5b8; }
QLabel#detailTitle { font-size: 18px; font-weight: 600; }
QFrame#card { background: #191f29; border: 1px solid #2b3443; border-radius: 10px; }
QFrame#card QLabel { background: transparent; border: none; }
QLabel#statNumber { font-size: 27px; font-weight: 700; }
QPushButton { background: #222b39; border: 1px solid #344056; border-radius: 6px; padding: 9px 13px; }
QPushButton:hover { background: #303e51; border-color: #71859f; }
QPushButton:disabled { color: #627087; background: #1b222d; border-color: #293240; }
QPushButton#primary { background: #8aefce; color: #0d211b; border-color: #8aefce; font-weight: 600; }
QPushButton#primary:hover { background: #b1f7e0; }
QPushButton#primary:disabled { background: #223b34; color: #729387; border-color: #2f5045; }
QPushButton#danger { background: #ef8f93; color: #311417; border-color: #ef8f93; font-weight: 600; }
QPushButton#danger:disabled { background: #34272e; color: #997177; border-color: #4a333d; }
QPushButton#nav { text-align: left; background: transparent; border: none; padding: 12px; color: #a3afc2; }
QPushButton#nav:checked { background: #1b322e; color: #9ef1d4; border-left: 3px solid #8aefce; border-radius: 4px; }
QLineEdit { background: #191f29; border: 1px solid #344056; border-radius: 6px; padding: 10px; selection-background-color: #315b52; }
QLineEdit:focus { border-color: #8aefce; }
QTableView { background: #151b24; alternate-background-color: #19212c; border: 1px solid #2b3443; border-radius: 8px; gridline-color: #242e3c; }
QTableView::item { padding: 5px; border-bottom: 1px solid #232d3a; }
QHeaderView::section { background: #1c2532; color: #b1bfd1; border: none; border-bottom: 1px solid #344056; padding: 11px 7px; font-size: 11px; font-weight: 600; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QTableView::indicator { width: 17px; height: 17px; border-radius: 3px; border: 1px solid #8394a9; background: #1b2330; }
QCheckBox::indicator:checked { background: #8aefce; border: 3px solid #427b69; }
QTableView::indicator:checked { background: #ef8f93; border: 3px solid #a84e58; }
QCheckBox::indicator:disabled, QTableView::indicator:disabled { border-color: #354153; background: #202936; }
QSplitter::handle { background: #252e3c; width: 1px; }
QProgressBar { border: none; background: #1c2634; max-height: 3px; }
QProgressBar::chunk { background: #8aefce; }
QToolTip { background: #253344; color: white; border: 1px solid #62738a; padding: 6px; }
QScrollBar:vertical { background: #151b24; width: 10px; }
QScrollBar::handle:vertical { background: #43516a; border-radius: 4px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def ensure_fonts():
    # The offscreen Qt platform on Windows does not enumerate system fonts.
    if not QFontDatabase.families() and sys.platform == "win32":
        root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont(str(root / filename))


def app_settings() -> QSettings:
    # The organization/application overload always uses NativeFormat. Pass the
    # format explicitly so isolated INI settings also work in offscreen tests.
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope,
                     "RekordboxDatabaseManager", "Desktop")


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text: str, callback, name: str = "") -> QPushButton:
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    return widget


def placeholder(size: int = 46) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#283748"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#8aefce"))
    painter.setFont(QFont("Segoe UI Symbol", max(12, size // 3)))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
    painter.end()
    return pixmap


class CoverCache:
    def __init__(self):
        self.cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.empty = placeholder()

    def get(self, path: str) -> QPixmap:
        if not path:
            return self.empty
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        pixmap = QPixmap(path)
        pixmap = (pixmap.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                  if not pixmap.isNull() else self.empty)
        self.cache[path] = pixmap
        if len(self.cache) > 500:
            self.cache.popitem(last=False)
        return pixmap


class CoverLabel(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Klicken: ab der Mitte abspielen · Erneut klicken: stoppen")
        self.setAccessibleName("Hörprobe über das Titelbild starten oder stoppen")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class TrackDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.data(Qt.ItemDataRole.BackgroundRole) is not None:
            # Use the model palette so stylesheets do not mask group colors.
            option = QStyleOptionViewItem(option)
            option.widget = None
            if index.siblingAtColumn(0).data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked:
                option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, option, index)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        color = index.data(Qt.ItemDataRole.ForegroundRole)
        if color is not None:
            option.palette.setColor(QPalette.ColorRole.HighlightedText, color)
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if background is not None:
            marked = index.siblingAtColumn(0).data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            option.palette.setColor(QPalette.ColorRole.Highlight, background if marked else background.lighter(150))


class TitleDelegate(TrackDelegate):
    title_submitted = Signal(str, str)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setProperty("track_id", index.model().rows[index.row()].id)
        editor.setAccessibleName("Titel bearbeiten")
        editor.setToolTip("Return: Titel und Dateiname speichern · Escape: abbrechen")
        return editor

    def setEditorData(self, editor, index):
        editor.setText(index.model().rows[index.row()].title)
        editor.selectAll()

    def setModelData(self, editor, model, index):
        # Focus changes and Tab must not save; only an explicit Return submits.
        pass

    def eventFilter(self, editor, event):
        if isinstance(editor, QLineEdit):
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    track_id, title = editor.property("track_id"), editor.text()
                    self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                    self.title_submitted.emit(track_id, title)
                    return True
                if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                    self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.RevertModelCache)
                    return True
            if event.type() == QEvent.Type.FocusOut:
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.RevertModelCache)
                return False
        return super().eventFilter(editor, event)


class PlaylistDelegate(TrackDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if len(index.data(TrackModel.PLAYLIST_NAMES_ROLE) or ()) > 1:
            option.text = ""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        names = index.data(TrackModel.PLAYLIST_NAMES_ROLE) or ()
        if len(names) < 2:
            return
        cell = QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        combo = QStyleOptionComboBox()
        combo.rect = cell.rect.adjusted(4, 10, -4, -10)
        combo.state = cell.state
        combo.palette = cell.palette
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if background is not None:
            marked = index.siblingAtColumn(0).data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            if cell.state & QStyle.StateFlag.State_Selected and not marked:
                background = background.lighter(150)
            combo.palette.setColor(QPalette.ColorRole.Button, background)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if foreground is not None:
            combo.palette.setColor(QPalette.ColorRole.ButtonText, foreground)
        combo.currentText = cell.fontMetrics.elidedText(
            f"{names[0]} (+{len(names) - 1})", Qt.TextElideMode.ElideRight,
            max(0, combo.rect.width() - 30))
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, combo, painter, option.widget)
        style.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, combo, painter, option.widget)

    def createEditor(self, parent, option, index):
        names = index.data(TrackModel.PLAYLIST_NAMES_ROLE) or ()
        if len(names) < 2:
            return None
        editor = QComboBox(parent)
        editor.addItems(names)
        editor.setAccessibleName("Playlists dieses Titels")
        for row, name in enumerate(names):
            editor.setItemData(row, name, Qt.ItemDataRole.ToolTipRole)
        editor.activated.connect(lambda: self.closeEditor.emit(editor))
        QTimer.singleShot(0, editor, editor.showPopup)
        return editor

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(0)

    def setModelData(self, editor, model, index):
        # This dropdown only displays memberships; selecting a name changes no data.
        pass


class TrackModel(QAbstractTableModel):
    selection_changed = Signal()
    safety_warning = Signal(str)
    PLAYLIST_NAMES_ROLE = Qt.ItemDataRole.UserRole + 1
    HEADERS = ["Entfernen", "Cover", "Titel", "Interpret", "Hinzugefügt", "Länge", "Bitrate (kbit/s)", "Playlists", "Cues", "Auswahl", "Gruppe", "Dateiname"]
    GROUP_BACKGROUNDS = ("#203348", "#233d36", "#38304a", "#3c3927")

    def __init__(self):
        super().__init__()
        self.library: Library | None = None
        self.rows: list[Track] = []
        self.selected: set[str] = set()
        self.keepers: dict[tuple[str, str], str] = {}
        self.group_numbers: dict[str, int] = {}
        self.recommended: set[str] = set()
        self.covers = CoverCache()
        self.duplicates_only = True
        self.search = ""
        self.sort_column = 10
        self.sort_order = Qt.SortOrder.AscendingOrder

    def set_library(self, library: Library):
        self.library = library
        self.selected.clear()
        self.keepers = {g.key: g.recommended_id for g in library.groups}
        self.recommended = {g.recommended_id for g in library.groups}
        self.group_numbers = {t.id: index for index, g in enumerate(library.groups, 1) for t in g.tracks}
        self.covers = CoverCache()
        self.refresh()

    def refresh(self):
        self.beginResetModel()
        tracks = self.library.tracks if self.library else ()
        if self.duplicates_only:
            tracks = tuple(t for g in self.library.groups for t in g.tracks) if self.library else ()
        needle = normalize(self.search)
        matched_keys = {t.duplicate_key for t in tracks
                        if needle in normalize(f"{t.title} {t.artist} {t.path}")}
        self.rows = [t for t in tracks if not needle or
                     (self.duplicates_only and t.duplicate_key in matched_keys) or
                     (not self.duplicates_only and needle in normalize(f"{t.title} {t.artist} {t.path}"))]
        self._sort_rows()
        self.endResetModel()
        self.selection_changed.emit()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def is_keeper(self, track: Track) -> bool:
        return self.keepers.get(track.duplicate_key) == track.id

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        track = self.rows[index.row()]
        col = index.column()
        group = self.group_numbers.get(track.id)
        if role == self.PLAYLIST_NAMES_ROLE and col == 7:
            return track.playlist_names
        if role == Qt.ItemDataRole.CheckStateRole and col == 0 and group:
            return Qt.CheckState.Checked if track.id in self.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DecorationRole and col == 1:
            return self.covers.get(track.cover)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 2:
                return f"Doppelklick: Titel bearbeiten · Return: speichern\n{track.title}\n{track.path}"
            if col == 1:
                return "Klicken: ab der Mitte abspielen · Erneut klicken: stoppen"
            if col == 0 and self.is_keeper(track):
                return "Zum Entfernen ankreuzen. Ein anderes Exemplar wird behalten. Sind alle markiert, erscheint eine Warnung."
            if col == 7:
                return "Playlists:\n" + "\n".join(track.playlist_names) if track.playlists else "Keine Playlist"
            if col == 11:
                return track.path
            return f"{track.title} · {track.artist}\n{track.path}\nID: {track.id}"
        if role == Qt.ItemDataRole.ForegroundRole:
            if track.id in self.selected:
                return QColor("#ef8f93")
            if col in (2, 11) and group and track.playlists:
                return QColor("#ef8f93")
            if col == 11 and not track.playlists:
                return QColor("#8aefce")
            if col == 9 and self.is_keeper(track):
                return QColor("#8aefce")
        if role == Qt.ItemDataRole.BackgroundRole:
            if track.id in self.selected:
                return QColor("#3b2029")
            if group:
                return QColor(self.GROUP_BACKGROUNDS[(group - 1) % len(self.GROUP_BACKGROUNDS)])
        if role == Qt.ItemDataRole.DisplayRole:
            state = ""
            if track.id in self.selected:
                state = "Entfernen"
            elif self.is_keeper(track):
                state = "Behalten · Tipp" if track.id in self.recommended else "Behalten"
            elif group:
                state = "Duplikat"
            values = ["", "", track.title or "Ohne Titel", track.artist or "Unbekannt",
                      display_date(track.added), track.duration_text,
                      str(track.bitrate) if track.bitrate else "–", track.playlist_text,
                      str(track.cues), state, f"{group:03d}" if group else "–", track.filename or "–"]
            return values[col]
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            track = self.rows[index.row()]
            if track.id in self.group_numbers:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
        if index.column() == 7 and len(self.rows[index.row()].playlist_names) > 1:
            flags |= Qt.ItemFlag.ItemIsEditable
        if index.column() == 2:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        track = self.rows[index.row()]
        if track.id not in self.group_numbers:
            return False
        checked = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        warning = ""
        if checked:
            self.selected.add(track.id)
            group = next(g for g in self.library.groups if g.key == track.duplicate_key)
            all_selected = all(t.id in self.selected for t in group.tracks)
            if self.is_keeper(track):
                alternatives = [t for t in group.tracks if t.id != track.id]
                retained = next((t for t in alternatives if t.id not in self.selected), alternatives[0])
                self.keepers[group.key] = retained.id
                self.selected.discard(retained.id)
                if all_selected:
                    warning = (f'Alle Titel der Duplikatgruppe „{track.title}“ von {track.artist} wurden zum Entfernen markiert.\n\n'
                               f'Zum Schutz vor dem Löschen aller Exemplare bleibt „{retained.filename or retained.title}“ '
                               f'(ID: {retained.id}) erhalten. Seine Lösch-Markierung wurde aufgehoben.\n\n'
                               'Bitte die Auswahl dieser Gruppe prüfen. Mindestens ein Titel muss erhalten bleiben.')
        else:
            self.selected.discard(track.id)
        for row, item in enumerate(self.rows):
            if item.duplicate_key == track.duplicate_key:
                self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))
        self.selection_changed.emit()
        if warning:
            self.safety_warning.emit(warning)
        return True

    def keep(self, track: Track):
        if track.id not in self.group_numbers:
            return
        self.keepers[track.duplicate_key] = track.id
        self.selected.discard(track.id)
        self.refresh()

    def apply_recommendations(self):
        # Only groups currently visible in the filter are affected.
        visible = {t.duplicate_key for t in self.rows if t.id in self.group_numbers}
        for group in self.library.groups if self.library else ():
            if group.key in visible:
                self.keepers[group.key] = group.recommended_id
                self.selected.discard(group.recommended_id)
                self.selected.update(t.id for t in group.tracks if t.id != group.recommended_id)
        self.refresh()

    def clear_selection(self):
        self.selected.clear()
        self.refresh()

    def plan(self) -> RemovalPlan:
        by_id = self.library.by_id
        plan = RemovalPlan({i: self.keepers[by_id[i].duplicate_key] for i in sorted(self.selected)})
        validate_plan(self.library, plan)
        return plan

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.sort_column, self.sort_order = column, order
        self.refresh()

    def _sort_rows(self):
        def key(track):
            keys = [track.id in self.selected, track.title.casefold(), track.title.casefold(),
                    track.artist.casefold(), track.added, track.duration, track.bitrate,
                    track.playlist_text.casefold(), track.cues, self.is_keeper(track),
                    self.group_numbers.get(track.id, 0), track.filename.casefold()]
            if self.sort_column == 10:
                return keys[10], not self.is_keeper(track), track.title.casefold(), track.id
            return keys[self.sort_column], track.title.casefold(), track.id
        self.rows.sort(key=key, reverse=self.sort_order == Qt.SortOrder.DescendingOrder)


class TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    def run(self):
        try:
            result = self.function()
        except ManagerError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            if sys.stderr is not None:  # Windowed EXEs have no stderr stream.
                traceback.print_exc()
            self.signals.failed.emit(f"Der Vorgang konnte nicht abgeschlossen werden.\n\n{exc}")
        else:
            self.signals.done.emit(result)


class RemovalDialog(QDialog):
    def __init__(self, library: Library, plan: RemovalPlan, parent=None):
        super().__init__(parent)
        validate_plan(library, plan)
        self.setWindowTitle("Auswahl prüfen und entfernen")
        self.resize(880, 540)
        self.plan = plan
        self.library = library
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(label(f"{len(plan.replacements)} Duplikate entfernen", "heading"))
        layout.addWidget(label("Playlist-Einträge werden auf das jeweils behaltene Exemplar umgestellt. "
                               "Cues und Analyse des behaltenen Titels bleiben erhalten; Cues der entfernten "
                               "Titel werden nicht zusammengeführt.", "muted", True))
        review = QTableView()
        self.review_model = ReviewModel(library, plan)
        review.setModel(self.review_model)
        review.setWordWrap(False)
        review.setAlternatingRowColors(True)
        review.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        review.verticalHeader().hide()
        review.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(review, 1)
        self.file_info = label("Musikdateien werden automatisch in den Windows-Papierkorb verschoben.", "muted", True)
        layout.addWidget(self.file_info)
        self.backup_note = label(
            "Vor der Änderung wird ein vollständiges Datenbank-Backup mit Playlist-XML und Änderungsprotokoll erstellt.\n"
            f"Speicherort: {library.path.parent / 'RekordboxManager-Backups'}", "muted", True)
        self.backup_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.backup_note)
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setDefault(True)
        confirm = buttons.addButton("Backup erstellen und entfernen", QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.setObjectName("danger")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # Filesystem preview was computed in the background before opening this dialog.
        self.candidates: list[Path] = []
        self.file_notices: list[str] = []
        self.update_files()

    def update_files(self):
        self.file_info.setText(
            f"{len(self.candidates)} Musikdatei(en) werden automatisch in den Windows-Papierkorb verschoben. "
            "Weiter verwendete Dateien bleiben erhalten. Auf Laufwerken ohne Papierkorb bleiben Dateien erhalten.\n"
            "Das Datenbank-Backup enthält keine Musikdateien."
            + (f"\n{len(self.file_notices)} Datei(en) werden übersprungen; Gründe stehen im Hinweis zum Feld." if self.file_notices else ""))
        self.file_info.setToolTip("\n".join(self.file_notices) + "\n" + "\n".join(str(p) for p in self.candidates))


class ReviewModel(QAbstractTableModel):
    def __init__(self, library, plan):
        super().__init__()
        self.rows = [(library.by_id[removed], library.by_id[retained])
                     for removed, retained in plan.replacements.items()]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ["Titel / Interpret", "Entfernen · ID", "Behalten · ID", "Dateipfad des Duplikats"][section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        removed, retained = self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return [f"{removed.title} · {removed.artist}", removed.id, retained.id, removed.path][index.column()]


def removal_message(result: RemovalResult, parent=None) -> QMessageBox:
    box = QMessageBox(parent)
    box.setWindowTitle("Entfernung abgeschlossen mit Warnungen" if result.warnings else "Entfernung abgeschlossen")
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(f"{result.removed} Datenbankeinträge entfernt.\n"
                f"{len(result.trashed)} Musikdatei(en) in den Papierkorb verschoben.\n\n"
                f"Backup: {result.backup}")
    box.setIcon(QMessageBox.Icon.Warning if result.warnings else QMessageBox.Icon.Information)
    visible, details = [], []
    for heading, messages in (("Warnungen", result.warnings), ("Hinweise zu übersprungenen Dateien", result.notices)):
        if messages:
            visible.append(heading + ":\n" + "\n\n".join(messages[:3])
                           + (f"\n\n{len(messages) - 3} weitere Hinweise unter Details." if len(messages) > 3 else ""))
            details.append(heading + ":\n" + "\n\n".join(messages))
    if visible:
        box.setInformativeText("\n\n".join(visible))
    if len(result.warnings) > 3 or len(result.notices) > 3:
        box.setDetailedText("\n\n".join(details))
    return box


class MainWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None):
        super().__init__()
        self.setWindowTitle("Rekordbox Database Manager")
        self.resize(1470, 900)
        self.setMinimumSize(1100, 700)
        self.library: Library | None = None
        self.busy = False
        self.active_task = None
        self.last_backup: Path | None = None
        self.settings = app_settings()
        self.model = TrackModel()
        self.model.selection_changed.connect(self.update_summary)
        self.model.safety_warning.connect(self.show_safety_warning)
        self.preview = AudioPreview(self)
        self._build()
        self.preview.changed.connect(self.preview_changed)
        self.preview.failed.connect(lambda message: QMessageBox.warning(self, "Hörprobe nicht möglich", message))
        self.model.modelReset.connect(self.reset_details)
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.startup_path = initial_path or self.settings.value("last_database", "", type=str)
        self.explicit_startup_path = bool(initial_path)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self.open_startup_database)
        self.startup_timer.start(0)

    def _build(self):
        container = QWidget()
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(container)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 30, 18, 24)
        side.setSpacing(8)
        side.addWidget(label("RB /", "brand"))
        side.addWidget(label("DATABASE MANAGER", "eyebrow"))
        side.addSpacing(38)
        side.addWidget(label("VERWALTUNG", "muted"))
        self.all_button = button("♫   Alle Titel", lambda: self.set_view(False), "nav")
        self.dupes_button = button("≋   Doppelte Titel", lambda: self.set_view(True), "nav")
        nav = QButtonGroup(self)
        for widget in (self.all_button, self.dupes_button):
            widget.setCheckable(True)
            nav.addButton(widget)
            side.addWidget(widget)
        self.dupes_button.setChecked(True)
        side.addStretch()
        side.addWidget(label("DEINE SAMMLUNG", "eyebrow"))
        side.addWidget(label("Überblick behalten.\nDuplikate prüfen.\nGezielt aufräumen.", "muted", True))
        side.addSpacing(18)
        side.addWidget(button("Kurzanleitung", self.show_help))
        side.addWidget(label(f"v{__version__} · Windows", "muted"))
        outer.addWidget(sidebar)

        main = QWidget()
        content = QVBoxLayout(main)
        content.setContentsMargins(28, 26, 28, 20)
        content.setSpacing(16)
        top = QHBoxLayout()
        self.heading = label("Doppelte Titel", "heading")
        top.addWidget(self.heading)
        top.addStretch()
        self.reload_button = button("Neu laden", self.reload_database)
        self.reload_button.setEnabled(False)
        self.open_button = button("Datenbank öffnen…", self.choose_database, "primary")
        top.addWidget(self.reload_button)
        top.addWidget(self.open_button)
        content.addLayout(top)
        self.description = label("Gleicher Titel + Interpret. Mix-Bezeichnungen bleiben berücksichtigt.", "muted")
        content.addWidget(self.description)
        self.path_label = label("Keine Sammlung geöffnet · Wähle eine master.db auf deinem PC oder einem externen Laufwerk.", "muted", True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(self.path_label)
        stats = QHBoxLayout()
        self.total_stat = self._stat(stats, "TITEL IN DER SAMMLUNG")
        self.dupe_stat = self._stat(stats, "DUPLIKATGRUPPEN")
        self.selected_stat = self._stat(stats, "ZUM ENTFERNEN MARKIERT")
        content.addLayout(stats)

        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Titel, Interpret oder Dateipfad suchen…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_rows)
        tools.addWidget(self.search, 1)
        self.recommend_button = button("Vorschläge übernehmen", self.model.apply_recommendations)
        self.recommend_button.setToolTip("Höchste Bitrate behalten; bei Gleichstand Titel mit Playlist-Zugehörigkeit bevorzugen. Wirkt auf sichtbare Gruppen.")
        self.clear_button = button("Auswahl leeren", self.model.clear_selection)
        tools.addWidget(self.recommend_button)
        tools.addWidget(self.clear_button)
        content.addLayout(tools)

        self.splitter = QSplitter()
        table_area = QWidget()
        table_layout = QVBoxLayout(table_area)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(TrackDelegate(self.table))
        self.title_delegate = TitleDelegate(self.table)
        self.title_delegate.title_submitted.connect(self.save_title)
        self.table.setItemDelegateForColumn(2, self.title_delegate)
        self.table.setItemDelegateForColumn(7, PlaylistDelegate(self.table))
        palette = self.table.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#28433f"))
        self.table.setPalette(palette)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(46, 46))
        self.table.verticalHeader().setDefaultSectionSize(60)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col, width in {0: 75, 1: 62, 3: 145, 4: 105, 5: 60, 6: 110, 7: 170, 8: 50, 9: 128, 10: 65, 11: 180}.items():
            self.table.setColumnWidth(col, width)
        # Additional technical metadata is available in the detail panel.
        for col in (5, 8):
            self.table.setColumnHidden(col, True)
        # Show the main track columns first, followed by selection and filename.
        header = self.table.horizontalHeader()
        for position, column in enumerate((10, 0, 1, 2, 3, 7, 6, 4, 9, 11, 5, 8)):
            header.moveSection(header.visualIndex(column), position)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(10, Qt.SortOrder.AscendingOrder)
        self.table.selectionModel().currentRowChanged.connect(self.show_track)
        self.table.clicked.connect(self.cover_clicked)
        self.table.clicked.connect(self.show_playlist_dropdown)
        self.table.activated.connect(self.show_playlist_dropdown)
        self.empty_label = label("Öffne eine Sammlung, um ihre Titel und mögliche Duplikate zu prüfen.", "muted", True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        table_layout.addWidget(self.table, 1)
        table_layout.addWidget(self.empty_label)
        self.splitter.addWidget(table_area)
        self.detail = QFrame()
        self.detail.setMinimumWidth(220)
        self.detail.setObjectName("card")
        detail = QVBoxLayout(self.detail)
        detail.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        detail.setContentsMargins(18, 20, 18, 20)
        detail.setSpacing(12)
        detail.addWidget(label("TITELDETAILS", "eyebrow"))
        self.detail_cover = CoverLabel()
        self.detail_cover.clicked.connect(self.preview_current)
        self.detail_cover.setFixedSize(150, 150)
        self.detail_cover.setPixmap(placeholder(150))
        detail.addWidget(self.detail_cover)
        self.detail_title = label("Titel auswählen", "detailTitle", True)
        self.detail_artist = label("", "muted", True)
        self.detail_meta = label("", "muted", True)
        self.detail_filename = label("", wrap=True)
        self.detail_filename.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_filename.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_playlists = label("", "muted", True)
        self.detail_playlists.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_path = label("", "muted", True)
        self.detail_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_reason = label("", "muted", True)
        for widget in (self.detail_title, self.detail_artist, self.detail_meta, self.detail_playlists,
                       self.detail_filename, self.detail_path, self.detail_reason):
            detail.addWidget(widget)
        detail.addStretch()
        self.keep_button = button("Diesen Titel behalten", self.keep_current, "primary")
        self.keep_button.setEnabled(False)
        detail.addWidget(self.keep_button)
        detail.addWidget(label("Höchste Bitrate wird empfohlen, bei Gleichstand ein Titel in Playlists. "
                               "Sind alle Exemplare angekreuzt, erscheint eine Warnung und ein Titel bleibt geschützt.", "muted", True))
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setMinimumWidth(250)
        self.detail_scroll.setMaximumWidth(310)
        self.detail_scroll.setWidget(self.detail)
        self.splitter.addWidget(self.detail_scroll)
        self.splitter.setSizes([980, 250])
        content.addWidget(self.splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        content.addWidget(self.progress)
        footer = QHBoxLayout()
        self.summary = label("Noch keine Sammlung geöffnet.", "muted", True)
        footer.addWidget(self.summary, 1)
        self.backup_button = button("Backups öffnen", self.open_backups)
        self.backup_button.setEnabled(False)
        self.remove_button = button("Auswahl prüfen & entfernen…", self.review_removal, "danger")
        self.remove_button.setEnabled(False)
        footer.addWidget(self.backup_button)
        footer.addWidget(self.remove_button)
        content.addLayout(footer)
        playback = QHBoxLayout()
        self.preview_info = label("", "muted", True)
        self.preview_info.setTextFormat(Qt.TextFormat.PlainText)
        self.stop_preview_button = button("Hörprobe stoppen", self.preview.stop)
        self.preview_info.hide()
        self.stop_preview_button.hide()
        playback.addWidget(self.preview_info, 1)
        playback.addWidget(self.stop_preview_button)
        content.addLayout(playback)
        self.status_label = label("Bereit · Änderungen werden erst nach Prüfung der Auswahl gespeichert.", "muted", True)
        content.addWidget(self.status_label)
        outer.addWidget(main, 1)
        self.update_summary()

    def _stat(self, layout, title):
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.addWidget(label(title, "muted"))
        value = label("–", "statNumber")
        box.addWidget(value)
        layout.addWidget(card)
        return value

    def set_view(self, duplicates_only):
        self.model.duplicates_only = duplicates_only
        self.heading.setText("Doppelte Titel" if duplicates_only else "Alle Titel")
        self.description.setText("Gleicher Titel + Interpret. Mix-Bezeichnungen bleiben berücksichtigt."
                                 if duplicates_only else "Deine Sammlung mit Cover, Titel, Interpret und Hinzufügedatum.")
        self.model.refresh()
        self.reset_details()

    def filter_rows(self, text):
        self.model.search = text
        self.model.refresh()
        self.reset_details()

    def choose_database(self):
        def discovered(path):
            if path and (not self.library or self.library.path != path.resolve()):
                self.open_database(str(path), discovered=True)
            else:
                # Already-open discoveries still leave other databases selectable.
                self.choose_database_file(path)

        self.run_task(default_database, discovered, "master.db wird über die Rekordbox-Einstellungen gesucht…")

    def choose_database_file(self, discovered=None):
        last = self.settings.value("last_database", "")
        suggested = str(discovered) if discovered else last or str(Path.home())
        self.status_label.setText("Gefundene Sammlung ist bereits geöffnet · Andere master.db auswählen."
                                  if discovered else "Keine verwendbare master.db über die Rekordbox-Einstellungen gefunden · Bitte manuell auswählen.")
        path, _ = QFileDialog.getOpenFileName(self, "Rekordbox master.db auswählen", suggested,
                                              "Rekordbox-Datenbank (*.db);;Alle Dateien (*)")
        if path:
            self.open_database(path)

    def open_startup_database(self):
        if self.library or self.busy:
            return
        if self.explicit_startup_path:
            self.open_database(self.startup_path)
            return
        path = self.startup_path

        def read_remembered():
            # External drives can be slow or disconnected; check off the UI thread.
            if path and Path(path).is_file():
                return load_library(path)
            found = default_database()
            return load_library(found) if found else None

        def startup_loaded(library):
            if library is not None:
                self.loaded(library)
            else:
                self.path_label.setText(f"Zuletzt verwendete Datenbank nicht erreichbar: {path}" if path else
                                        "Keine master.db über die Rekordbox-Einstellungen gefunden.")
                self.path_label.setToolTip(path)
                self.status_label.setText("Keine erreichbare master.db gefunden · Bitte über „Datenbank öffnen“ auswählen.")

        self.run_task(read_remembered, startup_loaded, "Gespeicherter Pfad und Rekordbox-Einstellungen werden geprüft…")

    def open_database(self, path, *, discovered=False):
        if self.model.selected:
            answer = QMessageBox.question(self, "Auswahl verwerfen?", "Die aktuelle Markierung zum Entfernen verwerfen und die Datenbank laden?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        def discovery_failed(message):
            self.task_finished()
            self.choose_database_file()

        self.run_task(lambda: load_library(path), self.loaded, "Sammlung wird gelesen und geprüft…",
                      failure=discovery_failed if discovered else None)

    def reload_database(self):
        if self.library:
            self.open_database(str(self.library.path))

    def loaded(self, library):
        self.startup_timer.stop()
        self.preview.stop()
        self.library = library
        self.model.set_library(library)
        self.path_label.setText(str(library.path))
        self.path_label.setToolTip(str(library.path))
        self.settings.setValue("last_database", str(library.path))
        self.settings.sync()
        self.reset_details()
        excluded = sum(1 for t in library.tracks if t.duplicate_key is None)
        self.status_label.setText(
            f"Sammlung geladen · {len(library.tracks)} Titel · {len(library.groups)} Duplikatgruppen."
            + (f" {excluded} Titel ohne Titel/Interpret werden bei der Duplikatsuche ausgelassen." if excluded else ""))
        self.update_summary()

    def run_task(self, function, callback, status, *, failure=None):
        if self.busy:
            return
        self.startup_timer.stop()
        self.preview.stop()
        self.busy = True
        self.set_controls()
        self.progress.show()
        self.status_label.setText(status)
        task = Task(function)
        self.active_task = task

        def done(result):
            self.task_finished()
            callback(result)

        task.signals.done.connect(done)
        task.signals.failed.connect(failure or self.task_failed)
        QThreadPool.globalInstance().start(task)

    def task_finished(self):
        self.busy = False
        self.progress.hide()
        self.active_task = None
        self.set_controls()

    def task_failed(self, message):
        self.task_finished()
        self.status_label.setText("Vorgang abgebrochen · " + message.split("\n")[0])
        QMessageBox.warning(self, "Vorgang nicht abgeschlossen", message)

    def set_controls(self):
        for widget in (self.open_button, self.search, self.table, self.all_button, self.dupes_button):
            widget.setEnabled(not self.busy)
        self.reload_button.setEnabled(bool(self.library) and not self.busy)
        self.recommend_button.setEnabled(bool(self.library and self.library.groups) and not self.busy)
        self.clear_button.setEnabled(bool(self.model.selected) and not self.busy)
        self.remove_button.setEnabled(bool(self.model.selected) and not self.busy)
        self.keep_button.setEnabled(self.current_track() is not None and not self.busy and
                                    self.current_track().id in self.model.group_numbers)
        self.backup_button.setEnabled(bool(self.library) and not self.busy)

    def update_summary(self):
        if not hasattr(self, "summary"):
            return
        count = len(self.model.selected)
        if self.library:
            self.total_stat.setText(f"{len(self.library.tracks):,}".replace(",", "."))
            self.dupe_stat.setText(str(len(self.library.groups)))
            self.selected_stat.setText(str(count))
            visible = {t.id for t in self.model.rows}
            hidden = len(self.model.selected - visible)
            self.summary.setText(f"{len(self.model.rows)} Titel angezeigt · {count} zum Entfernen markiert"
                                 + (f" · davon {hidden} außerhalb des Filters" if hidden else ""))
            if not self.model.rows:
                self.empty_label.setText("Keine Treffer für diesen Filter." if self.search.text() else
                                         "Keine doppelten Titel gefunden." if self.model.duplicates_only else "Diese Sammlung enthält keine Titel.")
        self.empty_label.setVisible(not self.model.rows)
        self.set_controls()

    def current_track(self):
        index = self.table.currentIndex()
        return self.model.rows[index.row()] if index.isValid() and index.row() < len(self.model.rows) else None

    def reset_details(self):
        self.table.clearSelection()
        self.table.setCurrentIndex(QModelIndex())
        self.detail_cover.setPixmap(placeholder(150))
        self.detail_title.setText("Titel auswählen")
        for widget in (self.detail_artist, self.detail_meta, self.detail_playlists,
                       self.detail_filename, self.detail_path, self.detail_reason):
            widget.clear()
        self.detail_filename.setStyleSheet("")
        self.detail_title.setStyleSheet("")
        self.keep_button.setEnabled(False)

    def show_track(self, current, previous=QModelIndex()):
        track = self.current_track()
        if not track:
            return
        pixmap = QPixmap(track.cover) if track.cover else placeholder(150)
        if pixmap.isNull():
            pixmap = placeholder(150)
        self.detail_cover.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        self.detail_title.setText(track.title or "Ohne Titel")
        playlist_duplicate = track.playlists and track.id in self.model.group_numbers
        self.detail_title.setStyleSheet("color: #ef8f93;" if playlist_duplicate else "")
        self.detail_artist.setText(track.artist or "Unbekannter Interpret")
        self.detail_filename.setText(track.filename or "–")
        self.detail_filename.setStyleSheet("color: #ef8f93;" if playlist_duplicate else
                                          "color: #8aefce;" if not track.playlists else "")
        self.detail_playlists.setText("Playlists:\n" + "\n".join(track.playlist_names)
                                      if track.playlists else "Keine Playlist")
        self.detail_meta.setText(f"Hinzugefügt  {display_date(track.added)}\n"
                                 f"Länge  {track.duration_text} · {track.bitrate or '–'} kbit/s\n"
                                 f"{track.playlists} Playlist-Einträge · {track.cues} Cues\n"
                                 f"ID  {track.id}")
        self.detail_path.setText(("Datei erreichbar\n" if track.available else "Datei nicht erreichbar\n") + track.path)
        self.detail_reason.setText(
            "Behalten-Empfehlung\nPriorität: höchste Bitrate → in Playlists enthalten. "
            "Bei weiterem Gleichstand: Datei erreichbar → Cues → ältestes Hinzufügedatum → Titel-ID. "
            "Die Empfehlung lässt sich manuell ändern."
            if track.id in self.model.recommended else "")
        self.keep_button.setEnabled(track.id in self.model.group_numbers and not self.busy)

    def keep_current(self):
        track = self.current_track()
        if track:
            self.model.keep(track)
            self.reset_details()

    def show_safety_warning(self, message):
        QMessageBox.warning(self, "Mindestens einen Titel behalten", message)

    def cover_clicked(self, index):
        if index.isValid() and index.column() == 1 and not self.busy:
            self.preview.toggle(self.model.rows[index.row()])

    def show_playlist_dropdown(self, index):
        if (index.isValid() and index.column() == 7 and not self.busy
                and len(index.data(TrackModel.PLAYLIST_NAMES_ROLE) or ()) > 1):
            self.table.edit(index)

    def save_title(self, track_id, title):
        if self.busy or not self.library or track_id not in self.library.by_id:
            return
        if title.strip() == self.library.by_id[track_id].title:
            return
        library = self.library
        self.run_task(lambda: rename_track(library, track_id, title), self.title_saved,
                      "Titel und Dateiverknüpfung werden gespeichert…")

    def title_saved(self, result):
        old_path = self.library.path
        # A changed title can create or split duplicate groups. Reset removal
        # choices before adopting the new snapshot or falling back to a reload.
        self.library = None
        self.model.library = None
        self.model.clear_selection()
        self.reset_details()

        def refreshed(library):
            self.loaded(library)
            for row, track in enumerate(self.model.rows):
                if track.id == result.track_id:
                    self.table.setCurrentIndex(self.model.index(row, 2))
                    break
            self.status_label.setText(f"Titel gespeichert · {result.path.name} · Duplikatgruppen neu geprüft")
            if result.warnings:
                QMessageBox.warning(self, "Titel gespeichert", "\n\n".join(result.warnings))

        def refresh_failed(message):
            self.task_finished()
            self.status_label.setText("Titel gespeichert · Erneutes Laden der Sammlung fehlgeschlagen")
            QMessageBox.warning(self, "Titel gespeichert · Neu laden nötig",
                                f"Der Titel und die Dateiverknüpfung wurden gespeichert:\n{result.path}\n\n"
                                f"Die Sammlung konnte anschließend nicht neu geladen werden. "
                                f"Bitte „Datenbank öffnen“ verwenden.\n\n{message}\n\nProtokoll: {result.journal}")

        if result.library is not None:
            refreshed(result.library)
        else:
            self.run_task(lambda: load_library(old_path), refreshed, "Aktualisierte Sammlung wird geladen…",
                          failure=refresh_failed)

    def preview_current(self):
        track = self.current_track()
        if track and not self.busy:
            self.preview.toggle(track)

    def preview_changed(self, track):
        self.preview_info.setVisible(track is not None)
        self.stop_preview_button.setVisible(track is not None)
        self.preview_info.setText(f"Hörprobe ab Mitte: {track.title} · {track.artist}" if track else "")

    def review_removal(self):
        if not self.library or not self.model.selected:
            return
        library = self.library
        try:
            plan = self.model.plan()
        except ManagerError as exc:
            self.show_safety_warning(str(exc))
            return

        def preview_done(preview):
            dialog = RemovalDialog(library, plan, self)
            dialog.candidates, dialog.file_notices = preview
            dialog.update_files()
            if dialog.exec() == QDialog.DialogCode.Accepted:
                final_plan = RemovalPlan(dict(plan.replacements))
                self.run_task(lambda: remove_duplicates(library, final_plan), self.removed,
                              "Backup wird erstellt, Duplikate werden entfernt…")
            else:
                self.status_label.setText("Prüfung abgebrochen · Die Auswahl bleibt markiert.")

        self.run_task(lambda: audio_candidates(library, plan), preview_done, "Auswahl und Musikdateien werden geprüft…")

    def removed(self, result):
        self.last_backup = result.backup
        self.model.clear_selection()
        # Disable further writes until the freshly committed database is loaded.
        old_path = self.library.path
        self.library = None
        self.model.library = None
        self.model.refresh()
        self.reset_details()
        box = removal_message(result, self)
        box.exec()
        self.run_task(lambda: load_library(old_path), self.loaded, "Aktualisierte Sammlung wird geladen…")

    def open_backups(self):
        root = self.last_backup or (self.library.path.parent / "RekordboxManager-Backups" if self.library else None)
        if root and root.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))
        else:
            QMessageBox.information(self, "Backups", "Ein Datenbank-Backup wird automatisch vor jeder Entfernung erstellt.")

    def show_help(self):
        QMessageBox.information(
            self, "Kurzanleitung",
            "1. master.db öffnen (PC oder externes Laufwerk).\n"
            "   Beim nächsten Start wird die zuletzt geöffnete Datenbank automatisch geladen, sofern sie erreichbar ist.\n"
            "   Andernfalls wird zuerst über die Rekordbox-Einstellungen gesucht, bevor eine manuelle Auswahl nötig ist.\n"
            "2. Doppelte Titel prüfen. Gruppennummer und gemeinsame Hintergrundfarbe verbinden zusammengehörige Einträge.\n"
            "3. Bei Bedarf einen Titel wählen und „Diesen Titel behalten“ anklicken.\n"
            "4. Exemplare per Kontrollkästchen markieren oder „Vorschläge übernehmen“ nutzen. Auch der Behalten-Titel ist auswählbar; dann wird ein anderes Exemplar behalten.\n"
            "5. „Auswahl prüfen & entfernen“ zeigt die komplette Auswahl zur Bestätigung.\n\n"
            "Die Spalte „Auswahl“ zeigt den Behalten-/Entfernen-Status. Zum Löschen markierte Zeilen und Kontrollkästchen sind rot.\n"
            "In allen betroffenen Playlists ersetzt der behaltene Titel die gelöschten Exemplare an derselben Position.\n\n"
            "Empfehlung: höchste Bitrate, bei Gleichstand ein Titel in Playlists. Playlist-Duplikate sind rot markiert.\n"
            "Sind alle Exemplare einer Gruppe markiert, wird gewarnt und ein Exemplar bleibt geschützt.\n"
            "Klick auf ein Cover spielt ab der Mitte; erneuter Klick auf dasselbe Cover stoppt die Hörprobe.\n\n"
            "Doppelklick auf einen Titelnamen: bearbeiten. Return speichert den Titel und benennt die Datei nach "
            "„Interpret - Titel“ mit ihrer bisherigen Dateiendung um. Escape oder Verlassen des Feldes bricht ab. "
            "Dateiverknüpfungen werden aktualisiert und Duplikatgruppen neu geprüft; die Lösch-Auswahl wird zurückgesetzt.\n\n"
            "Die Suche ignoriert Groß-/Kleinschreibung und überzählige Leerzeichen. "
            "Mix-Namen und Satzzeichen bleiben relevant. Gleiche Metadaten garantieren keinen identischen Audioinhalt.\n\n"
            "Vorschläge übernehmen wirkt auf sichtbare Gruppen; eine gefilterte Duplikatgruppe bleibt vollständig sichtbar. "
            "Markierungen außerhalb des Filters werden in der Fußzeile gezählt und vor dem Entfernen ebenfalls angezeigt.\n\n"
            "Vor Änderungen Rekordbox und Rekordbox Agent schließen. Musikdateien werden beim Entfernen automatisch "
            "in den Papierkorb verschoben; ein Datenbank-Backup enthält keine Musikdateien.")

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, "Vorgang läuft", "Bitte den laufenden Vorgang abwarten, bevor die App geschlossen wird.")
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.sync()
        self.startup_timer.stop()
        self.preview.stop()
        event.accept()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Rekordbox Database Manager")
    parser.add_argument("database", nargs="?", help="Optionaler Pfad zu einer master.db")
    args = parser.parse_args(argv)
    app = QApplication(sys.argv[:1])
    ensure_fonts()
    app.setApplicationName("Rekordbox Database Manager")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(placeholder(64)))
    window = MainWindow(args.database)
    window.show()
    return app.exec()
