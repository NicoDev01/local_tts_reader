"""All settings on one calm page, grouped like system settings."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from settings import PROFILES, VOICES
from ui_theme import Theme, app_icon
from ui_widgets import IconButton, KeyCaps, Segmented, Switch, card, divider
from windows_runtime import set_dark_title_bar

THEMES = {"system": "System", "light": "Hell", "dark": "Dunkel"}


class SettingsWindow(QWidget):
    control_changed = Signal(str, float)     # speed / volume
    choice_changed = Signal(str, str)        # voice / sound_profile / theme
    toggle_changed = Signal(str, bool)       # hud_enabled / autostart
    preview_voice = Signal()
    read_text = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.setObjectName("SettingsWindow")
        self.setWindowTitle("Vorleser")
        self.setWindowIcon(app_icon())
        self.resize(480, 780)
        self.setMinimumSize(420, 520)
        self.config = config
        self._building = True
        self._build()
        self._building = False

    # -- structure ----------------------------------------------------------------
    def _build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        scroll.setWidget(page)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        v = QVBoxLayout(page)
        v.setContentsMargins(24, 22, 24, 22)
        v.setSpacing(6)
        title = QLabel("Vorleser")
        title.setObjectName("Title")
        self.status = QLabel()
        self.status.setObjectName("Secondary")
        self.status.setWordWrap(True)
        v.addWidget(title)
        v.addWidget(self.status)
        v.addSpacing(14)

        c = self.config
        self.voice = self._combo(VOICES, c["voice"], "voice")
        preview = IconButton("play", 30, 13, tooltip="Hörprobe dieser Stimme")
        preview.clicked.connect(self.preview_voice)
        self.speed, self.speed_value = self._slider("speed", 70, 200, c["speed"])
        self.volume, self.volume_value = self._slider("volume", 0, 150, c["volume"])
        self.profile = self._combo(PROFILES, c["sound_profile"], "sound_profile")
        self._section(v, "Wiedergabe", [
            ("Stimme", [self.voice, preview]),
            ("Tempo", [self.speed, self.speed_value]),
            ("Lautstärke", [self.volume, self.volume_value]),
            ("Klang", [self.profile]),
        ])

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Text einfügen und mit Strg + Enter vorlesen")
        self.editor.setFixedHeight(92)
        read = QPushButton("Vorlesen")
        read.setObjectName("Primary")
        read.setCursor(Qt.CursorShape.PointingHandCursor)
        read.clicked.connect(self._read_editor)
        QShortcut(QKeySequence("Ctrl+Return"), self.editor, activated=self._read_editor)
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 8, 12, 12)
        bl.addWidget(self.editor)
        bl.addWidget(read, 0, Qt.AlignmentFlag.AlignRight)
        self._label(v, "Eigener Text")
        v.addWidget(box)
        v.addSpacing(14)

        self.hud = Switch()
        self.hud.setChecked(c["hud_enabled"])
        self.hud.toggled.connect(lambda on: self.toggle_changed.emit("hud_enabled", on))
        self.autostart = Switch()
        self.autostart.setChecked(c["autostart"])
        self.autostart.toggled.connect(lambda on: self.toggle_changed.emit("autostart", on))
        self.theme = Segmented(THEMES)
        self.theme.set_value(c["theme"])
        self.theme.changed.connect(lambda key: self.choice_changed.emit("theme", key))
        self._section(v, "Allgemein", [
            ("Mini-Player beim Vorlesen", [self.hud]),
            ("Mit Windows starten", [self.autostart]),
            ("Darstellung", [self.theme]),
        ])

        self._section(v, "Tastenkürzel", [
            ("Markierten Text vorlesen", [KeyCaps(c["hotkey"])]),
            ("Pause / Weiter", [KeyCaps(c["pause_hotkey"])]),
            ("Vorlesen beenden", [KeyCaps(c["stop_hotkey"])]),
        ])

        footer = QLabel("Die Sprache wird online über Microsoft erzeugt. Das Fenster zu schließen lässt den "
                        "Vorleser im Infobereich weiterlaufen.")
        footer.setObjectName("Footer")
        footer.setWordWrap(True)
        v.addWidget(footer)
        v.addStretch(1)

    def _label(self, layout, text):
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        layout.addWidget(label)

    def _section(self, layout, title, rows):
        self._label(layout, title)
        box = card()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 2, 10, 2)
        bl.setSpacing(0)
        for i, (name, widgets) in enumerate(rows):
            if i:
                bl.addWidget(divider())
            row = QHBoxLayout()
            row.setContentsMargins(0, 9, 0, 9)
            row.addWidget(QLabel(name))
            row.addStretch(1)
            for widget in widgets:
                row.addWidget(widget)
            bl.addLayout(row)
        layout.addWidget(box)
        layout.addSpacing(14)

    def _combo(self, choices, current, key):
        combo = QComboBox()
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for value, label in choices.items():
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(
            lambda _i: self._building or self.choice_changed.emit(key, combo.currentData()))
        return combo

    def _slider(self, key, low, high, value):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(5)
        slider.setPageStep(10)
        slider.setFixedWidth(170)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        label = QLabel()
        label.setObjectName("Value")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.setValue(round(value * 100))
        slider.valueChanged.connect(lambda v: self._building or self.control_changed.emit(key, v / 100))
        self._format(key, label, value)
        return slider, label

    @staticmethod
    def _format(key, label, value):
        if key == "speed":
            label.setText(f"{value:.2f}".replace(".", ",") + "×")
        else:
            label.setText(f"{round(value * 100)} %")

    def _read_editor(self):
        self.read_text.emit(self.editor.toPlainText())

    # -- updates from the app ------------------------------------------------------
    def set_controls(self, speed, volume):
        self._building = True
        for key, slider, label, value in (("speed", self.speed, self.speed_value, speed),
                                          ("volume", self.volume, self.volume_value, volume)):
            if slider.value() != round(value * 100):
                slider.setValue(round(value * 100))
            self._format(key, label, value)
        self._building = False

    def set_status(self, text):
        self.status.setText(text)

    def set_autostart(self, enabled):
        self.autostart.blockSignals(True)
        self.autostart.setChecked(enabled)
        self.autostart.blockSignals(False)

    def refresh_theme(self):
        set_dark_title_bar(int(self.winId()), Theme.dark())
        for widget in self.findChildren(QWidget):
            widget.update()

    def showEvent(self, event):
        set_dark_title_bar(int(self.winId()), Theme.dark())
        super().showEvent(event)

    def closeEvent(self, event):
        event.ignore()  # stay in the tray
        self.hide()
