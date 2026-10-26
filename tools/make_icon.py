r"""Writes assets/vorleser.ico (launcher and desktop shortcut) from the app icon drawing.

.venv\Scripts\python.exe -B tools\make_icon.py
"""
import io
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication
from ui_theme import app_icon_image

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(size):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    app_icon_image(size).save(buffer, "PNG")
    return bytes(buffer.data())


def main():
    QGuiApplication(sys.argv)
    images = [png_bytes(size) for size in SIZES]
    # ICO container with PNG entries (supported since Windows Vista).
    out = io.BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(SIZES)))
    offset = 6 + 16 * len(SIZES)
    for size, data in zip(SIZES, images):
        out.write(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for data in images:
        out.write(data)
    target = ROOT / "assets" / "vorleser.ico"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(out.getvalue())
    app_icon_image(256).save(str(ROOT / "assets" / "vorleser-256.png"))
    print(target, len(out.getvalue()), "Bytes")


main()
