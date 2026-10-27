"""Which service speaks: ElevenLabs while chosen and usable, otherwise Microsoft Edge.

ElevenLabs is switched off for good (until chosen again) when its period has ended, the key is
missing or rejected, the plan is no longer active or the credits run low. A passing failure only
lets Edge read that one section, so a reading never stops because of ElevenLabs.
"""
import asyncio
import datetime as dt
import logging
import threading
from dataclasses import dataclass

from elevenlabs_tts import ElevenLabsClient, ElevenLabsError, api_key, native_speed
from high_fidelity_tts import HighFidelityTTSClient
from settings import VOICE_GAIN_DB
from text_cleaner import speakable

ELEVEN_GAIN_DB = 0.0


@dataclass(frozen=True)
class Route:
    engine: str   # "edge" or "elevenlabs"
    speed: float  # tempo the audio is generated at; the player covers any difference
    gain: float   # linear level match


def edge_gain(voice):
    return 10 ** (VOICE_GAIN_DB.get(voice, 0.0) / 20)


def end_date(config):
    try:
        return dt.date.fromisoformat(config.get("eleven_until") or "")
    except ValueError:
        return None


def german_date(day):
    return day.strftime("%d.%m.%Y")


class SpeechService:
    def __init__(self, config=None, on_disable=None, edge=None, eleven=None, key=api_key):
        self.config = config  # the app's live settings, used for prewarming
        self.on_disable = on_disable
        self.edge = edge or HighFidelityTTSClient()
        self.eleven = eleven or ElevenLabsClient(key)
        self.key = key
        self.disabled = None  # why ElevenLabs was switched off in this run
        self._lock = threading.Lock()

    def enable(self):
        self.disabled = None

    def disable(self, reason):
        with self._lock:
            if self.disabled:
                return
            self.disabled = reason
        logging.warning("ElevenLabs abgeschaltet: %s", reason)
        if self.on_disable:
            self.on_disable(reason)

    def route(self, config, today=None):
        if config.get("engine") == "elevenlabs" and not self.disabled:
            until = end_date(config)
            if until and (today or dt.date.today()) > until:
                self.disable(f"Der ElevenLabs-Zeitraum endete am {german_date(until)}.")
            elif not self.key():
                self.disable("Kein ElevenLabs-Schlüssel gefunden.")
            elif config.get("eleven_voice"):
                return Route("elevenlabs", native_speed(config["speed"]), 10 ** (ELEVEN_GAIN_DB / 20))
        return Route("edge", config["speed"], edge_gain(config["voice"]))

    async def prewarm(self):
        if self.config is not None and self.route(self.config).engine == "elevenlabs":
            await self.eleven.prewarm()
        else:
            await self.edge.prewarm()

    async def synthesize_stream(self, text, route, config, on_boundary=None,
                                previous_text=None, next_text=None, **_):
        if route.engine == "elevenlabs" and not self.disabled:
            produced = False
            try:
                async for piece in self.eleven.synthesize_stream(
                        text, config["eleven_voice"], config["eleven_model"], route.speed, on_boundary,
                        previous_text, next_text):
                    produced = True
                    yield piece
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if produced:
                    raise  # repeating audio would be worse than a short message
                if isinstance(error, ElevenLabsError) and error.permanent:
                    self.disable(str(error))
                else:
                    logging.warning("ElevenLabs nicht erreichbar (%s); Edge liest diesen Abschnitt", error)
        rate = f"{round((route.speed - 1) * 100):+d}%"
        async for piece in self.edge.synthesize_stream(speakable(text), voice=config["voice"], rate=rate,
                                                       pitch=config["pitch"], on_boundary=on_boundary):
            yield piece

    async def close(self):
        await asyncio.gather(self.edge.close(), self.eleven.close(), return_exceptions=True)
