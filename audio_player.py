"""Audio output with pitch-preserving live tempo and ramped live volume."""

import threading
import logging
import math
from dataclasses import dataclass
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import sounddevice as sd
import soxr
import pedalboard as pb

OUTPUT_SAMPLE_RATE = 48000
OUTPUT_CHANNELS = 2

# Dry EQ profiles. The default avoids compression pumping and limiter latency.
MASTERING_PROFILES = {
    "studio_warmth": pb.Pedalboard([
        pb.HighpassFilter(cutoff_frequency_hz=70.0),
        pb.PeakFilter(cutoff_frequency_hz=220.0, gain_db=0.8, q=0.8),
        pb.PeakFilter(cutoff_frequency_hz=3200.0, gain_db=1.4, q=0.9),       # Clear speech presence / vocal intelligibility
        pb.HighShelfFilter(cutoff_frequency_hz=8500.0, gain_db=-0.8),
    ]),
    "headphone_comfort": pb.Pedalboard([
        pb.HighpassFilter(cutoff_frequency_hz=80.0),
        pb.PeakFilter(cutoff_frequency_hz=480.0, gain_db=-1.8, q=1.0),
        pb.PeakFilter(cutoff_frequency_hz=6200.0, gain_db=-3.8, q=1.1),      # Deep de-esser (zero ear fatigue)
        pb.PeakFilter(cutoff_frequency_hz=200.0, gain_db=1.8, q=0.7),        # Intimate proximity warmth
        pb.PeakFilter(cutoff_frequency_hz=3200.0, gain_db=0.8, q=0.9),
        pb.Compressor(threshold_db=-18.0, ratio=2.2, attack_ms=10.0, release_ms=150.0),
        pb.HighShelfFilter(cutoff_frequency_hz=8500.0, gain_db=-3.8),       # Warm, dark acoustic slope
        pb.Limiter(threshold_db=-1.0),
    ]),
    "night_whisper": pb.Pedalboard([
        pb.HighpassFilter(cutoff_frequency_hz=90.0),
        pb.PeakFilter(cutoff_frequency_hz=6000.0, gain_db=-4.0, q=1.2),
        pb.PeakFilter(cutoff_frequency_hz=240.0, gain_db=1.0, q=0.8),
        pb.HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=-4.5),
        pb.Compressor(threshold_db=-20.0, ratio=2.6, attack_ms=15.0, release_ms=160.0),
        pb.Limiter(threshold_db=-2.0),
    ]),
    "crystal_clear": pb.Pedalboard([
        pb.HighpassFilter(cutoff_frequency_hz=95.0),
        pb.PeakFilter(cutoff_frequency_hz=1800.0, gain_db=1.0, q=1.0),
        pb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=2.2, q=1.0),       # High speech intelligibility
        pb.HighShelfFilter(cutoff_frequency_hz=9500.0, gain_db=-1.5),
        pb.Compressor(threshold_db=-14.0, ratio=2.5, attack_ms=8.0, release_ms=100.0),
        pb.Limiter(threshold_db=-1.0),
    ]),
    "bypass": pb.Pedalboard([]),
}


def trim_silence(audio: np.ndarray, sr: int = 24000, threshold: float = 0.0003, pad_ms: float = 75.0) -> np.ndarray:
    """Trims raw MP3 padding silence while preserving natural vocal decay and 8ms boundary smoothing."""
    pad_samples = int(sr * (pad_ms / 1000.0))
    nonzeros = np.where(np.abs(audio) > threshold)[0]
    if len(nonzeros) == 0:
        return audio
    start = max(0, nonzeros[0] - pad_samples)
    end = min(len(audio), nonzeros[-1] + pad_samples + 1)
    trimmed = audio[start:end].copy()

    fade_len = min(int(sr * 0.008), len(trimmed) // 4)
    if fade_len > 0:
        fade_in = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
        fade_out = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_len, dtype=np.float32)))
        trimmed[:fade_len] *= fade_in
        trimmed[-fade_len:] *= fade_out
    return trimmed


