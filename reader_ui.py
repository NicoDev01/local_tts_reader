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
from reading_view import ReadingView
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
    selection = Signal(object, object)  # token, text ('' nothing selected, None clipboard not saved)


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
        self.view = ReadingView()
        self._connect_ui()
        self._setup_tray()
        self._register_hotkeys()
        self._sync_autostart()
        self._render_controls()
        self._set_status(f"Bereit · {hotkey_label(self.config['hotkey'])}")

        self.save_timer = QTimer(singleShot=True, interval=400, timeout=self._save)
        self.ticker = QTimer(interval=60, timeout=self._tick)  # word highlight follows speech
        self.speed_timer = QTimer(singleShot=True, interval=450, timeout=self._respeed)
        self.pending_respeed = None  # sentence at which the new tempo takes over
        self.scrubbing = False
        self.message_timer = QTimer(singleShot=True, interval=1600, timeout=self._end_message)
        self.instance_timer = QTimer(interval=250, timeout=self._check_instance)
        self.instance_timer.start()
        if not self.config["welcomed"]:
            QTimer.singleShot(1200, self._welcome)

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
        h.set_anchor(self.config["hud_anchor"])
        h.moved.connect(self._hud_moved)
        h.open_view.connect(self.show_view)
        h.seek_preview.connect(self._preview_seek)
        h.seek.connect(self._seek)
        v = self.view
        v.jump.connect(self.jump_to)
        v.toggle_pause.connect(self.toggle_pause)
        v.previous.connect(lambda: self.jump(-1))
        v.next.connect(lambda: self.jump(1))
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
        for label, slot in (("Einstellungen öffnen", self.show_window), ("Leseansicht öffnen", self.show_view),
                            ("Pause / Weiter", self.toggle_pause),
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
        reading = self.state in ("reading", "buffering", "preparing")
        # While reading, the running sentence keeps its tempo (no warped audio); the new
        # tempo arrives with freshly generated speech from the next sentence on.
        speed = self.playback.player.controls()[0] if reading else self.config["speed"]
        self.playback.player.set_controls(speed, self.config["volume"])
        self._render_controls()
        self.save_timer.start()
        if key == "speed" and reading:
            self.speed_timer.start()  # settle first: slider drags and wheel steps come in bursts

    def _respeed(self):
        plan = self.playback.respeed_plan(self.config["speed"])
        self.pending_respeed = None
        if plan is None or plan[0] == "stretch":  # unchanged, or the last sentence: adjust it live
            self.playback.player.set_controls(self.config["speed"], self.config["volume"])
        elif plan[0] == "now":
            self._restart_at(plan[1])
        else:
            self.pending_respeed = plan[1]
        self._render_state()

    def _restart_at(self, unit):
        job = self.playback.current
        self.playback.player.set_controls(self.config["speed"], self.config["volume"])
        self.playback.start(None, self.config, units=job.units, first=unit)

    def _switch_speed_if_due(self):
        target = self.pending_respeed
        position = self.playback.position()
        if target is None or not position:
            return
        if position[0] >= target or self.playback.sentence_finished(target - 1):
            self.pending_respeed = None
            self._restart_at(target)

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
        self.view.refresh_theme()

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

    def _hud_moved(self, anchor):
        self.config["hud_anchor"] = anchor or []
        self.save_timer.start()

    def _welcome(self):
        self.tray.showMessage(
            "Vorleser ist bereit",
            f"Text markieren und {hotkey_label(self.config['hotkey'])} drücken. "
            "Ein Klick auf das Symbol im Infobereich öffnet die Einstellungen.",
            QSystemTrayIcon.MessageIcon.Information, 8000)
        self.config["welcomed"] = True
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
        if text is None:  # the clipboard holds something that cannot be saved and restored
            self._message("Zwischenablage nicht sicherbar",
                          ". Etwas anderes kopieren (z. B. ein Wort) und erneut drücken.")
        elif text.strip():
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
        if units and first:  # a jump: keep the bar at the new spot until audio starts
            words = [len(u.split()) for u in units]
            self.hud.set_progress(sum(words[:first]) / max(1, sum(words)))
        self.ticker.start()

    def _unit_at(self, fraction):
        """Sentence that starts at or before ``fraction`` of the text (by words)."""
        job = self.playback.current
        if not job or not job.units:
            return None, None
        words = [len(u.split()) for u in job.units]
        target, start = fraction * sum(words), 0
        for unit, count in enumerate(words):
            if start + count > target or unit == len(words) - 1:
                return unit, start
            start += count

    def _preview_seek(self, fraction):
        unit, words_before = self._unit_at(fraction)
        if unit is None:
            return
        if not self.scrubbing:
            self.playback.prewarm()  # connect while the finger is still on the bar
        self.scrubbing = True
        units = self.playback.current.units
        seconds = int(words_before / (self.config["speed"] * WORDS_PER_SECOND))
        self.hud.set_text(" ".join(units[unit].split()), status=True)
        self.hud.set_progress(fraction, f"{unit + 1} / {len(units)}")
        self.hud.remaining.setText(f"{seconds // 60}:{seconds % 60:02d}")

    def _seek(self, fraction):
        unit, _ = self._unit_at(fraction)
        self.scrubbing = False
        if unit is not None:
            self.jump_to(unit)

    def jump_to(self, unit):
        """Read from a sentence picked in the reading view (also after reading ended)."""
        job = self.playback.current
        units = job.units if job and job.units else (self.last or {}).get("units")
        if units:
            self.read_text(None, units=units, first=unit)
            self.view.set_paused(False)

    def show_view(self):
        job = self.playback.current
        if job and job.units:
            position = self.playback.position()
            self.view.show_text(job.units, position[0] if position else job.first)
        elif self.last:
            self.view.show_text(self.last["units"], self.last["unit"])
        self.view.show()
        self.view.raise_()
        self.view.activateWindow()

    def jump(self, delta):
        job = self.playback.current
        if not job or job.done.is_set():
            return
        new = self.playback.jump(delta, self.config)
        if new is None:
            return
        self.hud.set_paused(False)
        self._enter("preparing", self.hud._text)  # keep showing the sentence until audio starts
        words = [len(u.split()) for u in new.units]
        self.hud.set_progress(sum(words[:new.first]) / max(1, sum(words)))

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
        self.view.set_paused(paused)
        self._render_state()

    def stop(self):
        self.pending_respeed = None
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

    def _message(self, text, hint=". Text markieren und erneut drücken."):
        self._set_status(text + hint)
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
        if self.pending_respeed is not None:
            self._switch_speed_if_due()
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
            if self.scrubbing:  # the preview owns the display while the bar is dragged
                return
            word = self.playback.current_word()
            spoken = (word[1], word[2]) if word and word[0] == unit else None
            self.hud.set_text(" ".join(units[unit].split()), word=spoken)
            done = sum(words[:unit]) + within * words[unit]  # by words, so bar and time agree
            self.hud.set_progress(done / max(1, sum(words)), f"{unit + 1} / {len(units)}")
            self.hud.set_remaining(remaining, note="ab nächstem Satz"
                                   if self.pending_respeed is not None else None)
            self.hud.set_navigation(True, unit + 1 < len(units))
            if self.view.isVisible():
                self.view.show_text(units, unit, spoken)
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
