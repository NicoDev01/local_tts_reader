"""Validated settings and atomic, debounced-by-UI persistence."""
import json
import logging
import math
import os
from pathlib import Path
import winreg

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
DEFAULTS = dict(hotkey="ctrl+alt+v", pause_hotkey="ctrl+alt+space", stop_hotkey="esc",
                voice="de-DE-KillianNeural", speed=1.05, volume=0.7, pitch="+0Hz",
                restore_clipboard=True, autostart=False, hud_enabled=True,
                theme="system", sound_profile="studio_warmth")
# Voices offered by the Edge read-aloud service (checked 2026-10-26).
VOICES = {"de-DE-KillianNeural": "Killian", "de-DE-ConradNeural": "Conrad",
          "de-DE-FlorianMultilingualNeural": "Florian", "de-DE-KatjaNeural": "Katja",
          "de-DE-SeraphinaMultilingualNeural": "Seraphina", "de-DE-AmalaNeural": "Amala",
          "de-AT-JonasNeural": "Jonas (Österreich)", "de-AT-IngridNeural": "Ingrid (Österreich)",
          "de-CH-JanNeural": "Jan (Schweiz)", "de-CH-LeniNeural": "Leni (Schweiz)"}
PROFILES = dict(studio_warmth="Warm", headphone_comfort="Sanft", crystal_clear="Klar",
                night_whisper="Leise hören", bypass="Unbearbeitet")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "TTSVorleserStudio"


def validate(raw):
    cfg = DEFAULTS.copy()
    if not isinstance(raw, dict):
        return cfg
    for key in cfg:
        if key in raw and type(raw[key]) is type(cfg[key]):
            cfg[key] = raw[key]
    for key, low, high in (("speed", .7, 2.0), ("volume", 0., 1.5)):
        try:
            value = raw.get(key, cfg[key])
            if key == "speed" and "speed" not in raw and "rate" in raw:
                value = 1 + float(str(raw["rate"]).rstrip("%")) / 100
            value = float(value)
            cfg[key] = min(high, max(low, value)) if math.isfinite(value) else DEFAULTS[key]
        except (ValueError, TypeError):
            cfg[key] = DEFAULTS[key]
    if cfg["voice"] not in VOICES:
        cfg["voice"] = DEFAULTS["voice"]
    if cfg["sound_profile"] not in PROFILES:
        cfg["sound_profile"] = DEFAULTS["sound_profile"]
    if cfg["theme"] not in ("system", "light", "dark"):
        cfg["theme"] = "system"
    import re
    if not re.fullmatch(r"[+-]\d{1,2}Hz", cfg["pitch"]):
        cfg["pitch"] = "+0Hz"
    return cfg


def load_config():
    try:
        return validate(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return DEFAULTS.copy()
    except (OSError, ValueError):
        logging.exception("Einstellungen konnten nicht geladen werden")
        return DEFAULTS.copy()


def save_config(cfg):
    temp = CONFIG_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(validate(cfg), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, CONFIG_FILE)


def set_autostart(enabled):
    launcher = ROOT / "TTS Vorleser.exe"
    if enabled and not launcher.is_file():
        raise FileNotFoundError("Windows-Launcher fehlt. Bitte setup.ps1 ausführen.")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, '"' + str(launcher) + '"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, APP_NAME)[0])
    except FileNotFoundError:
        return False
