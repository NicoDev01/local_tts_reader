"""Small painted controls shared by the settings window and the mini-player."""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from ui_theme import Theme, paint_icon, ui_font


class IconButton(QAbstractButton):
    """Round, borderless icon button; ``filled`` draws the primary disc."""

    def __init__(self, icon, size=28, icon_size=16, filled=False, tooltip="", parent=None):
        super().__init__(parent)
        self.icon_name, self.icon_size, self.filled = icon, icon_size, filled
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tooltip)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_icon(self, name):
        if name != self.icon_name:
            self.icon_name = name
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        if self.filled:
            color = Theme.color("primary", .85 if self.isDown() else 1.0)
            p.setBrush(color)
            p.drawEllipse(rect)
            fg = Theme.color("on_primary")
        else:
            if self.underMouse():
                p.setBrush(Theme.color("hover") if not self.isDown() else Theme.color("control"))
                p.drawEllipse(rect)
            fg = Theme.color("text" if self.isEnabled() else "muted")
        s = self.icon_size
        icon = QRectF((rect.width() - s) / 2, (rect.height() - s) / 2, s, s)
        if self.icon_name == "play" and self.filled:
            icon.translate(s * .06, 0)  # optical centering of the triangle
        paint_icon(p, self.icon_name, icon, fg)


class Switch(QAbstractButton):
    """iOS-style toggle with an eased knob."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked):
        super().setChecked(checked)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def get_knob(self):
        return self._pos

    def set_knob(self, value):
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):
        return QSize(38, 22)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        off, on = Theme.color("track"), Theme.color("primary")
        t = self._pos
        track = off.toRgb()
        track.setRgbF(off.redF() + (on.redF() - off.redF()) * t, off.greenF() + (on.greenF() - off.greenF()) * t,
                      off.blueF() + (on.blueF() - off.blueF()) * t)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, 38, 22), 11, 11)
        p.setBrush(Theme.color("on_primary") if t > .5 else Theme.color("card"))
        p.drawEllipse(QRectF(2 + 16 * t, 2, 18, 18))


class Segmented(QWidget):
    """Segmented control (System / Hell / Dunkel)."""
    changed = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.options = list(options.items())  # [(key, label)]
        self.value = self.options[0][0]
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(ui_font(9))
        widths = [self.fontMetrics().horizontalAdvance(label) + 24 for _, label in self.options]
        self.setFixedWidth(sum(widths) + 4)
        self._widths = widths

    def set_value(self, key):
        self.value = key
        self.update()

    def _segments(self):
        x = 2.0
        for (key, label), width in zip(self.options, self._widths):
            yield key, label, QRectF(x, 2, width, self.height() - 4)
            x += width

    def mousePressEvent(self, event):
        for key, _, rect in self._segments():
            if rect.contains(event.position()) and key != self.value:
                self.set_value(key)
                self.changed.emit(key)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Theme.color("control"))
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        for key, label, rect in self._segments():
            if key == self.value:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(Theme.color("card"))
                p.drawRoundedRect(rect, 6, 6)
            p.setPen(Theme.color("text" if key == self.value else "secondary"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


KEY_NAMES = {"ctrl": "Strg", "alt": "Alt", "shift": "Umschalt", "space": "Leertaste", "esc": "Esc",
             "windows": "Win", "enter": "Enter", "tab": "Tab"}


class KeyCaps(QWidget):
    """Shows a hotkey like ``ctrl+alt+v`` as keycaps."""

    def __init__(self, combo, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for part in combo.split("+"):
            cap = QLabel(KEY_NAMES.get(part.strip().lower(), part.strip().upper()))
            cap.setObjectName("KeyCap")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(cap)


def card():
    frame = QFrame()
    frame.setObjectName("Card")
    return frame


def divider():
    line = QFrame()
    line.setObjectName("Divider")
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line
