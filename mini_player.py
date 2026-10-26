"""Floating mini-player: current sentence, sentence navigation, tempo and volume.

It never takes focus, so clicking it leaves the document's selection alone.
"""
import html
import math
import re

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF,
                            Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui_theme import Theme, ui_font
from ui_widgets import IconButton
from windows_runtime import prevent_activation

SHADOW = 16
EXPANDED = (340, 124)
COLLAPSED = (148, 44)


def elide_lines(text, metrics, width, lines=2):
    """Wrap to at most ``lines`` lines, ending with an ellipsis if cut."""
    words, rows, row = text.split(), [], ""
    for word in words:
        candidate = f"{row} {word}".strip()
        if metrics.horizontalAdvance(candidate) <= width or not row:
            row = candidate
            continue
        rows.append(row)
        row = word
        if len(rows) == lines:
            break
    if len(rows) < lines and row:
        rows.append(row)
        row = ""
    if len(rows) == lines and (row or len(" ".join(rows).split()) < len(words)):
        rows[-1] = metrics.elidedText(rows[-1] + " …", Qt.TextElideMode.ElideRight, width)
        if not rows[-1].endswith("…"):
            rows[-1] = rows[-1].rstrip(" .,;:") + " …"
    return "\n".join(rows)


def highlight_lines(text, word_at, metrics, width, colors, lines=2):
    """Two-line window that follows the spoken word: said words full, the current one
    marked, upcoming ones dimmed. Starts at the sentence beginning while it fits."""
    tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if not tokens:
        return ""
    current = next((i for i, (_, end) in enumerate(tokens) if end > word_at), len(tokens) - 1)

    def fill(first):
        rows, line = [[]], "… " if first else ""
        for i in range(first, len(tokens)):
            word = text[tokens[i][0]:tokens[i][1]]
            candidate = f"{line} {word}" if line.strip() else line + word
            if metrics.horizontalAdvance(candidate) <= width or not rows[-1]:
                rows[-1].append(i)
                line = candidate
            elif len(rows) == lines:
                break
            else:
                rows.append([i])
                line = word
        return rows

    # Keep as much already-read context as fits while the current word and a few
    # upcoming words stay visible, so the eye can read ahead.
    ahead = min(3, len(tokens) - 1 - current)
    for first in range(current + 1):
        rows = fill(first)
        if current + ahead in [i for row in rows for i in row]:
            break

    def span(i):
        word = html.escape(text[tokens[i][0]:tokens[i][1]])
        if i == current:
            return f'<span style="color:{colors["accent"]};">{word}</span>'
        return f'<span style="color:{colors["text" if i < current else "secondary"]};">{word}</span>'

    out = [" ".join(span(i) for i in row) for row in rows]
    if first:
        out[0] = f'<span style="color:{colors["secondary"]};">…</span> ' + out[0]
    if rows[-1] and rows[-1][-1] < len(tokens) - 1:
        out[-1] += f' <span style="color:{colors["secondary"]};">…</span>'
    return "<br>".join(out)


