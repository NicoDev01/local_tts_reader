"""Cancellable synthesis with one bounded buffer and serialized audio ownership."""
import asyncio
from dataclasses import dataclass, field
import logging
import queue
import threading
import time
from contextlib import nullcontext

import numpy as np

from audio_player import AudioPlayer, OUTPUT_SAMPLE_RATE
from high_fidelity_tts import HighFidelityTTSClient
from settings import VOICE_GAIN_DB
from text_cleaner import group_ranges, speakable, split_units


def voice_gain(voice):
    """Linear gain that levels this voice with the others."""
    return 10 ** (VOICE_GAIN_DB.get(voice, 0.0) / 20)


@dataclass
class Reading:
    cancel: threading.Event = field(default_factory=threading.Event)
    paused: threading.Event = field(default_factory=threading.Event)
    audio: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=4))
    done: threading.Event = field(default_factory=threading.Event)
    ready: threading.Event = field(default_factory=threading.Event)
    future: object = None
    buffer_lock: threading.Lock = field(default_factory=threading.Lock)
    buffered: float = 0.0
    started: float = field(default_factory=time.monotonic)
    buffering_count: int = 0
    units: list = field(default_factory=list)       # spoken sentences of the whole text
    sections: list = field(default_factory=list)    # (first, end) unit ranges sent as one request
    first: int = 0                                  # unit this reading starts at
    boundaries: dict = field(default_factory=dict)  # section -> [(seconds, unit)]
    words: dict = field(default_factory=dict)       # section -> [(seconds, char, length, duration)]
    speed: float = 1.0                              # tempo the service was asked for
    unit_chars: dict = field(default_factory=dict)  # section -> char start of each unit

    def reserve(self, seconds):
        with self.buffer_lock:
            self.buffered += seconds

    def buffered_seconds(self):
        with self.buffer_lock:
            return max(0.0, self.buffered)

    def section_text(self, section):
        start, end = self.sections[section]
        return ' '.join(self.units[start:end])

    def boundary_handler(self, section):
        """Map the service's sentence starts to our units by locating their text."""
        start, end = self.sections[section]
        flat = lambda value: ' '.join(value.split())
        offsets, position, text = [], 0, ''
        for unit in self.units[start:end]:
            offsets.append(len(text))
            text += flat(unit) + ' '
        found = self.boundaries[section] = []  # a retried request starts over
        words = self.words[section] = []
        self.unit_chars[section] = offsets
        word_position = 0

        def handle(seconds, spoken, kind="sentence", duration=0.0):
            nonlocal position, word_position
            if kind == "word":
                probe = flat(spoken)
                at = text.find(probe, word_position) if probe else -1
                if at >= 0:
                    word_position = at + len(probe)
                    words.append((seconds, at, len(probe), duration))
                return
            probe = flat(spoken)[:24]
            at = text.find(probe, position) if probe else -1
            if at >= 0:
                position = at
            unit = start + max(i for i, o in enumerate(offsets) if o <= position)
            found.append((seconds, unit))
        return handle


