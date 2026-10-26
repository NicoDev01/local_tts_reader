import asyncio
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from audio_player import AudioPlayer, PreparedAudio, trim_silence
from playback import PlaybackController
from settings import DEFAULTS
from text_cleaner import split_sentences
from test_reader import FakeStream, FakeClient, FakePlayer


class SmoothTests(unittest.TestCase):
    def test_context_and_paragraphs(self):
        self.assertEqual(split_sentences('Erster Satz. Zweiter Satz!'),
                         ['Erster Satz. Zweiter Satz!'])
        self.assertEqual(len(split_sentences('Erster Absatz.\n\nZweiter Absatz.')), 2)
        for limit in (1, 10, 35, 80):
            parts = split_sentences(' '.join(['Wort'] * 201), limit)
            self.assertEqual(sum(len(p.split()) for p in parts), 201)
            self.assertTrue(all(len(p.split()) <= limit for p in parts))

    def test_quiet_consonants_survive_trim(self):
        source = np.concatenate((np.zeros(3000), np.full(1200, .0005),
                                 np.full(2400, .1), np.full(1200, .0005), np.zeros(3000))).astype('float32')
        result = trim_silence(source)
        self.assertEqual(np.count_nonzero(result == np.float32(.0005)), 2400)

    def test_native_speed_skips_time_stretch_at_all_speeds(self):
        for speed in (.7, 1, 1.25, 1.5, 2):
            stream = FakeStream()
            player = AudioPlayer(lambda **kw: stream)
            player.set_controls(speed, 1)
            try:
                with patch('audio_player.pb.time_stretch', side_effect=AssertionError('unnecessary DSP')):
                    player.play(PreparedAudio(np.ones(4800, dtype='float32') * .1, speed),
                                48000, 'Satz.', threading.Event(), threading.Event())
                self.assertTrue(stream.closed)
            finally:
                player.close()

    def test_multiple_sections_use_one_device_stream(self):
        streams = []
        def factory(**kw):
            stream = FakeStream()
            streams.append(stream)
            return stream
        player = AudioPlayer(factory)
        controller = PlaybackController(lambda *a: None, DEFAULTS, FakeClient(), player)
        try:
            job = controller.start('Satz.\n\n' * 5, DEFAULTS)
            self.assertTrue(job.done.wait(5))
            self.assertEqual(len(streams), 1)
            self.assertTrue(streams[0].closed)
        finally:
            controller.close()

    def test_service_receives_native_speed(self):
        client = FakeClient()
        rates = []
        controller = PlaybackController(lambda *a: None, DEFAULTS, client, FakePlayer())
        async def synthesize(text, **kwargs):
            rates.append(kwargs['rate'])
            return np.zeros(240, dtype='float32'), 24000
        client.synthesize = synthesize
        try:
            job = controller.start('Test.', dict(DEFAULTS, speed=2.0))
            self.assertTrue(job.done.wait(3))
            self.assertEqual(rates, ['+100%'])
        finally:
            controller.close()

    def test_start_waits_for_second_section(self):
        client, player = FakeClient(), FakePlayer()
        release = threading.Event()
        async def synthesize(text, **kwargs):
            if 'Zweiter' in text:
                while not release.is_set():
                    await asyncio.sleep(.01)
            return np.zeros(240, dtype='float32'), 24000
        client.synthesize = synthesize
        controller = PlaybackController(lambda *a: None, DEFAULTS, client, player)
        try:
            job = controller.start('Erster.\n\nZweiter.', DEFAULTS)
            self.assertFalse(player.entered.wait(.15))
            release.set()
            self.assertTrue(job.done.wait(3))
            self.assertEqual(len(player.played), 2)
        finally:
            release.set()
            controller.close()

    def test_rapid_tempo_changes_finish_without_zero_dip(self):
        stream = FakeStream()
        player = AudioPlayer(lambda **kw: stream)
        def controls(n):
            if n in (3, 5, 8, 15):
                player.set_controls({3: 1.5, 5: .7, 8: 2, 15: 1.25}[n], 1)
            time.sleep(.003)
        stream.callback = controls
        try:
            # A constant signal exposes the old explicit fade-to-zero on switches.
            source = PreparedAudio(np.full(48000, .1, dtype='float32'), 1)
            with patch.object(player, '_stretch', side_effect=lambda a, r: np.full(round(len(a)/r), .1, dtype='float32')):
                player.play(source, 48000, '', threading.Event(), threading.Event())
            speech = [b for b in stream.blocks if np.max(b) > 0]
            self.assertTrue(all(np.min(b) > .09 for b in speech))
        finally:
            player.close()

    def test_cancel_while_initial_buffer_is_waiting(self):
        client, player = FakeClient(), FakePlayer()
        controller = PlaybackController(lambda *a: None, DEFAULTS, client, player)
        try:
            job = controller.start('Erster.\n\nLangsam.', DEFAULTS)
            deadline = time.monotonic() + 2
            while client.calls < 2 and time.monotonic() < deadline:
                time.sleep(.01)
            controller.stop()
            self.assertTrue(job.done.wait(2))
            self.assertEqual(player.played, [])
        finally:
            controller.close()

    def test_pause_outputs_silence_and_resumes_same_position(self):
        stream, paused = FakeStream(), threading.Event()
        player = AudioPlayer(lambda **kw: stream)
        def change(n):
            if n == 2:
                paused.set()
            if n == 5:
                paused.clear()
        stream.callback = change
        try:
            player.play(PreparedAudio(np.full(9600, .1, dtype='float32'), 1),
                        48000, '', threading.Event(), paused)
            self.assertTrue(all(np.max(b) == 0 for b in stream.blocks[2:5]))
            speech_frames = sum(len(b) for b in stream.blocks if np.max(b) > 0)
            self.assertEqual(speech_frames, 9600)
        finally:
            player.close()

    def test_failure_in_second_request_releases_initial_buffer(self):
        client, player, events = FakeClient(), FakePlayer(), []
        async def synthesize(text, **kwargs):
            if 'Fehler' in text:
                raise RuntimeError('simulated service failure')
            return np.zeros(240, dtype='float32'), 24000
        client.synthesize = synthesize
        controller = PlaybackController(lambda *a: events.append(a[1]), DEFAULTS, client, player)
        try:
            with self.assertLogs(level='ERROR'):
                job = controller.start('Erster.\n\nFehler.', DEFAULTS)
                self.assertTrue(job.done.wait(3))
            self.assertIn('error', events)
            self.assertNotIn('done', events)
        finally:
            controller.close()
