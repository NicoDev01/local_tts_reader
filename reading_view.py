"""Reading view: the whole text, the current sentence and word marked; click a sentence to jump."""
import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from ui_theme import Theme, app_icon
from ui_widgets import IconButton
from windows_runtime import set_window_chrome


def _mix(color, background, amount):
    a, b = QColor(color), QColor(background)
    return QColor(round(b.red() + (a.red() - b.red()) * amount), round(b.green() + (a.green() - b.green()) * amount),
                  round(b.blue() + (a.blue() - b.blue()) * amount)).name()


class ReadingView(QWidget):
    jump = Signal(int)
    toggle_pause = Signal()
    previous = Signal()
    next = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("SettingsWindow")  # same window background
        self.setWindowTitle("Leseansicht")
        self.setWindowIcon(app_icon())
        self.resize(640, 720)
        self.setMinimumSize(420, 360)
        self.units, self.unit, self.word = [], -1, None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("Leseansicht")
        title.setObjectName("Title")
        self.hint = QLabel("Satz anklicken, um dort weiterzulesen")
        self.hint.setObjectName("Secondary")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(title)
        titles.addWidget(self.hint)
        header.addLayout(titles, 1)
        self.prev_btn = IconButton("skip-back", 32, 14, tooltip="Vorheriger Satz")
        self.play_btn = IconButton("pause", 38, 15, filled=True, tooltip="Pause / Weiter")
        self.next_btn = IconButton("skip-forward", 32, 14, tooltip="Nächster Satz")
        self.prev_btn.clicked.connect(self.previous)
        self.play_btn.clicked.connect(self.toggle_pause)
        self.next_btn.clicked.connect(self.next)
        for button in (self.prev_btn, self.play_btn, self.next_btn):
            header.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        self.browser = QTextBrowser()
        self.browser.setObjectName("Reader")
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self._clicked)
        self.browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.browser.document().setDocumentMargin(26)
        root.addWidget(self.browser, 1)

    def _clicked(self, url):
        if url.toString().startswith("u:"):
            self.jump.emit(int(url.toString()[2:]))

    def set_paused(self, paused):
        self.play_btn.set_icon("play" if paused else "pause")

    def show_text(self, units, unit, word=None):
        """Render when the sentence or word changed; scroll only when the sentence changed."""
        if units is self.units and unit == self.unit and word == self.word:
            return
        sentence_changed = units is not self.units or unit != self.unit
        self.units, self.unit, self.word = units, unit, word
        bar = self.browser.verticalScrollBar()
        keep = bar.value()
        self.browser.setHtml(self._html())
        if sentence_changed and unit >= 0:
            self.browser.scrollToAnchor(f"s{unit}")
            bar.setValue(max(0, bar.value() - self.browser.viewport().height() // 3))
        else:
            bar.setValue(keep)

    def _html(self):
        c = Theme.colors
        marked = _mix(c["accent"], c["card"], .14)
        paragraphs, current = [], []
        for i, unit in enumerate(self.units):
            text = " ".join(unit.split())
            if i == self.unit and self.word:
                at, length = self.word
                body = (html.escape(text[:at]) + f'<span style="color:{c["accent"]};">'
                        + html.escape(text[at:at + length]) + "</span>" + html.escape(text[at + length:]))
            else:
                body = html.escape(text)
            color = c["secondary"] if i < self.unit else c["text"]
            background = f"background-color:{marked};" if i == self.unit else ""
            current.append(f'<a name="s{i}"></a><a href="u:{i}" style="color:{color}; text-decoration:none; '
                           f'{background}">{body}</a>')
            if unit.endswith("\n\n") or i == len(self.units) - 1:
                paragraphs.append('<p style="margin-bottom:14px; line-height:160%;">' + " ".join(current) + "</p>")
                current = []
        return (f'<div style="font-size:13pt; color:{c["text"]};">' + "".join(paragraphs) + "</div>")

    def refresh_theme(self):
        self._chrome()
        units, self.units = self.units, []
        self.show_text(units, self.unit, self.word)

    def _chrome(self):
        set_window_chrome(int(self.winId()), Theme.dark(), Theme.colors["window"], Theme.colors["text"])

    def showEvent(self, event):
        self._chrome()
        super().showEvent(event)
