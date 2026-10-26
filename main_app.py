"""Tray-first Windows reader; Qt runs exclusively on the main thread."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

def main():
    root_dir = Path(__file__).resolve().parent
    handler = RotatingFileHandler(root_dir / 'reader.log', maxBytes=1_000_000,
                                  backupCount=2, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format='%(asctime)s %(levelname)s %(message)s')
    from windows_runtime import SingleInstance
    instance = SingleInstance()
    try:
        if not instance.primary:
            if '--show' in sys.argv:
                instance.request_show()
            return
        from PySide6.QtWidgets import QApplication
        from ui_theme import app_icon
        qt = QApplication(sys.argv)
        qt.setQuitOnLastWindowClosed(False)
        qt.setApplicationName('Vorleser')
        qt.setWindowIcon(app_icon())
        from reader_ui import ReaderApp
        app = ReaderApp(instance)
        import ctypes
        logging.info('Vorleser bereit; Konsole=%s; Fenster=%s',
                     bool(ctypes.windll.kernel32.GetConsoleWindow()), app.window.isVisible())
        if '--show' in sys.argv:
            app.show_window()
        qt.exec()
    finally:
        instance.close()

if __name__ == '__main__':
    try:
        main()
    except Exception:
        logging.exception('Anwendung konnte nicht gestartet werden')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            'Der Vorleser konnte nicht gestartet werden. Details stehen in reader.log im Programmordner.',
            'TTS Vorleser', 0x10)
