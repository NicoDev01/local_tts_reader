"""Tray app wiring: hotkeys, playback, mini-player and settings. Qt runs on the main thread only."""
import logging
import re
import threading

import keyboard
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from clipboard_capture import capture_selection
from mini_player import MiniPlayer
from playback import PlaybackController
from settings import DEFAULTS, VOICES, load_config, save_config, set_autostart, is_autostart_enabled
from settings_window import SettingsWindow
from ui_theme import Theme, tray_icon
from ui_widgets import key_label

SPEED_STEPS = (1.0, 1.25, 1.5, 1.75, 2.0)
WORDS_PER_SECOND = 2.5  # measured 2.5 words/s at 1.0x with the German voices (2026-10-26)
HOTKEYS = {"hotkey": "capture", "pause_hotkey": "pause", "stop_hotkey": "stop",
           "prev_hotkey": "previous", "next_hotkey": "next"}
HOTKEY_NAMES = {"hotkey": "Vorlesen", "pause_hotkey": "Pause / Weiter", "stop_hotkey": "Beenden",
                "prev_hotkey": "Satz zurück", "next_hotkey": "Satz vor"}


def hotkey_label(combo):
    return " + ".join(key_label(p) for p in combo.split("+"))


def hotkey_problem(combo, others):
    """Why ``combo`` cannot be a global hotkey, or None."""
    parts = combo.split("+")
    if len(parts) == 1 and not re.fullmatch(r"esc|f\d{1,2}", combo):
        return "Einzelne Tasten würden beim Tippen auslösen. Bitte mit Strg, Alt, Umschalt oder Win kombinieren."
    for key, other in others.items():
        if other == combo:
            return f"{hotkey_label(combo)} ist schon für „{HOTKEY_NAMES[key]}“ vergeben."
    try:
        keyboard.parse_hotkey(combo)
    except ValueError:
        return f"{hotkey_label(combo)} kann nicht als Tastenkürzel verwendet werden."
    return None


class Bridge(QObject):
    """Signals hop from worker threads (hotkeys, network, audio) to the Qt thread."""
    action = Signal(str)
    playback = Signal(object, str, object)
    selection = Signal(object, str)


