import asyncio
from contextlib import contextmanager
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from audio_player import AudioPlayer, PreparedAudio
from playback import PlaybackController
from settings import DEFAULTS
from text_cleaner import clean_text, split_sentences
from test_reader import FakeClient, FakePlayer, FakeStream


class TextExperienceTests(unittest.TestCase):
    def test_pdf_wraps_do_not_introduce_sentence_stops(self):
        self.assertEqual(clean_text('Der Text wird aus einem Dokument\nübernommen und ohne neue\nPausen vorgelesen.'),
                         'Der Text wird aus einem Dokument übernommen und ohne neue Pausen vorgelesen.')

    def test_explicit_headings_and_bullets_keep_boundaries(self):
        result = clean_text('# Einkauf\n- Äpfel\n- Birnen\n\nDanach bezahlen.')
        self.assertIn('Einkauf. Äpfel. Birnen.', result)
        self.assertIn('\n\nDanach', result)

    def test_entities_and_comparisons(self):
        self.assertEqual(clean_text('5 &gt; 3 und 2 &lt; 4.'), '5 größer als 3 und 2 kleiner als 4.')
        self.assertNotIn('amp;', clean_text('AT&amp;T'))

    def test_unit_slashes_retain_sentence_ending(self):
        for text, expected in [('12 €/Monat.', '12 Euro pro Monat.'),
                               ('3x/Woche.', '3 mal pro Woche.'),
                               ('2/Woche.', '2 pro Woche.')]:
            self.assertEqual(clean_text(text), expected)

    def test_ordinal_date_and_initial_stay_together(self):
        chunks = split_sentences('Wir treffen J. Müller am 3. Mai. Danach gehen wir nach Hause.', 7)
        self.assertTrue(any('3. Mai.' in p for p in chunks), chunks)
        self.assertTrue(any('J. Müller' in p for p in chunks), chunks)

    def test_negation_and_paragraphs_survive(self):
        result = clean_text('Nicht erlaubt, außer bei Bedarf.\r\n\r\nKeinesfalls ohne Zustimmung.')
        self.assertEqual(result, 'Nicht erlaubt, außer bei Bedarf.\n\nKeinesfalls ohne Zustimmung.')


class AudioExperienceTests(unittest.TestCase):
    def test_soft_ceiling_is_transparent_below_knee_and_bounded(self):
        player = AudioPlayer()
        try:
            low = np.array([-.5, 0, .5], dtype='float32')
            np.testing.assert_array_equal(player._gain(low)[:, 0], low)
            high = np.linspace(-1.5, 1.5, 3001, dtype='float32')
            result = player._gain(high)[:, 0]
            self.assertLessEqual(float(np.max(abs(result))), .981)
            self.assertTrue(np.all(np.diff(result) >= 0))
        finally:
            player.close()

    def test_invalid_audio_and_controls_fail_explicitly(self):
        player = AudioPlayer()
        try:
            for data in (np.array([]), np.array([np.nan]), np.zeros((2, 2, 2))):
                with self.assertRaises(ValueError):
                    player.prepare(data, 24000, 1)
            with self.assertRaises(ValueError):
                player.set_controls(float('nan'), 1)
        finally:
            player.close()

    def test_prepared_tempo_is_used_at_section_start(self):
        stream = FakeStream()
        player = AudioPlayer(lambda **kw: stream)
        player.set_controls(2, 1)
        try:
            audio = PreparedAudio(np.full(9600, .1, dtype='float32'), 1,
                                  np.full(4800, .2, dtype='float32'), 2)
            with patch.object(player, '_stretch', side_effect=AssertionError('blocking DSP')):
                player.play(audio, 48000, '', threading.Event(), threading.Event())
            self.assertAlmostEqual(float(stream.blocks[0][0, 0]), .2)
            self.assertEqual(sum(len(b) for b in stream.blocks if np.max(b)), 4800)
        finally:
            player.close()

    def test_tempo_change_prefers_upcoming_breath(self):
        stream = FakeStream()
        player = AudioPlayer(lambda **kw: stream)
        source = np.full(48000, .1, dtype='float32')
        source[14400:16320] = 0
        def during_write(n):
            if n == 2:
                player.set_controls(2, 1)
            time.sleep(.003)
        stream.callback = during_write
        try:
            # The marker makes the time of the switch visible, independently of DSP quality.
            with patch.object(player, '_stretch', side_effect=lambda a, r: np.full(round(len(a)/r), .2, dtype='float32')):
                player.play(PreparedAudio(source, 1), 48000, '', threading.Event(), threading.Event())
            changed = next(i for i, b in enumerate(stream.blocks) if np.max(b) > .15)
            self.assertEqual(changed, 15)
        finally:
            player.close()

    def test_preparation_corrects_tempo_off_the_output_thread(self):
        player = AudioPlayer()
        player.set_controls(1.5, 1)
        player.set_profile('bypass')
        try:
            with patch.object(player, '_stretch', return_value=np.ones(100, dtype='float32')) as stretch:
                audio = player.prepare(np.ones(2400, dtype='float32') * .1, 24000, 1)
            stretch.assert_called_once()
            self.assertEqual(audio.rate, 1.5)
            self.assertEqual(len(audio.rendered), 100)
        finally:
            player.close()