def calculate_adaptive_pause(text: str) -> float:
    """Editorial breaths between sections; punctuation is retained."""
    t = text.rstrip()
    if t.endswith(":"):
        return .42 if text.endswith("\n\n") else .35
    if text.endswith("\n\n"):
        return .52
    if t.endswith((";", ")", "]", '"', "»", "”")):
        return .18
    if t.endswith(","):
        return .10
    if t.endswith((".", "!", "?")):
        return .20
    return .08


@dataclass
class PreparedAudio:
    source: np.ndarray
    speed: float
    rendered: np.ndarray | None = None
    rate: float = 1.0
    final: bool = True  # only the last piece of a section is followed by its pause
    start: float = 0.0  # seconds into the section's request audio where this piece begins
    marker: object = None  # identifies the section for the player's cursor


class SectionStream:
    """Prepare one section piece by piece while it downloads.

    Resampling and filters keep their state across pieces, so the joins are
    seamless; silence is trimmed only at the section's start and end.
    """
    FADE = int(OUTPUT_SAMPLE_RATE * .008)

    def __init__(self, player, speed, gain=1.0):
        self.player, self.speed, self.gain = player, speed, gain
        self.resampler = None
        self.voiced = False      # leading silence already trimmed
        self.filtered = False    # filter state initialized
        self.faded_in = False
        self.position = 0.0      # request-audio seconds covered by returned pieces

    def push(self, audio, sr, final):
        audio = np.asarray(audio, dtype=np.float32) * self.gain
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if not math.isfinite(sr) or sr <= 0 or not np.all(np.isfinite(audio)):
            raise ValueError("Ungültige Audiodaten")
        if not self.voiced:
            voiced = np.where(np.abs(audio) > 0.0003)[0]
            if not len(voiced) and not final:
                self.position += len(audio) / sr
                return None  # leading service padding
            lead = max(0, voiced[0] - int(sr * .075)) if len(voiced) else 0
            self.position += lead / sr
            audio = audio[lead:]
            self.voiced = True
        if final:
            voiced = np.where(np.abs(audio) > 0.0003)[0]
            audio = audio[:voiced[-1] + int(sr * .075) + 1] if len(voiced) else audio[:0]
        if self.resampler is None:
            self.resampler = soxr.ResampleStream(sr, OUTPUT_SAMPLE_RATE, 1, dtype="float32", quality="HQ")
        audio = self.resampler.resample_chunk(audio, last=final)
        with self.player._lock:
            board = MASTERING_PROFILES[self.player.profile]
        if len(board) and len(audio):
            with self.player._dsp_lock:
                audio = board(audio, OUTPUT_SAMPLE_RATE, reset=not self.filtered)
            self.filtered = True
        audio = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        if not self.faded_in and len(audio):
            n = min(self.FADE, len(audio) // 4)
            audio[:n] *= 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, n, dtype=np.float32)))
            self.faded_in = True
        if final and len(audio):
            n = min(self.FADE, len(audio) // 4)
            audio[len(audio) - n:] *= 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, n, dtype=np.float32)))
        if not len(audio) and not final:
            return None
        prepared = PreparedAudio(audio, self.speed, final=final, start=self.position)
        self.position += len(audio) / OUTPUT_SAMPLE_RATE
        prepared.rate = self.player.controls()[0] / self.speed
        if abs(prepared.rate - 1.0) > 1e-6 and len(audio):
            prepared.rendered = self.player._stretch(audio, prepared.rate)
        return prepared


