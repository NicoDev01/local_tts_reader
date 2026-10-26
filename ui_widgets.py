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
             "windows": "Win", "enter": "Enter", "tab": "Tab", "left": "←", "right": "→", "up": "↑",
             "down": "↓", "backspace": "Rücktaste", "delete": "Entf", "page up": "Bild ↑", "page down": "Bild ↓"}

# Windows virtual-key codes -> names the ``keyboard`` package understands.
VK_NAMES = {0x20: "space", 0x1B: "esc", 0x0D: "enter", 0x09: "tab", 0x08: "backspace", 0x2E: "delete",
            0x2D: "insert", 0x24: "home", 0x23: "end", 0x21: "page up", 0x22: "page down", 0x25: "left",
            0x26: "up", 0x27: "right", 0x28: "down", 0xBC: ",", 0xBE: ".", 0xBD: "-"}
VK_NAMES.update({vk: chr(vk).lower() for vk in range(0x41, 0x5B)})
VK_NAMES.update({vk: chr(vk) for vk in range(0x30, 0x3A)})
VK_NAMES.update({0x70 + i: f"f{i + 1}" for i in range(24)})


def key_label(part):
    part = part.strip().lower()
    return KEY_NAMES.get(part, part.upper())


class HotkeyField(QWidget):
    """Shows a hotkey like ``ctrl+alt+v`` as keycaps; click to record a new one."""
    recorded = Signal(str)
    recording = Signal(bool)

    def __init__(self, combo, default, parent=None):
        super().__init__(parent)
        self.default, self.active = default, False
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Klicken und neue Tastenkombination drücken")
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(6, 3, 6, 3)
        self.layout_.setSpacing(4)
        self.set_combo(combo)

    def set_combo(self, combo):
        self.combo = combo
        while self.layout_.count():
            old = self.layout_.takeAt(0).widget()
            old.setParent(None)
            old.deleteLater()
        if self.active:
            hint = QLabel("Tasten drücken · Rücktaste: Standard")
            hint.setObjectName("Secondary")
            self.layout_.addWidget(hint)
            return
        for part in combo.split("+"):
            cap = QLabel(key_label(part))
            cap.setObjectName("KeyCap")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout_.addWidget(cap)

    def mousePressEvent(self, _event):
        if not self.active:
            self.active = True
            self.set_combo(self.combo)
            self.setFocus()
            self.grabKeyboard()
            self.recording.emit(True)
            self.update()

    def keyPressEvent(self, event):
        if not self.active:
            return super().keyPressEvent(event)
        name = VK_NAMES.get(event.nativeVirtualKey())
        if not name:
            return  # a modifier alone, or a key the hotkey library cannot name
        mods = event.modifiers()
        parts = [n for flag, n in ((Qt.KeyboardModifier.ControlModifier, "ctrl"),
                                   (Qt.KeyboardModifier.AltModifier, "alt"),
                                   (Qt.KeyboardModifier.ShiftModifier, "shift"),
                                   (Qt.KeyboardModifier.MetaModifier, "windows")) if mods & flag]
        combo = self.default if name == "backspace" and not parts else "+".join(parts + [name])
        self._finish()
        self.recorded.emit(combo)

    def focusOutEvent(self, event):
        if self.active:
            self._finish()
        super().focusOutEvent(event)

    def _finish(self):
        self.releaseKeyboard()
        self.active = False
        self.set_combo(self.combo)
        self.recording.emit(False)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.active:
            p.setPen(Theme.color("primary"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
        elif self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Theme.color("hover"))
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


def card():
    frame = QFrame()
    frame.setObjectName("Card")
    return frame


def divider():
    line = QFrame()
    line.setObjectName("Divider")
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return line