class ReaderApp:
    def __init__(self, instance):
        self.instance = instance
        self.config = load_config()
        self.closing = False
        self.last = None          # last reading: units, unit to resume at, finished
        self._previewing = False
        self.capture_cancel = threading.Event()
        self.state = "idle"  # idle | capturing | preparing | reading | buffering | message
        self.bridge = Bridge()
        self.bridge.action.connect(self._on_action)
        self.bridge.playback.connect(self._on_playback)
        self.bridge.selection.connect(self._on_selection)

        Theme.apply(self.config["theme"])
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _s: self._apply_theme())
        self.playback = PlaybackController(lambda *event: self.bridge.playback.emit(*event), self.config)
        self.hud = MiniPlayer()
        self.window = SettingsWindow(self.config)
        self._connect_ui()
        self._setup_tray()
        self._register_hotkeys()
        self._sync_autostart()
        self._render_controls()
        self._set_status(f"Bereit · {hotkey_label(self.config['hotkey'])}")

        self.save_timer = QTimer(singleShot=True, interval=400, timeout=self._save)
        self.ticker = QTimer(interval=100, timeout=self._tick)
        self.message_timer = QTimer(singleShot=True, interval=1600, timeout=self._end_message)
        self.instance_timer = QTimer(interval=250, timeout=self._check_instance)
        self.instance_timer.start()

    # -- wiring ---------------------------------------------------------------------
    def _connect_ui(self):
        h, w = self.hud, self.window
        h.toggle_pause.connect(self.toggle_pause)
        h.stop.connect(self.stop)
        h.previous.connect(lambda: self.jump(-1))
        h.next.connect(lambda: self.jump(1))
        h.speed_step.connect(self._speed_step)
        h.volume_toggle.connect(self._toggle_mute)
        h.volume_step.connect(lambda d: self.set_control("volume", self.config["volume"] + d * .05))
        w.control_changed.connect(self.set_control)
        w.choice_changed.connect(self.set_choice)
        w.toggle_changed.connect(self._toggle)
        w.preview_voice.connect(self._preview_voice)
        w.read_text.connect(self.read_text)
        w.hotkey_changed.connect(self.set_hotkey)
        w.hotkey_recording.connect(self._hotkey_recording)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(tray_icon())
        self.tray.setToolTip("Vorleser · Bereit")
        menu = QMenu()
        for label, slot in (("Einstellungen öffnen", self.show_window), ("Pause / Weiter", self.toggle_pause),
                            ("Vorlesen beenden", self.stop)):
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        menu.addSeparator()
        self.resume_action = QAction("Weiterlesen", menu)
        self.resume_action.triggered.connect(self.resume)
        self.again_action = QAction("Zuletzt Vorgelesenes wiederholen", menu)
        self.again_action.triggered.connect(lambda: self.resume(from_start=True))
        menu.addAction(self.resume_action)
        menu.addAction(self.again_action)
        menu.aboutToShow.connect(self._update_recent)
        self._update_recent()
        menu.addSeparator()
        quit_action = QAction("Beenden", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and self.show_window())
        self.tray.show()

    def _register_hotkeys(self):
        self.hotkeys = []
        for key, action in HOTKEYS.items():
            emit = lambda a=action: self.bridge.action.emit(a)
            try:
                self.hotkeys.append(keyboard.add_hotkey(self.config[key], emit))
            except (ValueError, KeyError):
                self.config[key] = DEFAULTS[key]
                self.window.set_hotkey(key, self.config[key])
                self.hotkeys.append(keyboard.add_hotkey(self.config[key], emit))
                self._set_status("Ungültiges Tastenkürzel wurde auf den Standard zurückgesetzt.")

    def _unregister_hotkeys(self):
        for hook in self.hotkeys:
            try:
                keyboard.remove_hotkey(hook)
            except (KeyError, ValueError):
                pass
        self.hotkeys = []

    def _hotkey_recording(self, active):
        # While a new combination is typed, the current ones must not fire.
        self._unregister_hotkeys() if active else (self.hotkeys or self._register_hotkeys())

    def set_hotkey(self, key, combo):
        error = hotkey_problem(combo, {k: self.config[k] for k in HOTKEYS if k != key})
        if error:
            self.window.set_hotkey(key, self.config[key])
            self._set_status(error)
        else:
            self.config[key] = combo
            self.window.set_hotkey(key, combo)
            self._set_status(f"Tastenkürzel gespeichert: {hotkey_label(combo)}")
            self.save_timer.start()
        self._unregister_hotkeys()
        self._register_hotkeys()

    def _sync_autostart(self):
        try:
            enabled = is_autostart_enabled()
            if enabled:
                set_autostart(True)  # refresh the launcher path
            self.config["autostart"] = enabled
            self.window.set_autostart(enabled)
        except OSError:
            logging.exception("Autostart konnte nicht aktualisiert werden")
            self._set_status("Autostart prüfen: Windows-Launcher nicht verfügbar.")

    def _on_action(self, action):
        {"capture": self.capture, "pause": self.toggle_pause, "stop": self.stop,
         "previous": lambda: self.jump(-1), "next": lambda: self.jump(1)}[action]()

    def _check_instance(self):
        if self.instance.show_requested():
            self.show_window()

    # -- settings -------------------------------------------------------------------
    def set_control(self, key, value):
        low, high = (.7, 2.0) if key == "speed" else (0.0, 1.5)
        value = round(min(high, max(low, float(value))), 2)
        if value == self.config[key]:
            return
        self.config[key] = value
        self.playback.player.set_controls(self.config["speed"], self.config["volume"])
        self._render_controls()
        self.save_timer.start()

    def _render_controls(self):
        self.window.set_controls(self.config["speed"], self.config["volume"])
        self.hud.set_controls(self.config["speed"], self.config["volume"])

    def _speed_step(self, direction):
        speed = self.config["speed"]
        if direction == 0:  # click: next preset, wrapping around
            following = [s for s in SPEED_STEPS if s > speed + .001]
            speed = following[0] if following else SPEED_STEPS[0]
        else:
            speed += direction * .05
        self.set_control("speed", speed)

    def _toggle_mute(self):
        if self.config["volume"] > .01:
            self._last_volume = self.config["volume"]
            self.set_control("volume", 0.0)
        else:
            self.set_control("volume", getattr(self, "_last_volume", .85))

    def set_choice(self, key, value):
        self.config[key] = value
        if key == "sound_profile":
            self.playback.player.set_profile(value)
        elif key == "theme":
            self._apply_theme()
        self.save_timer.start()

    def _apply_theme(self):
        Theme.apply(self.config["theme"])
        self.window.refresh_theme()
        self.hud.refresh_theme()

    def _toggle(self, key, enabled):
        if key == "autostart":
            try:
                set_autostart(enabled)
            except OSError as error:
                self.window.set_autostart(self.config["autostart"])
                self._set_status(str(error))
                return
        self.config[key] = enabled
        if key == "hud_enabled":
            if not enabled:
                self.hud.hide_player()
            elif self.state != "idle":
                self.hud.show_player()
        self.save_timer.start()

    def _save(self):
        try:
            save_config(self.config)
        except OSError:
            logging.exception("Speichern fehlgeschlagen")
            self._set_status("Einstellungen konnten nicht gespeichert werden.")

    # -- reading --------------------------------------------------------------------
    def capture(self):
        self.stop()
        token = threading.Event()
        self.capture_cancel = token
        # Connect while the selection is copied; show the player before the first word.
        self.playback.prewarm()
        self._enter("capturing", "Text wird übernommen …")

        def worker():
            text = capture_selection(token, self.config["restore_clipboard"])
            self.bridge.selection.emit(token, text)
        threading.Thread(target=worker, daemon=True, name="tts-clipboard").start()

    def _on_selection(self, token, text):
        if token is not self.capture_cancel or token.is_set():
            return
        if text.strip():
            self.read_text(text)
        else:
            self._message("Kein Text markiert")

    def read_text(self, text, units=None, first=0):
        if units is None and not text.strip():
            self._set_status("Kein Text vorhanden. Text markieren oder eingeben.")
            return
        self._remember()
        self._previewing = False
        self.playback.start(text, self.config, units=units, first=first)
        self.hud.set_paused(False)
        self._enter("preparing", "Wird vorbereitet …")
        self.ticker.start()

    def jump(self, delta):
        job = self.playback.current
        if not job or job.done.is_set():
            return
        if self.playback.jump(delta, self.config) is None:
            return
        self.hud.set_paused(False)
        self._enter("preparing", self.hud._text)  # keep showing the sentence until audio starts

    # -- last reading (kept in memory only; the text is never written to disk) ------
    def _remember(self, finished=False):
        job = self.playback.current
        if not job or not job.units or self._previewing:
            return
        position = self.playback.position()
        self.last = dict(units=job.units, unit=position[0] if position else job.first, finished=finished)

    def _update_recent(self):
        last = getattr(self, "last", None)
        can_resume = bool(last) and not last["finished"]
        self.resume_action.setEnabled(can_resume)
        self.again_action.setEnabled(bool(last))
        if can_resume:
            words = last["units"][last["unit"]].split()
            snippet = " ".join(words[:5]) + (" …" if len(words) > 5 else "")
            self.resume_action.setText(f"Weiterlesen: „{snippet}“")
        else:
            self.resume_action.setText("Weiterlesen")

    def resume(self, from_start=False):
        last = getattr(self, "last", None)
        if last:
            first = 0 if from_start or last["finished"] else last["unit"]
            self.read_text(None, units=last["units"], first=first)

    def _preview_voice(self):
        name = VOICES[self.config["voice"]].split(" (")[0]
        self.read_text(f"Hallo, ich bin {name}. So klinge ich, wenn ich dir einen Text vorlese.")
        self._previewing = True  # a voice sample is not "the last reading"

    def toggle_pause(self):
        job = self.playback.current
        if not job or job.done.is_set():
            return
        paused = self.playback.toggle_pause()
        self.hud.set_paused(paused)
        self._render_state()

    def stop(self):
        self.capture_cancel.set()
        self._remember()
        self.playback.stop()
        self.ticker.stop()
        self.message_timer.stop()
        self.hud.hide_player()
        self.state = "idle"
        self._set_status(f"Bereit · {hotkey_label(self.config['hotkey'])}")

    def _on_playback(self, job, event, payload):
        if job is not self.playback.current:
            return
        if event == "progress":
            self.state = "reading"
        elif event == "buffering":
            self.state = "buffering"
        elif event in ("done", "error"):
            self._remember(finished=event == "done")
            self.ticker.stop()
            self.hud.hide_player()
            self.state = "idle"
            self._set_status("Fertig · Bereit zum Vorlesen" if event == "done" else payload)
            if event == "error":
                self.tray.showMessage("Vorleser", payload, QSystemTrayIcon.MessageIcon.Warning, 4000)
            return
        self._render_state()

    # -- presentation ---------------------------------------------------------------
    def _enter(self, state, text):
        self.state = state
        self.hud.set_text(text, status=True)
        self.hud.set_progress(0)
        self.hud.set_remaining(None)
        self._set_status(text)
        if self.config["hud_enabled"]:
            self.hud.show_player()

    def _message(self, text):
        self._set_status(text + ". Text markieren und erneut drücken.")
        if not self.config["hud_enabled"]:
            self.tray.showMessage("Vorleser", text, QSystemTrayIcon.MessageIcon.Information, 2500)
            self.state = "idle"
            return
        self._enter("message", text)
        self.message_timer.start()

    def _end_message(self):
        if self.state == "message":
            self.stop()

    def _tick(self):
        if self.state in ("reading", "buffering"):
            self._render_state()

    def _render_state(self):
        job = self.playback.current
        if not job:
            return
        paused = job.paused.is_set()
        position = self.playback.position()
        units = job.units
        if position and units:
            unit, since = position
            words = [len(u.split()) for u in units]
            speed = self.config["speed"] * WORDS_PER_SECOND
            within = min(.95, since * speed / max(1, words[unit]))
            remaining = max(0.0, sum(words[unit:]) / speed - since)
            self.hud.set_text(units[unit].strip())
            self.hud.set_progress((unit + within) / len(units), f"{unit + 1} / {len(units)}")
            self.hud.set_remaining(remaining)
            self.hud.set_navigation(True, unit + 1 < len(units))
        if paused:
            status = "Pausiert"
        elif self.state == "buffering":
            status = "Lädt nach …"
        else:
            status = "Liest vor" if position else "Wird vorbereitet …"
        if self.state == "buffering" or not position:
            self.hud.set_text(status if not position else self.hud._text, status=not position)
        self._set_status(status)

    def _set_status(self, text):
        self.window.set_status(text)
        if hasattr(self, "tray"):
            self.tray.setToolTip("Vorleser · " + text)

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def quit(self):
        if self.closing:
            return
        self.closing = True
        self.capture_cancel.set()
        if self.save_timer.isActive():
            self.save_timer.stop()
        self._save()
        self._unregister_hotkeys()
        self.tray.hide()
        self.playback.close()
        QGuiApplication.instance().quit()
