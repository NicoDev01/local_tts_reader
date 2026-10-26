"""Desktop smoke test of the Qt interface; renders screenshots without global hotkeys or audio.

Runs beside an already running reader: it uses its own instance stub and no hotkeys.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import time
from unittest.mock import patch

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel

qt = QApplication(sys.argv)
qt.setQuitOnLastWindowClosed(False)

import reader_ui
from playback import Reading
from ui_theme import Theme

output = Path(__file__).resolve().parent / 'artifacts'
output.mkdir(exist_ok=True)


class Instance:
    def show_requested(self):
        return False


def pump(seconds=.4):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        qt.processEvents()
        time.sleep(.01)


with patch.object(reader_ui.keyboard, 'add_hotkey', return_value=None), \
        patch.object(reader_ui.keyboard, 'remove_hotkey'), \
        patch.object(reader_ui, 'save_config'), \
        patch.object(reader_ui, 'set_autostart'):
    app = reader_ui.ReaderApp(Instance())
    try:
        assert not app.window.isVisible() and app.tray.isVisible()
        results = {}
        for mode in ('light', 'dark'):
            app.set_choice('theme', mode)
            assert Theme.dark() == (mode == 'dark')
            app.show_window()
            pump()
            app.window.grab().save(str(output / f'settings-{mode}.png'))
            app.window.hide()

            job = Reading()
            job.units = ['Die Stadtbibliothek öffnet ab November bereits früher, damit Berufstätige vor der Arbeit '
                         'Bücher ausleihen können.', 'Gruppen melden sich vorher an.', 'Danach gibt es Kaffee.']
            job.sections = [(0, 3)]
            app.playback.current = job
            app.playback.player.cursor = ((job, 0), 1.2)
            app.state = 'reading'
            app.hud.set_paused(False)
            app.hud.show_player()
            app._render_state()
            pump(.5)
            assert app.hud.isVisible() and app.hud.windowOpacity() > .99
            assert app.hud.sentence.text().startswith('Die Stadtbibliothek')
            assert app.hud.counter.text() == '1 / 3'
            app.hud.grab().save(str(output / f'mini-player-{mode}.png'))
            app.hud.collapse()
            pump(.2)
            app.hud.grab().save(str(output / f'mini-player-collapsed-{mode}.png'))
            app.hud.expand()

            app.set_control('speed', 1.25)
            app._speed_step(0)
            assert app.config['speed'] == 1.5 and app.hud.speed.text() == '1,5×'
            app._toggle_mute()
            assert app.config['volume'] == 0 and app.hud.volume.icon_name == 'volume-x'
            app._toggle_mute()
            assert app.config['volume'] > 0
            app.toggle_pause()  # no running job: ignored
            app._on_playback(job, 'done', None)
            pump(.3)
            assert not app.hud.isVisible() and app.state == 'idle'
            app.playback.current = None
            results[mode] = True
        # Hotkeys: bare letters and duplicates are refused, valid ones take effect.
        app.set_hotkey('next_hotkey', 'n')
        assert app.config['next_hotkey'] == 'ctrl+alt+right' and 'Einzelne Tasten' in app.window.status.text()
        app.set_hotkey('next_hotkey', 'ctrl+alt+v')
        assert app.config['next_hotkey'] == 'ctrl+alt+right' and 'vergeben' in app.window.status.text()
        app.set_hotkey('next_hotkey', 'ctrl+shift+f9')
        assert app.config["next_hotkey"] == "ctrl+shift+f9"
        pump(.1)
        assert [c.text() for c in app.window.hotkeys['next_hotkey'].findChildren(QLabel)
                if c.objectName() == 'KeyCap'] == ['Strg', 'Umschalt', 'F9']
        # Recording: click the field, press Ctrl+Alt+K (virtual key 0x4B).
        field, got = app.window.hotkeys['prev_hotkey'], []
        field.recorded.connect(got.append)
        field.mousePressEvent(None)
        assert field.active
        field.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_K,
                                      Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
                                      0, 0x4B, 0))
        assert got == ['ctrl+alt+k'] and not field.active and app.config['prev_hotkey'] == 'ctrl+alt+k'
        app.show_window()
        pump()
        app.window.grab().save(str(output / 'settings-hotkeys.png'))
        app.window.hide()

        # Last reading: resume where it stopped, or again from the start.
        units = ['Eins.', 'Zwei.', 'Drei.']
        with patch.object(app.playback, 'start') as start:
            app.last = dict(units=units, unit=1, finished=False)
            app._update_recent()
            assert app.resume_action.isEnabled() and 'Zwei.' in app.resume_action.text()
            app.resume()
            assert start.call_args.kwargs['first'] == 1
            app.resume(from_start=True)
            assert start.call_args.kwargs['first'] == 0
        app.playback.current = None
        app.stop()

        # Dragged position is kept per corner anchor; a double-click returns to the default corner.
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        center = QGuiApplication.primaryScreen().availableGeometry().center()
        app.hud.set_anchor([center.x(), center.y()])
        app.hud._place()
        card_corner = app.hud.pos() + QPoint(app.hud.width() - 16, app.hud.height() - 16)
        assert card_corner == center, (card_corner, center)
        moved = []
        app.hud.moved.connect(moved.append)
        app.hud.mouseDoubleClickEvent(None)
        assert moved == [None] and app.hud.anchor is None
        app._hud_moved(None)

        app._message('Kein Text markiert')
        pump(.3)
        assert app.hud.isVisible() and 'Kein Text' in app.hud.sentence.text()
        pump(1.8)
        assert not app.hud.isVisible()
        print(json.dumps({'themes': results, 'screenshots': str(output)}))
    finally:
        app.playback.current = None
        app.quit()