class BufferExperienceTests(unittest.TestCase):
    def test_sufficient_first_audio_starts_without_second_request(self):
        player, client, release = FakePlayer(), FakeClient(), threading.Event()
        async def synthesize(text, **kwargs):
            if text.startswith('Zweiter'):
                while not release.is_set():
                    await asyncio.sleep(.01)
            return np.zeros(24000 * 12, dtype='float32'), 24000
        client.synthesize = synthesize
        controller = PlaybackController(lambda *a: None, DEFAULTS, client, player)
        try:
            job = controller.start('Erster.\n\nZweiter.', DEFAULTS)
            self.assertTrue(player.entered.wait(2))
            release.set()
            self.assertTrue(job.done.wait(3))
        finally:
            release.set()
            controller.close()

    def test_many_short_sections_still_have_bounded_prefetch(self):
        client, player = FakeClient(), FakePlayer()
        controller = PlaybackController(lambda *a: None, DEFAULTS, client, player)
        try:
            job = controller.start('Blockiert.\n\n' + 'Weiter.\n\n' * 50, DEFAULTS)
            self.assertTrue(player.entered.wait(2))
            time.sleep(.15)
            self.assertLessEqual(job.audio.qsize(), 4)
            self.assertLessEqual(client.calls, 5)
            controller.stop()
            self.assertTrue(job.done.wait(2))
        finally:
            controller.close()

    def test_completion_follows_device_drain(self):
        player, events = FakePlayer(), []
        @contextmanager
        def session(cancel):
            yield
            events.append('drained')
        player.session = session
        controller = PlaybackController(lambda j, k, p: events.append(k), DEFAULTS, FakeClient(), player)
        try:
            job = controller.start('Ein Satz.', DEFAULTS)
            self.assertTrue(job.done.wait(3))
            self.assertLess(events.index('drained'), events.index('done'))
        finally:
            controller.close()

    def test_starvation_keeps_device_alive_and_reports_state_once(self):
        events, release, silence = [], threading.Event(), threading.Event()
        client, player = FakeClient(), FakePlayer()
        async def synthesize(text, **kwargs):
            if text.startswith('Zweiter'):
                while not release.is_set():
                    await asyncio.sleep(.01)
            return np.zeros(24000 * 12, dtype='float32'), 24000
        def write_silence():
            silence.set()
            time.sleep(.01)
        client.synthesize = synthesize
        player.write_silence = write_silence
        controller = PlaybackController(lambda j, k, p: events.append(k), DEFAULTS, client, player)
        try:
            job = controller.start('Erster.\n\nZweiter.', DEFAULTS)
            self.assertTrue(silence.wait(2))
            time.sleep(.05)
            release.set()
            self.assertTrue(job.done.wait(3))
            self.assertEqual(events.count('buffering'), 1)
            self.assertEqual(events.count('progress'), 2)
        finally:
            release.set()
            controller.close()
