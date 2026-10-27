"""ElevenLabs speech synthesis: streamed PCM with character timings, plus account checks.

API details checked against elevenlabs.io/docs on 2026-10-27: stream-with-timestamps returns JSON
chunks with ``audio_base64`` and per-character ``alignment``; ``voice_settings.speed`` accepts 0.7–1.2
(not honoured by v3, see ``MODELS``).
"""
import asyncio
import base64
import codecs
import json
import logging
import os
import re
import time
import winreg
from pathlib import Path
from typing import NamedTuple

import aiohttp
import numpy as np

API = "https://api.elevenlabs.io"
KEY_NAME = "ELEVENLABS_API_KEY"
ENV_FILE = Path(__file__).resolve().parent / ".env"
SAMPLE_RATE = 24000
SPEED_RANGE = (.7, 1.2)

class Model(NamedTuple):
    label: str
    factor: float    # credits per character (pricing page: Flash costs half of v2 and v3)
    language: bool   # ``language_code`` accepted
    tempo: bool      # ``voice_settings.speed`` honoured; otherwise it speaks at its own pace
    context: bool    # ``previous_text``/``next_text`` accepted
    tags: bool = False  # [square brackets] are performed as audio tags instead of read


# Models for German reading on the text-to-speech endpoint (measured live 2026-10-27).
# v3 ignores the speed setting and rejects previous_text/next_text with 400.
MODELS = {"eleven_v3": Model("v3 · beste Qualität, eigenes Tempo", 1.0, True, False, False, True),
          "eleven_flash_v2_5": Model("Flash v2.5 · schnell, halber Preis", .5, True, True, True),
          "eleven_multilingual_v2": Model("Multilingual v2 · Start nach ~2 s", 1.0, False, True, True)}
_FALLBACK_MODEL = Model("", 1.0, False, True, True)
ACCOUNT_SECONDS = 300   # account figures older than this are refreshed before trusting them
QUOTA_RESERVE = 2000    # credits kept free so a reading never runs into paid overage
INACTIVE = {"free", "free_disabled", "past_due", "incomplete"}
_SENTENCE_END = re.compile(r"[.!?…:]['\"»«)]*$")


def api_key():
    """Key from the environment, the user's Windows environment (no restart needed) or ``.env``."""
    key = os.environ.get(KEY_NAME, "").strip()
    if not key:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                key = str(winreg.QueryValueEx(reg, KEY_NAME)[0]).strip()
        except OSError:
            pass
    if not key:
        try:
            for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
                name, _, value = line.partition("=")
                if name.strip().removeprefix("export ").strip() == KEY_NAME:
                    key = value.strip().strip("'\"")
        except OSError:
            pass
    return key or None


def native_speed(speed):
    """Tempo the service is asked for; the player covers the rest beyond 0.7–1.2."""
    return min(SPEED_RANGE[1], max(SPEED_RANGE[0], speed))


class ElevenLabsError(Exception):
    """``permanent``: retrying will not help (key, quota, voice), so switch back to Edge."""

    def __init__(self, message, permanent=False, status=None, code=""):
        super().__init__(message)
        self.permanent, self.status, self.code = permanent, status, code


def _error(status, body):
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, AttributeError):
        detail = None
    code = detail.get("status", "") if isinstance(detail, dict) else ""
    text = detail.get("message", "") if isinstance(detail, dict) else ""
    if code == "quota_exceeded":
        message = "ElevenLabs-Kontingent ist aufgebraucht."
    elif code == "invalid_api_key" or status == 401 and not code:
        message = "ElevenLabs-Schlüssel ist ungültig."
    elif status in (401, 402, 403):
        message = f"ElevenLabs verweigert den Zugriff ({code or status})."
    elif status == 404:
        message = "ElevenLabs-Stimme wurde nicht gefunden."
    elif status in (400, 422):
        message = f"ElevenLabs lehnt die Anfrage ab: {text or code or status}"
    else:  # 429 busy or too many requests, 5xx: worth another try later
        return ElevenLabsError(f"ElevenLabs antwortet mit {status} {code}".strip(), False, status, code)
    return ElevenLabsError(message, True, status, code)