class PlaybackController:
    def __init__(self, notify, config, client=None, player=None):
        self.notify = notify
        self.player = player or AudioPlayer()
        self.player.set_controls(config["speed"], config["volume"])
        self.player.set_profile(config["sound_profile"])
        self.loop = asyncio.new_event_loop()
        self.client = client or HighFidelityTTSClient()
        self.thread = threading.Thread(target=self._network_loop, daemon=True, name="tts-network")
        self.thread.start()
        self.current = None
        self._audio_lock = threading.Lock()
        self._workers = []
        self._request_seconds = 2.0

    def _network_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self):
        if self.current:
            self.current.cancel.set()
            if self.current.future:
                self.current.future.cancel()
        self.current = None

    def start(self, text, config, units=None, first=0):
        """Read ``text`` or, for navigation, the given units from ``first`` on."""
        self.stop()
        job = Reading()
        job.units = list(units) if units is not None else split_units(text)
        job.first = max(0, min(first, len(job.units)))
        job.speed = config["speed"]
        job.sections = [(start + job.first, end + job.first)
                        for start, end in group_ranges(job.units[job.first:])]
        self.current = job
        self._workers = [t for t in self._workers if t.is_alive()]
        for target, name in ((lambda: self._fetch(job, config.copy()), "tts-fetch"),
                             (lambda: self._play(job), "tts-play")):
            thread = threading.Thread(target=target, daemon=True, name=name)
            self._workers.append(thread)
            thread.start()
        return job

    def _post(self, job, kind, value=None):
        if not job.cancel.is_set():
            self.notify(job, kind, value)

    def _put(self, job, item):
        while not job.cancel.is_set():
            try:
                job.audio.put(item, timeout=.05)
                return True
            except queue.Full:
                pass
        return False

    def position(self):
        """Current unit and seconds spoken of it, or None before audio started."""
        job = self.current
        cursor = getattr(self.player, 'cursor', None)
        if not job or not cursor or cursor[0] is None or cursor[0][0] is not job:
            return None
        _, section = cursor[0]
        seconds = cursor[1]  # into the section's request audio
        unit, unit_start = job.sections[section][0], 0.0
        for offset, mapped in list(job.boundaries.get(section, ())):
            if offset <= seconds + .05 and mapped != unit:
                unit, unit_start = mapped, offset
        return unit, max(0.0, seconds - unit_start)

    def current_word(self):
        """(unit, char offset in the unit's text, length) of the word being spoken, or None."""
        job = self.current
        cursor = getattr(self.player, 'cursor', None)
        if not job or not cursor or cursor[0] is None or cursor[0][0] is not job:
            return None
        _, section = cursor[0]
        spoken = [w for w in list(job.words.get(section, ())) if w[0] <= cursor[1] + .02]
        if not spoken:
            return None
        _, at, length, _ = spoken[-1]
        offsets = job.unit_chars[section]
        index = max(i for i, o in enumerate(offsets) if o <= at)
        return job.sections[section][0] + index, at - offsets[index], length

    def sentence_finished(self, unit):
        """True once the last word of ``unit`` has been spoken (the pause before the next)."""
        job = self.current
        cursor = getattr(self.player, 'cursor', None)
        if not job or not cursor or cursor[0] is None or cursor[0][0] is not job:
            return False
        _, section = cursor[0]
        start, end = job.sections[section]
        if not start <= unit < end:
            return False
        offsets = job.unit_chars.get(section, [])
        low = offsets[unit - start]
        high = offsets[unit - start + 1] if unit - start + 1 < len(offsets) else float('inf')
        inside = [w for w in list(job.words.get(section, ())) if low <= w[1] < high]
        if not inside:
            return False
        last = max(inside, key=lambda w: w[1])
        return cursor[1] >= last[0] + last[3]

    def respeed(self, config):
        """The service speaks at the requested tempo; stretching that audio later sounds
        warped. So a new tempo is generated afresh: right away early in a sentence,
        otherwise from the next sentence. Returns that next unit, to switch at its start."""
        job = self.current
        if not job or job.done.is_set() or not job.units or abs(job.speed - config["speed"]) < .01:
            return None
        position = self.position()
        if not position:
            self.start(None, config, units=job.units, first=job.first)
            return None
        unit, since = position
        if since < 1.5:
            self.start(None, config, units=job.units, first=unit)
            return None
        return unit + 1 if unit + 1 < len(job.units) else None

    def jump(self, delta, config):
        """Restart at the next (+1) or previous (-1) sentence.

        Like a music player, "back" first returns to the start of the current
        sentence and only goes one further when pressed early in a sentence.
        """
        job = self.current
        if not job or not job.units:
            return None
        unit, since = self.position() or (job.first, 0.0)
        target = unit if delta < 0 and since > 2.0 else unit + delta
        if target >= len(job.units):
            return None
        return self.start(None, config, units=job.units, first=max(0, target))

    def prewarm(self):
        """Open the service connection while the selection is being copied."""
        if hasattr(self.client, 'prewarm'):
            asyncio.run_coroutine_threadsafe(self.client.prewarm(), self.loop)

    @staticmethod
    def _voice_args(config):
        return dict(voice=config["voice"], rate=f'{round((config["speed"] - 1) * 100):+d}%',
                    pitch=config["pitch"])

    async def _synthesize(self, text, config):
        return await asyncio.wait_for(self.client.synthesize(
            speakable(text.strip()), **self._voice_args(config)), timeout=35)

    def _stream_part(self, job, part, index, total, config):
        """Queue a section in pieces while the service is still speaking.

        Returns the queued seconds, or None if cancelled. Raises with
        ``queued`` set when a failure happens after audio was handed over.
        """
        pieces = queue.Queue()  # one section at most; never blocks the event loop

        section = index - 1
        on_boundary = job.boundary_handler(section)

        async def pump():
            try:
                async for samples, sr in self.client.synthesize_stream(
                        speakable(part.strip()), on_boundary=on_boundary, **self._voice_args(config)):
                    pieces.put(("audio", samples, sr))
                pieces.put(("end", None, None))
            except BaseException as error:
                pieces.put(("error", error, None))
                raise

        future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(pump(), 35), self.loop)
        job.future = future
        preparer = self.player.stream_section(config["speed"], voice_gain(config["voice"]))
        pending, sr, queued = [], None, 0.0
        # Start as early as possible, then hand over larger pieces. The last
        # 0.4 s stay pending so the section's trailing silence is trimmed whole.
        first_seconds, next_seconds, hold_seconds = .3, 1.2, .4

        def emit(final):
            nonlocal pending, queued
            audio = np.concatenate(pending) if pending else np.zeros(0, dtype=np.float32)
            keep = 0 if final else int(sr * hold_seconds)
            pending = [audio[len(audio) - keep:]] if keep else []
            audio = audio[:len(audio) - keep]
            prepared = preparer.push(audio, sr, final)
            if prepared is None:
                return True
            prepared.marker = (job, section)
            seconds = len(audio) / sr * config["speed"] / 2
            job.reserve(seconds)
            if not self._put(job, ("audio", (prepared, OUTPUT_SAMPLE_RATE, part, index, total, seconds))):
                job.reserve(-seconds)
                return False
            queued += seconds
            job.ready.set()
            return True

        try:
            while True:
                if job.cancel.is_set():
                    return None
                try:
                    kind, value, rate = pieces.get(timeout=.05)
                except queue.Empty:
                    continue
                if kind == "error":
                    if job.cancel.is_set():
                        return None  # stop() cancelled the request
                    if isinstance(value, asyncio.CancelledError):
                        # wait_for cancels the pump when the section takes too long
                        value = TimeoutError("Sprachdienst antwortet zu langsam")
                    value.queued = queued
                    raise value
                if kind == "end":
                    if sr is None:
                        error = RuntimeError("Sprachdienst liefert kein Audio")
                        error.queued = 0.0
                        raise error
                    return queued if emit(True) else None
                sr = rate
                pending.append(value)
                buffered = sum(map(len, pending)) / sr
                if buffered >= (first_seconds if not queued else next_seconds) + hold_seconds:
                    if not emit(False):
                        return None
        finally:
            if not future.done():
                future.cancel()
            job.future = None

    def _fetch(self, job, config):
        try:
            parts = [job.section_text(section) for section in range(len(job.sections))]
            if not parts:
                self._put(job, ("error", "Kein vorlesbarer Text vorhanden."))
                return
            for index, part in enumerate(parts, 1):
                if job.cancel.is_set():
                    return
                # Reserve buffer room before starting another network request.
                # Seconds are measured at 2x, so a later speed increase cannot
                # silently halve our reserve. The item cap also bounds short lists.
                target = min(12.0, max(2.5, self._request_seconds * 1.6 + .5))
                while job.audio.full() or job.buffered_seconds() >= max(8.0, target * 2):
                    if job.cancel.wait(.05):
                        return
                if hasattr(self.player, 'controls'):
                    config['speed'] = round(self.player.controls()[0] * 100) / 100
                if hasattr(self.client, 'synthesize_stream') and hasattr(self.player, 'stream_section'):
                    if self._fetch_streamed(job, part, index, len(parts), config) is None:
                        return
                    continue
                audio, sr = None, None
                last_err = None
                for attempt in range(3):
                    if job.cancel.is_set():
                        return
                    request_started = time.monotonic()
                    future = asyncio.run_coroutine_threadsafe(self._synthesize(part, config), self.loop)
                    job.future = future
                    if job.cancel.is_set():
                        future.cancel()
                        return
                    try:
                        audio, sr = future.result(timeout=40)
                    except Exception as e:
                        last_err = e
                        logging.warning("Spracherzeugung für Teil %d/%d (Versuch %d/3) fehlgeschlagen: %s",
                                        index, len(parts), attempt + 1, e)
                    finally:
                        if not future.done():
                            future.cancel()
                        job.future = None
                    if audio is not None and len(audio):
                        break
                    if attempt < 2 and not job.cancel.is_set():
                        if job.cancel.wait(0.5 * (attempt + 1)):
                            return
                if audio is None or not len(audio):
                    if last_err:
                        raise last_err
                    raise RuntimeError("Sprachdienst liefert kein Audio")
                seconds = len(audio) / sr * config["speed"] / 2
                if hasattr(self.player, 'prepare'):
                    audio = self.player.prepare(audio, sr, config["speed"], voice_gain(config["voice"]))
                elapsed = time.monotonic() - request_started
                self._request_seconds = .7 * self._request_seconds + .3 * elapsed
                target = min(12.0, max(2.5, self._request_seconds * 1.6 + .5))
                job.reserve(seconds)
                if not self._put(job, ("audio", (audio, sr, part, index, len(parts), seconds))):
                    job.reserve(-seconds)
                    return
                if job.buffered_seconds() >= target or job.audio.full() or index == len(parts):
                    job.ready.set()
            self._put(job, ("done", None))
        except Exception:
            if not job.cancel.is_set():
                logging.exception("Spracherzeugung fehlgeschlagen")
                self._put(job, ("error", "Vorlesen unterbrochen. Internetverbindung oder Sprachdienst prüfen."))
        finally:
            job.ready.set()

    def _fetch_streamed(self, job, part, index, total, config):
        """Up to three attempts while nothing of the section has been played yet."""
        for attempt in range(3):
            if job.cancel.is_set():
                return None
            request_started = time.monotonic()
            try:
                queued = self._stream_part(job, part, index, total, config)
            except Exception as error:
                if getattr(error, 'queued', 0) or job.cancel.is_set() or attempt == 2:
                    raise
                logging.warning("Spracherzeugung für Teil %d/%d (Versuch %d/3) fehlgeschlagen: %s",
                                index, total, attempt + 1, error)
                if job.cancel.wait(0.5 * (attempt + 1)):
                    return None
                continue
            if queued is not None:
                elapsed = time.monotonic() - request_started
                self._request_seconds = .7 * self._request_seconds + .3 * elapsed
            return queued

    def _play(self, job):
        result = None
        try:
            with self._audio_lock:
                while not job.ready.wait(.05):
                    if job.cancel.is_set():
                        return
                if job.cancel.is_set():
                    return
                session = self.player.session(job.cancel) if hasattr(self.player, 'session') else nullcontext()
                with session:
                    result = self._play_sections(job)
                # Report completion only after the driver's remaining audio drains.
                if result:
                    self._post(job, *result)
        except Exception:
            if not job.cancel.is_set():
                logging.exception("Audioausgabe fehlgeschlagen")
                self._post(job, "error", "Audioausgabe nicht verfügbar. Ausgabegerät prüfen.")
        finally:
            job.cancel.set()
            if job.future:
                job.future.cancel()
            job.done.set()

    def _play_sections(self, job):
        waiting = False
        first = True
        shown = None  # a streamed section arrives in several pieces
        while not job.cancel.is_set():
            try:
                kind, item = job.audio.get_nowait()
            except queue.Empty:
                if not waiting:
                    waiting = True
                    job.buffering_count += 1
                    self._post(job, "buffering", "Nächsten Abschnitt laden …")
                if hasattr(self.player, 'write_silence'):
                    self.player.write_silence()
                else:
                    job.cancel.wait(.02)
                continue
            if kind == "done":
                return "done", None
            if kind == "error":
                return "error", item
            audio, sr, part, index, total, seconds = item
            job.reserve(-seconds)
            waiting = False
            if first:
                logging.info("Audiostart nach %.2f s; Reserve %.2f s bei 2x",
                             time.monotonic() - job.started, seconds + job.buffered_seconds())
                first = False
            if index != shown:
                shown = index
                self._post(job, "progress", (index, total))
            self.player.play(audio, sr, part, job.cancel, job.paused)

    def toggle_pause(self):
        job = self.current
        if not job or job.done.is_set():
            return False
        if job.paused.is_set():
            job.paused.clear()
        else:
            job.paused.set()
        return job.paused.is_set()

    def close(self):
        self.stop()
        for worker in self._workers:
            worker.join(timeout=1)
        async def cleanup():
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await self.client.close()
        try:
            asyncio.run_coroutine_threadsafe(cleanup(), self.loop).result(timeout=3)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
            if not self.thread.is_alive():
                self.loop.close()
            if hasattr(self.player, 'close'):
                self.player.close()
