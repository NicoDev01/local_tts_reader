import asyncio
import io
import threading
import unittest

import numpy as np
import soundfile as sf

from audio_player import AudioPlayer, PreparedAudio
from high_fidelity_tts import ProgressiveMp3
from playback import PlaybackController
from settings import DEFAULTS


def speech_like(seconds=1.5, sr=24000):
    t = np.arange(int(seconds * sr)) / sr
    tone = (.3 * np.sin(2 * np.pi * 220 * t)).astype('float32')
    return np.concatenate([np.zeros(2400, 'float32'), tone, np.zeros(2400, 'float32')])


class ProgressiveMp3Tests(unittest.TestCase):
    def test_pieces_equal_full_decode(self):
        buffer = io.BytesIO()
        sf.write(buffer, speech_like(8), 24000, format='MP3')
        mp3 = buffer.getvalue()
        full, _ = sf.read(io.BytesIO(mp3), dtype='float32')
        decoder, pieces = ProgressiveMp3(), []
        for start in range(0, len(mp3), 700):
            piece = decoder.feed(mp3[start:start + 700])
            if piece is not None:
                pieces.append(piece)
        self.assertGreater(len(pieces), 1, 'audio must be released before the stream ends')
        pieces.append(decoder.finish())
        np.testing.assert_array_equal(np.concatenate(pieces), full)


class SectionStreamTests(unittest.TestCase):
    def test_pieces_join_like_one_block(self):
        player = AudioPlayer()
        try:
            audio = speech_like()
            whole = player.stream_section(1).push(audio, 24000, True).source
            stream, parts = player.stream_section(1), []
            for start in range(0, len(audio), 6000):
                end = start + 6000
                prepared = stream.push(audio[start:end], 24000, end >= len(audio))
                if prepared is not None:
                    self.assertEqual(prepared.final, end >= len(audio))
                    parts.append(prepared.source)
            joined = np.concatenate(parts)
            self.assertLess(abs(len(joined) - len(whole)), 480)
            n = min(len(joined), len(whole)) - 2400
            self.assertLess(np.max(np.abs(joined[:n] - whole[:n])), 1e-3)
        finally:
            player.close()


class VoiceLevelTests(unittest.TestCase):
    def test_every_voice_has_a_level_and_gain_is_applied(self):
        from playback import voice_gain
        from settings import VOICE_GAIN_DB, VOICES
        self.assertEqual(set(VOICE_GAIN_DB), set(VOICES))
        self.assertAlmostEqual(voice_gain('de-AT-IngridNeural'), 10 ** (-3.1 / 20))
        player = AudioPlayer()
        player.set_profile('bypass')
        try:
            audio = speech_like()
            loud = player.stream_section(1).push(audio, 24000, True).source
            quiet = player.stream_section(1, .5).push(audio, 24000, True).source
            self.assertAlmostEqual(np.max(np.abs(quiet)) / np.max(np.abs(loud)), .5, places=2)
        finally:
            player.close()


class StreamingClient:
    def __init__(self, fail_before=0, fail_after=False):
        self.release, self.calls = threading.Event(), 0
        self.fail_before, self.fail_after = fail_before, fail_after
    async def prewarm(self): pass
    async def synthesize_stream(self, text, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_before:
            raise TimeoutError('Simulierter Abbruch')
        audio = speech_like(3)
        yield audio[:36000], 24000
        if self.fail_after:
            raise ConnectionError('Abbruch mitten im Satz')
        while not self.release.is_set():
            await asyncio.sleep(.01)
        yield audio[36000:], 24000
    async def close(self): pass


class RecordingPlayer(AudioPlayer):
    def __init__(self):
        super().__init__()
        self.pieces, self.first = [], threading.Event()
    def session(self, cancel):
        from contextlib import nullcontext
        return nullcontext()
    def play(self, audio, sr, text, cancel, paused):
        self.pieces.append(audio)
        self.first.set()
    def write_silence(self):
        threading.Event().wait(.005)


class StreamingPipelineTests(unittest.TestCase):
    def run_reading(self, client, events=None):
        player = RecordingPlayer()
        controller = PlaybackController(lambda j, k, p: (events if events is not None else []).append(k),
                                        DEFAULTS, client, player)
        return player, controller

    def test_playback_starts_before_section_is_complete(self):
        client = StreamingClient()
        player, controller = self.run_reading(client)
        try:
            job = controller.start('Ein langer Satz.', DEFAULTS)
            self.assertTrue(player.first.wait(2), 'first piece must play while the service still speaks')
            self.assertFalse(job.done.is_set())
            client.release.set()
            self.assertTrue(job.done.wait(3))
            self.assertIsInstance(player.pieces[0], PreparedAudio)
            self.assertFalse(player.pieces[0].final)
            self.assertTrue(player.pieces[-1].final)
        finally:
            client.release.set()
            controller.close()
            player.close()

    def test_failure_before_audio_is_retried(self):
        client, events = StreamingClient(fail_before=1), []
        client.release.set()
        player, controller = self.run_reading(client, events)
        try:
            job = controller.start('Ein Satz.', DEFAULTS)
            self.assertTrue(job.done.wait(5))
            self.assertEqual(client.calls, 2)
            self.assertIn('done', events)
        finally:
            controller.close()
            player.close()

    def test_failure_after_audio_is_reported_not_repeated(self):
        client, events = StreamingClient(fail_after=True), []
        player, controller = self.run_reading(client, events)
        try:
            job = controller.start('Ein Satz.', DEFAULTS)
            self.assertTrue(job.done.wait(5))
            self.assertEqual(client.calls, 1)
            self.assertIn('error', events)
        finally:
            controller.close()
            player.close()


class SentencePositionTests(unittest.TestCase):
    def test_service_sentences_map_to_units_and_cursor(self):
        controller = PlaybackController(lambda *a: None, DEFAULTS, StreamingClient(), RecordingPlayer())
        try:
            units = ['Hinweis: Die Bibliothek öffnet.', 'Wer kommt mit?', 'Danach gibt es Kaffee.\n\n', 'Neu.']
            job = controller.start(None, DEFAULTS, units=units, first=1)
            controller.stop()
            self.assertEqual(job.sections, [(1, 3), (3, 4)])
            controller.current = job
            handle = job.boundary_handler(0)
            for seconds, text in ((.1, 'Wer kommt mit?'), (1.4, 'Danach gibt es'), (1.9, 'Kaffee.')):
                handle(seconds, text)
            self.assertEqual(job.boundaries[0], [(.1, 1), (1.4, 2), (1.9, 2)])
            controller.player.cursor = ((job, 0), 1.0)
            self.assertEqual(controller.position()[0], 1)
            controller.player.cursor = ((job, 0), 2.5)
            unit, since = controller.position()
            self.assertEqual(unit, 2)
            self.assertAlmostEqual(since, 1.1)
        finally:
            controller.close()
            controller.player.close()


if __name__ == '__main__':
    unittest.main()
