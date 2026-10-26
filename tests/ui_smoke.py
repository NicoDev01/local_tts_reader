"""Desktop smoke test of the Qt interface; renders screenshots without global hotkeys or audio.

Runs beside an already running reader: it uses its own instance stub and no hotkeys.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import time
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

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
        app._message('Kein Text markiert')
        pump(.3)
        assert app.hud.isVisible() and 'Kein Text' in app.hud.sentence.text()
        pump(1.8)
        assert not app.hud.isVisible()
        print(json.dumps({'themes': results, 'screenshots': str(output)}))
    finally:
        app.playback.current = None
        app.quit()
