"""Colors, type, stylesheet and line icons for the Qt interface."""
from pathlib import Path
import tempfile
import winreg

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QImage,
                           QLinearGradient, QPainter, QPixmap)
from PySide6.QtSvg import QSvgRenderer

LIGHT = dict(
    window="#F5F5F7", card="#FFFFFF", border="#E3E3E8", text="#1D1D1F", secondary="#6E6E73",
    muted="#AEAEB2", primary="#1D1D1F", on_primary="#FFFFFF", control="#E9E9EE",
    hover="#00000010", track="#D9D9DE", danger="#D70015", shadow=(0, 0, 0), accent="#7C4DFF",
)
DARK = dict(
    window="#1C1C1E", card="#2C2C2E", border="#3A3A3C", text="#F5F5F7", secondary="#98989D",
    muted="#636366", primary="#F5F5F7", on_primary="#1C1C1E", control="#3A3A3C",
    hover="#FFFFFF14", track="#48484A", danger="#FF453A", shadow=(0, 0, 0), accent="#B39DFF",
)


class Theme:
    """Active palette; widgets read it when painting."""
    mode = "system"
    colors = LIGHT

    @classmethod
    def dark(cls):
        if cls.mode == "system":
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        return cls.mode == "dark"

    @classmethod
    def apply(cls, mode=None):
        if mode:
            cls.mode = mode
        cls.colors = DARK if cls.dark() else LIGHT
        app = QGuiApplication.instance()
        if app.style().name().lower() != "fusion":
            app.setStyle("Fusion")  # the native style ignores parts of the stylesheet
        app.setStyleSheet(stylesheet(cls.colors))
        return cls.colors

    @classmethod
    def color(cls, name, alpha=None):
        color = QColor(cls.colors[name])
        if alpha is not None:
            color.setAlphaF(alpha)
        return color


def ui_font(size=10, weight=QFont.Weight.Normal):
    families = QFontDatabase.families()
    family = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in families), "")
    font = QFont(family)
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


def stylesheet(c):
    return f"""
    * {{ color: {c['text']}; font-size: 10pt; }}
    QWidget#SettingsWindow, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['window']}; }}
    QFrame#Card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 20px; }}
    QFrame#Divider {{ background: {c['border']}; border: none; max-height: 1px; min-height: 1px; }}
    QLabel {{ background: transparent; }}
    QLabel#Title {{ font-size: 17pt; font-weight: 600; }}
    QLabel#Secondary, QLabel#SectionLabel, QLabel#Footer {{ color: {c['secondary']}; }}
    QLabel#SectionLabel {{ font-size: 9pt; font-weight: 600; padding-left: 4px; }}
    QLabel#Footer {{ font-size: 8.5pt; }}
    QLabel#Value {{ color: {c['secondary']}; min-width: 44px; }}
    QLabel#KeyCap {{ background: {c['control']}; border-radius: 8px; padding: 2px 9px; min-height: 16px; color: {c['secondary']}; font-size: 8.5pt; }}
    QComboBox {{ background: {c['control']}; border: none; border-radius: 15px; padding: 6px 30px 6px 14px; min-width: 150px; min-height: 18px; }}
    QComboBox:hover {{ background: {c['track']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url("{icon_file('chevron-down', c['secondary'])}"); width: 12px; height: 12px;
        margin-right: 10px; }}
    QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 14px;
        padding: 6px; outline: none; selection-background-color: {c['control']}; selection-color: {c['text']}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['track']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['primary']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {c['card']}; border: 1px solid {c['border']}; width: 16px; height: 16px;
        margin: -7px 0; border-radius: 9px; }}
    QTextBrowser#Reader {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 20px; }}
    QTextBrowser#Reader > QWidget {{ background: transparent; }}
    QPlainTextEdit {{ background: transparent; border: none; selection-background-color: {c['track']}; }}
    QPushButton#Primary {{ background: {c['primary']}; color: {c['on_primary']}; border: none; border-radius: 14px;
        min-height: 18px; padding: 5px 18px; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {c['secondary']}; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['track']}; border-radius: 2px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
    QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 5px 10px; }}
    QMenu {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 14px; padding: 6px; }}
    QMenu::item {{ padding: 7px 20px; border-radius: 10px; }}
    QMenu::item:selected {{ background: {c['control']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
    """


# Line icons from Lucide (https://lucide.dev), ISC License, 24x24 viewBox.
ICONS = {
    "play": '<polygon points="6 3 20 12 6 21 6 3" fill="currentColor"/>',
    "pause": '<rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>'
             '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/>',
    "skip-back": '<polygon points="19 20 9 12 19 4 19 20" fill="currentColor"/><line x1="5" x2="5" y1="19" y2="5"/>',
    "skip-forward": '<polygon points="5 4 15 12 5 20 5 4" fill="currentColor"/><line x1="19" x2="19" y1="5" y2="19"/>',
    "volume": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/>'
              '<path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>',
    "volume-x": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/>'
                '<line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
    "minus": '<path d="M5 12h14"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "book-open": '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5'
                 'a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "audio-lines": '<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/>'
                   '<path d="M18 5v13"/><path d="M22 10v3"/>',
}


def paint_icon(painter, name, rect, color, stroke=2.0):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color.name()}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" '
           f'color="{color.name()}">{ICONS[name].replace("currentColor", color.name())}</svg>')
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(rect))


def icon_pixmap(name, size, color, background=None, ratio=2.0):
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    inset = 0
    if background is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * .26, size * .26)
        inset = size * .2
    paint_icon(painter, name, QRectF(inset, inset, size - 2 * inset, size - 2 * inset), color)
    painter.end()
    return pixmap


def icon_file(name, color):
    """Stylesheets need image files; render the icon once into the temp folder."""
    path = Path(tempfile.gettempdir()) / "vorleser-icons" / f"{name}-{color.strip('#')}.png"
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        icon_pixmap(name, 12, QColor(color), ratio=2.0).save(str(path))
    return path.as_posix()


def taskbar_is_light():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def tray_icon():
    color = QColor("#1D1D1F" if taskbar_is_light() else "#FFFFFF")
    icon = QIcon()
    for size in (16, 20, 24, 32):
        icon.addPixmap(icon_pixmap("audio-lines", size, color, ratio=1.0))
    return icon


def app_icon_image(size):
    """Rounded square with a violet gradient, soft top light and white sound waves."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, size, size).adjusted(size * .04, size * .04, -size * .04, -size * .04)
    radius = rect.width() * .2237  # close to the iOS / macOS app icon curve
    fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
    fill.setColorAt(0, QColor("#6D6AF8"))
    fill.setColorAt(.55, QColor("#8B5CF6"))
    fill.setColorAt(1, QColor("#C04CE0"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawRoundedRect(rect, radius, radius)
    light = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.center().y()))
    light.setColorAt(0, QColor(255, 255, 255, 64))
    light.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(light)
    p.drawRoundedRect(rect, radius, radius)
    small = size <= 24  # fewer pixels need bolder strokes to stay legible
    glyph = rect.width() * (.74 if small else .62)
    box = QRectF(rect.center().x() - glyph / 2, rect.center().y() - glyph / 2, glyph, glyph)
    paint_icon(p, "audio-lines", box, QColor("#FFFFFF"), stroke=3.4 if small else 2.4)
    p.end()
    return image


def app_icon():
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(app_icon_image(size)))
    return icon