class AudioPlayer:
    def __init__(self, stream_factory=None):
        self._lock = threading.Lock()
        self._dsp_lock = threading.Lock()
        self.speed, self.volume = 1.0, 1.0
        self.profile = "studio_warmth"
        self.stream_factory = stream_factory or sd.OutputStream
        self._last_gain = 1.0
        self._stream = None
        self.cursor = None  # (marker, seconds) of the block just written
        self.underflows = 0
        self.startup_underflows = 0
        self._tempo_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-tempo")
        self._silence = np.zeros((960, OUTPUT_CHANNELS), dtype=np.float32)

    def set_controls(self, speed, volume):
        speed, volume = float(speed), float(volume)
        if not math.isfinite(speed) or not math.isfinite(volume):
            raise ValueError("Tempo und Lautstärke müssen endliche Zahlen sein")
        with self._lock:
            self.speed = min(2., max(.7, float(speed)))
            self.volume = min(1.5, max(0., float(volume)))

    def set_profile(self, profile):
        with self._lock:
            self.profile = profile if profile in MASTERING_PROFILES else "studio_warmth"

    def controls(self):
        with self._lock:
            return self.speed, self.volume

    def _prepare(self, audio, sr, gain=1.0):
        audio = np.asarray(audio, dtype=np.float32) * gain
        if (audio.ndim not in (1, 2) or not audio.size or not math.isfinite(sr)
                or sr <= 0 or not np.all(np.isfinite(audio))):
            raise ValueError("Ungültige Audiodaten")
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        audio = trim_silence(audio, sr)
        if sr != OUTPUT_SAMPLE_RATE:
            audio = soxr.resample(audio, sr, OUTPUT_SAMPLE_RATE, quality="HQ")
        with self._lock:
            board = MASTERING_PROFILES[self.profile]
        if len(board):
            with self._dsp_lock:
                audio = board(audio, OUTPUT_SAMPLE_RATE, reset=True)
        return np.ascontiguousarray(audio, dtype=np.float32)

    def _gain(self, mono):
        _, volume = self.controls()
        ramp = np.linspace(self._last_gain, volume, len(mono), dtype=np.float32)
        self._last_gain = volume
        mono = mono * ramp
        # Transparent below 90%; a smooth knee avoids hard clipping at >100% volume.
        magnitude = np.abs(mono)
        peaks = magnitude > .9
        mono[peaks] = np.sign(mono[peaks]) * (.9 + .08 * np.tanh((magnitude[peaks] - .9) / .08))
        return np.ascontiguousarray(np.column_stack((mono, mono)), dtype=np.float32)

    @staticmethod
    def _stretch(source, rate):
        rendered = source.copy() if rate == 1 else pb.time_stretch(
            source, OUTPUT_SAMPLE_RATE, stretch_factor=rate,
            transient_mode="crisp", use_long_fft_window=False, preserve_formants=True)
        return np.asarray(rendered, dtype=np.float32).reshape(-1)

    def close(self):
        self._tempo_worker.shutdown(wait=True, cancel_futures=True)

    def prepare(self, audio, sr, speed, gain=1.0):
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Ungültiges Quelltempo")
        prepared = PreparedAudio(self._prepare(audio, sr, gain), speed)
        prepared.rate = self.controls()[0] / speed
        if abs(prepared.rate - 1.0) > 1e-6:
            prepared.rendered = self._stretch(prepared.source, prepared.rate)
        return prepared

    def stream_section(self, speed, gain=1.0):
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Ungültiges Quelltempo")
        return SectionStream(self, speed, gain)

    @contextmanager
    def session(self, cancel):
        """Keep one device stream open across all prepared sections of a reading."""
        stream = self.stream_factory(samplerate=OUTPUT_SAMPLE_RATE, channels=2,
                                     dtype="float32", blocksize=960, latency="high")
        self._stream = stream
        self.underflows = 0
        self.startup_underflows = 0
        try:
            stream.start()
            self._last_gain = self.controls()[1]
            # Some Windows/Bluetooth drivers report an empty buffer on their
            # very first write. Prime with 100 ms silence before any consonant.
            self.startup_underflows = int(bool(stream.write(np.zeros((4800, 2), dtype=np.float32))))
            yield
            if cancel.is_set():
                stream.abort()
            else:
                stream.stop()
        except BaseException:
            stream.abort()
            raise
        finally:
            stream.close()
            self._stream = None
            if self.underflows:
                logging.warning("Audioausgabe: %d Pufferunterläufe", self.underflows)

    def _write(self, block):
        if self._stream.write(block):
            self.underflows += 1

    def write_silence(self):
        self._write(self._silence)

    def play(self, audio, sr, text, cancel, paused):
        if self._stream is None:
            with self.session(cancel):
                return self.play(audio, sr, text, cancel, paused)
        base_speed = audio.speed if isinstance(audio, PreparedAudio) else 1.0
        source = audio.source if isinstance(audio, PreparedAudio) else self._prepare(audio, sr)
        if cancel.is_set():
            return
        rate, _ = self.controls()
        # Prepared speech already has native tempo. Never block output for DSP
        # at a section boundary; live corrections are computed below in parallel.
        rate = audio.rate if isinstance(audio, PreparedAudio) else rate / base_speed
        rendered = (audio.rendered if isinstance(audio, PreparedAudio) and audio.rendered is not None
                    else source if rate == 1 else self._stretch(source, rate))
        if cancel.is_set():
            return
        pending = None
        ready_offset = None
        last_requested = rate
        stable_frames = 0
        try:
            source_offset = 0
            output_offset = 0
            while source_offset < len(source) and not cancel.is_set():
                while paused.is_set() and not cancel.is_set():
                    self.write_silence()
                if cancel.is_set():
                    break
                requested, _ = self.controls()
                requested /= base_speed
                if requested != last_requested:
                    last_requested, stable_frames = requested, 0
                if pending is not None and pending[1].done():
                    new_rate, future = pending
                    if ready_offset is None:
                        ready_offset = output_offset
                    next_block = rendered[output_offset:output_offset + 960]
                    quiet = len(next_block) and np.max(np.abs(next_block)) < .012
                    # Prefer a breath, but do not make a continuous sentence wait
                    # indefinitely for the requested tempo (350 ms maximum).
                    if new_rate != requested:
                        pending, ready_offset = None, None
                    elif quiet or output_offset - ready_offset >= 16800:
                        new_audio = future.result()
                        pending, ready_offset = None, None
                        old_tail = rendered[output_offset:output_offset + 480].copy()
                        rate, rendered = new_rate, new_audio
                        output_offset = round(source_offset / rate)
                        n = min(len(old_tail), len(rendered) - output_offset)
                        if n > 0:
                            mix = np.linspace(0, 1, n, dtype=np.float32)
                            rendered[output_offset:output_offset+n] = (
                                old_tail[:n] * (1 - mix) + rendered[output_offset:output_offset+n] * mix)
                if pending is None and rate != requested and stable_frames >= 3840:
                    # Keep playing while DSP prepares the new tempo, avoiding an underrun.
                    pending = (requested, self._tempo_worker.submit(self._stretch, source, requested))
                if cancel.is_set():
                    break
                block = rendered[output_offset:output_offset + 960]
                if not len(block):
                    break
                self._write(self._gain(block))
                output_offset += len(block)
                stable_frames += len(block)
                source_offset = min(len(source), round(output_offset * rate))
                if isinstance(audio, PreparedAudio):
                    self.cursor = (audio.marker, audio.start + source_offset / OUTPUT_SAMPLE_RATE)
            if isinstance(audio, PreparedAudio) and not audio.final:
                return
            speed, _ = self.controls()
            pause_frames = int(OUTPUT_SAMPLE_RATE * calculate_adaptive_pause(text) / speed)
            while pause_frames > 0 and not cancel.is_set():
                while paused.is_set() and not cancel.is_set():
                    self.write_silence()
                if cancel.is_set():
                    break
                n = min(960, pause_frames)
                self._write(np.zeros((n, 2), dtype=np.float32))
                pause_frames -= n
        finally:
            if pending:
                pending[1].cancel()