class Timings:
    """Turn per-character timings into the word and sentence starts the player follows."""

    def __init__(self, text, on_boundary):
        self.text, self.on_boundary = text, on_boundary
        self.index = 0          # characters of ``text`` already timed
        self.word = None        # (first char index, start seconds, end seconds)
        self.last_start = -1.0

    def add(self, alignment, offset):
        chars = alignment.get("characters") or []
        starts = alignment.get("character_start_times_seconds") or []
        ends = alignment.get("character_end_times_seconds") or []
        # Chunks normally carry times from the start of the request; relative ones are shifted.
        shift = offset if starts and starts[0] + .02 < self.last_start else 0.0
        for char, start, end in zip(chars, starts, ends):
            start, end = start + shift, end + shift
            self.last_start = start
            if char.isspace():
                self._end_word()
            else:
                if self.word is None:
                    self._start_word(start)
                self.word = (self.word[0], self.word[1], end)
            self.index += len(char)

    def _start_word(self, start):
        before = self.text[:self.index].rstrip()
        if not before or _SENTENCE_END.search(before):
            self.on_boundary(start, self.text[self.index:self.index + 40], "sentence", 0.0)
        self.word = (self.index, start, start)

    def _end_word(self):
        if self.word:
            first, start, end = self.word
            self.on_boundary(start, self.text[first:self.index], "word", max(0.0, end - start))
            self.word = None

    def finish(self):
        self._end_word()