class Chip(QAbstractButton):
    """Small pill with text; the wheel changes the value in fine steps."""
    stepped = Signal(int)

    def __init__(self, tooltip, parent=None):
        super().__init__(parent)
        self.setFont(ui_font(8.5, QFont.Weight.DemiBold))
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tooltip)

    def setText(self, text):
        super().setText(text)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(text) + 18)
        self.update()

    def wheelEvent(self, event):
        self.stepped.emit(1 if event.angleDelta().y() > 0 else -1)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Theme.color("track" if self.underMouse() else "control"))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setPen(Theme.color("text"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class ProgressLine(QWidget):
    """Progress that can be scrubbed like a music player: hover shows a knob, drag previews,
    release seeks."""
    scrubbed = Signal(float)
    released = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value, self.drag = 0.0, None
        self.setFixedHeight(16)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Ziehen oder klicken zum Spulen")

    def set_value(self, value):
        value = min(1.0, max(0.0, value))
        if self.drag is None and abs(value - self.value) > .001:
            self.value = value
            self.update()

    def _fraction(self, event):
        return min(1.0, max(0.0, event.position().x() / max(1, self.width())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag = self._fraction(event)
            self.scrubbed.emit(self.drag)
            self.update()
        event.accept()  # never start dragging the whole player from here

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.drag = self._fraction(event)
            self.scrubbed.emit(self.drag)
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            self.value, self.drag = self.drag, None  # hold the spot until playback catches up
            self.released.emit(self.value)
            self.update()
        event.accept()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        active = self.underMouse() or self.drag is not None
        thick = 5.0 if active else 3.0
        y = (self.height() - thick) / 2
        shown = self.drag if self.drag is not None else self.value
        p.setBrush(Theme.color("track"))
        p.drawRoundedRect(QRectF(0, y, self.width(), thick), thick / 2, thick / 2)
        if shown > 0:
            p.setBrush(Theme.color("accent"))
            p.drawRoundedRect(QRectF(0, y, max(thick, self.width() * shown), thick), thick / 2, thick / 2)
        if active:
            x = min(max(self.width() * shown, 7.0), self.width() - 7.0)
            p.setBrush(Theme.color("card"))
            p.setPen(Theme.color("accent"))
            p.drawEllipse(QRectF(x - 6.5, self.height() / 2 - 6.5, 13, 13))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Theme.color("accent"))
            p.drawEllipse(QRectF(x - 3.5, self.height() / 2 - 3.5, 7, 7))


class LevelBars(QWidget):
    """Four calm bars that move while speech is playing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 16)
        self.phase, self.active = 0.0, False
        self.timer = QTimer(self, interval=60, timeout=self._tick)

    def set_active(self, active):
        self.active = active
        self.timer.start() if active else self.timer.stop()
        self.update()

    def _tick(self):
        self.phase += .35
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(Theme.color("secondary"))
        for i in range(4):
            level = .35 + .65 * abs(math.sin(self.phase * (1 + i * .37) + i)) if self.active else .3
            h = max(3.0, 16 * level)
            p.drawRoundedRect(QRectF(i * 5.5, 16 - h, 3, h), 1.5, 1.5)


class MiniPlayer(QWidget):
    toggle_pause = Signal()
    stop = Signal()
    previous = Signal()
    next = Signal()
    speed_step = Signal(int)
    volume_toggle = Signal()
    volume_step = Signal(int)
    moved = Signal(object)  # new bottom-right anchor [x, y], or None after a reset
    open_view = Signal()
    seek_preview = Signal(float)  # 0..1 while the progress line is dragged
    seek = Signal(float)          # 0..1 when it is released

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Vorleser")
        self.collapsed = False
        self.paused = False
        self._text, self._is_status = "", True
        self.anchor = None  # QPoint of the card's bottom-right corner once dragged
        self._press = None
        self._build()
        self._apply_size()
        self._fade = None

    # -- layout -----------------------------------------------------------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)

        self.expanded_view = QWidget()
        v = QVBoxLayout(self.expanded_view)
        v.setContentsMargins(16, 12, 10, 10)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(2)
        self.sentence = QLabel()
        self.sentence.setFont(ui_font(10))
        self.sentence.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.sentence.setFixedHeight(QFontMetrics(ui_font(10)).lineSpacing() * 2 + 2)
        top.addWidget(self.sentence, 1)
        self.view_btn = IconButton("book-open", 22, 13, tooltip="Leseansicht: ganzer Text")
        self.view_btn.clicked.connect(self.open_view)
        self.collapse_btn = IconButton("minus", 22, 13, tooltip="Einklappen")
        self.close_btn = IconButton("x", 22, 13, tooltip="Vorlesen beenden (Esc)")
        self.collapse_btn.clicked.connect(self.collapse)
        self.close_btn.clicked.connect(self.stop)
        for b in (self.view_btn, self.collapse_btn, self.close_btn):
            top.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)
        self.progress = ProgressLine()
        self.progress.scrubbed.connect(self.seek_preview)
        self.progress.released.connect(self.seek)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 6, 0)
        progress_row.addWidget(self.progress)
        v.addLayout(progress_row)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.prev_btn = IconButton("skip-back", 30, 14, tooltip="Vorheriger Satz")
        self.play_btn = IconButton("pause", 36, 15, filled=True, tooltip="Pause / Weiter (Strg + Alt + Leertaste)")
        self.next_btn = IconButton("skip-forward", 30, 14, tooltip="Nächster Satz")
        self.prev_btn.clicked.connect(self.previous)
        self.play_btn.clicked.connect(self.toggle_pause)
        self.next_btn.clicked.connect(self.next)
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            controls.addWidget(b)
        self.remaining = QLabel()
        self.remaining.setFont(ui_font(8.5))
        self.remaining.setObjectName("Secondary")
        controls.addSpacing(6)
        controls.addWidget(self.remaining)
        controls.addStretch(1)
        self.speed = Chip("Tempo: klicken für die nächste Stufe, Mausrad für feine Schritte")
        self.speed.clicked.connect(lambda: self.speed_step.emit(0))
        self.speed.stepped.connect(self.speed_step)
        controls.addWidget(self.speed)
        self.volume = IconButton("volume", 30, 15, tooltip="Ton aus / an · Mausrad: Lautstärke")
        self.volume.clicked.connect(self.volume_toggle)
        self.volume.wheelEvent = lambda e: self.volume_step.emit(1 if e.angleDelta().y() > 0 else -1)
        controls.addWidget(self.volume)
        v.addLayout(controls)

        self.collapsed_view = QWidget()
        h = QHBoxLayout(self.collapsed_view)
        h.setContentsMargins(8, 8, 14, 8)
        h.setSpacing(10)
        self.mini_play = IconButton("pause", 28, 12, filled=True, tooltip="Pause / Weiter")
        self.mini_play.clicked.connect(self.toggle_pause)
        self.bars = LevelBars()
        self.counter = QLabel()
        self.counter.setFont(ui_font(8.5))
        self.counter.setObjectName("Secondary")
        h.addWidget(self.mini_play)
        h.addWidget(self.bars)
        h.addWidget(self.counter, 1)
        self.collapsed_view.setToolTip("Klicken zum Aufklappen · ziehen zum Verschieben")
        self.collapsed_view.setCursor(Qt.CursorShape.PointingHandCursor)

        outer.addWidget(self.expanded_view)
        outer.addWidget(self.collapsed_view)

    def _apply_size(self):
        self.expanded_view.setVisible(not self.collapsed)
        self.collapsed_view.setVisible(self.collapsed)
        w, h = COLLAPSED if self.collapsed else EXPANDED
        self.setFixedSize(w + 2 * SHADOW, h + 2 * SHADOW)
        self._place()

    def _place(self):
        screen = (self.anchor and QGuiApplication.screenAt(self.anchor - QPoint(4, 4))) or None
        if screen is None:  # default corner, on the screen with the mouse
            self.anchor = None
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        corner = self.anchor or QPoint(area.right() - 16, area.bottom() - 16)
        x = min(max(corner.x() - self.width() + SHADOW, area.left() - SHADOW), area.right() - self.width() + SHADOW)
        y = min(max(corner.y() - self.height() + SHADOW, area.top() - SHADOW), area.bottom() - self.height() + SHADOW)
        self.move(x, y)

    def set_anchor(self, anchor):
        self.anchor = QPoint(*anchor) if anchor else None

    # -- dragging: the card moves like a window; a plain click on the pill expands it --
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = (event.globalPosition().toPoint(), self.pos(), False)

    def mouseMoveEvent(self, event):
        if self._press:
            start, origin, dragged = self._press
            delta = event.globalPosition().toPoint() - start
            if dragged or delta.manhattanLength() > 4:
                self._press = (start, origin, True)
                self.move(origin + delta)

    def mouseReleaseEvent(self, _event):
        if not self._press:
            return
        dragged = self._press[2]
        self._press = None
        if dragged:
            self.anchor = self.pos() + QPoint(self.width() - SHADOW, self.height() - SHADOW)
            self.moved.emit([self.anchor.x(), self.anchor.y()])
        elif self.collapsed:
            self.expand()

    def mouseDoubleClickEvent(self, _event):
        self.anchor = None
        self.moved.emit(None)
        self._place()

    # -- painting ---------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        radius = card.height() / 2 if self.collapsed else 26
        shadow_alpha = .45 if Theme.dark() else .10
        for i in range(SHADOW, 0, -2):  # soft layered shadow, a little lower than the card
            color = QColor(0, 0, 0)
            color.setAlphaF(shadow_alpha * (1 - i / SHADOW) ** 2 / 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(card.adjusted(-i, -i + 4, i, i + 4), radius + i, radius + i)
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        p.fillPath(path, Theme.color("card"))
        p.setPen(Theme.color("border"))
        p.drawPath(path)

    # -- state ------------------------------------------------------------------
    def refresh_theme(self):
        self._render_text()
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    def set_text(self, text, status=False, word=None):
        """``word`` = (char offset, length) of the word being spoken, to highlight it."""
        self._text, self._is_status, self._word = text, status, word
        self._render_text()

    def _render_text(self):
        color = Theme.colors["secondary" if self._is_status else "text"]
        self.sentence.setStyleSheet(f"color: {color};")
        width = EXPANDED[0] - 16 - 10 - 3 * 24
        metrics = QFontMetrics(self.sentence.font())
        if self._is_status or not getattr(self, "_word", None):
            self.sentence.setTextFormat(Qt.TextFormat.PlainText)
            self.sentence.setText(elide_lines(self._text, metrics, width))
            return
        self.sentence.setTextFormat(Qt.TextFormat.RichText)
        self.sentence.setText(highlight_lines(self._text, self._word[0], metrics, width, Theme.colors))

    def set_paused(self, paused):
        self.paused = paused
        icon = "play" if paused else "pause"
        self.play_btn.set_icon(icon)
        self.mini_play.set_icon(icon)
        self.bars.set_active(not paused and self.isVisible())

    def set_progress(self, value, counter=""):
        self.progress.set_value(value)
        self.counter.setText(counter)

    def set_remaining(self, seconds, note=None):
        """Remaining time, or a short ``note`` in the accent color (e.g. a pending tempo)."""
        if note:
            self.remaining.setStyleSheet(f"color: {Theme.colors['accent']};")
            self.remaining.setText(note)
            return
        self.remaining.setStyleSheet("")
        if seconds is None:
            self.remaining.setText("")
        else:
            seconds = int(round(seconds))
            self.remaining.setText(f"−{seconds // 60}:{seconds % 60:02d}")

    def set_controls(self, speed, volume):
        self.speed.setText(f"{speed:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "×")
        self.volume.set_icon("volume-x" if volume <= .01 else "volume")

    def set_navigation(self, previous, following):
        self.prev_btn.setEnabled(previous)
        self.next_btn.setEnabled(following)

    # -- visibility -------------------------------------------------------------
    def collapse(self):
        self.collapsed = True
        self._apply_size()
        self.update()

    def expand(self):
        self.collapsed = False
        self._apply_size()
        self.update()

    def show_player(self):
        if self.isVisible() and self.windowOpacity() > .99:
            return
        if self._fade:
            self._fade.stop()
        self._place()
        end = self.pos()
        self.setWindowOpacity(0.0)
        self.show()
        prevent_activation(int(self.winId()))
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity", group)
        fade.setDuration(160)
        fade.setEndValue(1.0)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(220)
        slide.setStartValue(end + QPoint(0, 10))
        slide.setEndValue(end)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(slide)
        self._fade = group
        group.start()
        self.bars.set_active(not self.paused)

    def hide_player(self):
        if not self.isVisible():
            return
        if self._fade:
            self._fade.stop()
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(140)
        anim.setEndValue(0.0)

        def done():
            self.hide()
            if self.collapsed:
                self.expand()
        anim.finished.connect(done)
        self._fade = anim
        anim.start()
        self.bars.set_active(False)