class ElevenLabsClient:
    def __init__(self, key=api_key, base=API):
        self.key, self.base = key, base
        self._session = None
        self._account, self._account_at, self._sent = None, 0.0, 0
        self._last_contact = 0.0
        self._refresh = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(sock_connect=6.0, sock_read=15.0)
            self._session = aiohttp.ClientSession(timeout=timeout,
                                                  connector=aiohttp.TCPConnector(keepalive_timeout=30.0))
        return self._session

    def _headers(self):
        key = self.key()
        if not key:
            raise ElevenLabsError("Kein ElevenLabs-Schlüssel gefunden.", True)
        return {"xi-api-key": key}

    async def _get(self, path):
        session = await self._get_session()
        async with session.get(self.base + path, headers=self._headers()) as response:
            self._last_contact = time.monotonic()
            body = await response.text()
            if response.status != 200:
                raise _error(response.status, body)
            return json.loads(body)

    # -- account ---------------------------------------------------------------------
    async def account(self, refresh=False):
        """Subscription figures (tier, status, credits), cached; None if the key may not read them."""
        if refresh or self._account is None or time.monotonic() - self._account_at > ACCOUNT_SECONDS:
            try:
                fresh = await self._get("/v1/user/subscription")
            except ElevenLabsError as error:
                if error.code == "missing_permissions":
                    return None
                raise
            # The service counts with a delay (measured 2026-10-27), so requests sent since the
            # last check stay pending until its counter has caught up with them.
            counted = fresh.get("character_count", 0) - (self._account or {}).get("character_count", 0)
            self._sent = max(0, self._sent - counted) if self._account and counted >= 0 else 0
            self._account, self._account_at = fresh, time.monotonic()
        return self._account

    def remaining(self):
        """Credits left by the last account check minus what was sent since, or None."""
        account = self._account
        if not account or "character_limit" not in account:
            return None
        return account["character_limit"] - account.get("character_count", 0) - self._sent

    async def check(self, characters):
        """Raise a permanent error when the plan has ended or ``characters`` would reach overage."""
        account = await self.account()
        if account is None:
            return  # restricted key: the service itself reports an exhausted quota
        if account.get("tier") == "free" or account.get("status") in INACTIVE:
            raise ElevenLabsError("Das ElevenLabs-Abo ist nicht mehr aktiv.", True)
        if self.remaining() < characters + QUOTA_RESERVE:
            account = await self.account(refresh=True)
            if account and self.remaining() < characters + QUOTA_RESERVE:
                raise ElevenLabsError(f"ElevenLabs-Kontingent fast aufgebraucht "
                                      f"(noch {max(0, self.remaining()):,} Credits).".replace(",", "."), True)

    async def catalog(self):
        """Voices of the account (native German first, then German-capable) and the account figures."""
        data = await self._get("/v2/voices?page_size=100")
        voices = []
        for voice in data.get("voices", []):
            labels = voice.get("labels") or {}
            german = any(v.get("language") == "de" for v in voice.get("verified_languages") or [])
            rank = 0 if labels.get("language") == "de" else 1 if german else 2
            name = re.split(r" [-|] ", voice.get("name", ""))[0].strip()
            voices.append((rank, name, voice["voice_id"]))
        voices.sort(key=lambda v: (v[0], v[1].lower()))
        return dict(voices=[(voice_id, name) for _, name, voice_id in voices],
                    account=await self.account(refresh=True))

    # -- speech ----------------------------------------------------------------------
    async def prewarm(self):
        """Open a connection (and refresh the account figures) shortly before a reading."""
        if time.monotonic() - self._last_contact < 20 or (self._refresh and not self._refresh.done()):
            return

        async def refresh():
            try:
                await self.account(refresh=time.monotonic() - self._account_at > 60)
                if time.monotonic() - self._last_contact > 20:
                    await self._get("/v1/models")
            except Exception as error:
                logging.debug("ElevenLabs-Vorbereitung fehlgeschlagen: %s", error)
        self._refresh = asyncio.ensure_future(refresh())

    async def synthesize_stream(self, text, voice, model, speed=1.0, on_boundary=None,
                                previous_text=None, next_text=None):
        """Yield 24 kHz Float32 mono pieces while ElevenLabs is still speaking."""
        if not text.strip():
            return
        spec = MODELS.get(model, _FALLBACK_MODEL)
        factor = spec.factor
        await self.check(int(len(text) * factor))
        # Same length, so the character timings still line up with ``text``.
        spoken = text.replace("[", "(").replace("]", ")") if spec.tags else text
        body = dict(text=spoken, model_id=model)
        if spec.tempo:
            body["voice_settings"] = dict(speed=native_speed(speed))
        if spec.language:
            body["language_code"] = "de"
        if previous_text and spec.context:
            body["previous_text"] = previous_text[-300:]
        if next_text and spec.context:
            body["next_text"] = next_text[:300]
        session = await self._get_session()
        url = f"{self.base}/v1/text-to-speech/{voice}/stream/with-timestamps?output_format=pcm_{SAMPLE_RATE}"
        timings = Timings(text, on_boundary) if on_boundary else None
        async with session.post(url, json=body, headers=self._headers()) as response:
            self._last_contact = time.monotonic()
            if response.status != 200:
                raise _error(response.status, await response.text())
            self._sent += int(len(text) * factor)
            decoder, buffer, carry, samples = json.JSONDecoder(), "", b"", 0
            utf8 = codecs.getincrementaldecoder("utf-8")()
            async for data in response.content.iter_any():
                buffer += utf8.decode(data)
                while True:
                    buffer = buffer.lstrip(" \r\n\t,[]")
                    if not buffer:
                        break
                    try:
                        chunk, end = decoder.raw_decode(buffer)
                    except ValueError:
                        break  # incomplete; wait for more bytes
                    buffer = buffer[end:]
                    if timings and chunk.get("alignment"):
                        timings.add(chunk["alignment"], samples / SAMPLE_RATE)
                    pcm = carry + base64.b64decode(chunk.get("audio_base64") or "")
                    usable = len(pcm) - len(pcm) % 2
                    carry = pcm[usable:]
                    if usable:
                        audio = np.frombuffer(pcm[:usable], dtype="<i2").astype(np.float32) / 32768
                        samples += len(audio)
                        yield audio, SAMPLE_RATE
            if timings:
                timings.finish()
            if not samples:
                raise ElevenLabsError("ElevenLabs lieferte kein Audio.")

    async def close(self):
        if self._refresh and not self._refresh.done():
            self._refresh.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
