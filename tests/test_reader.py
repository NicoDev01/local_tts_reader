import asyncio
import threading
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

from audio_player import AudioPlayer, calculate_adaptive_pause
from playback import PlaybackController
from settings import validate, DEFAULTS
from text_cleaner import clean_text, split_sentences
from windows_runtime import SingleInstance
import clipboard_capture as clipboard


class TextTests(unittest.TestCase):
    def test_grouped_decimal_keeps_value(self):
        self.assertIn('1000,5', clean_text('1.000,5 Euro'))
        self.assertIn('1234567,89', clean_text('1.234.567,89 Euro'))

    def test_dates_and_times(self):
        self.assertEqual(split_sentences('Termin am 10.09.2026 um 10:30 Uhr.'),
                         ['Termin am 10.09.2026 um 10:30 Uhr.'])

    def test_breath_boundaries(self):
        self.assertEqual(split_sentences('Priorität: Text (kurzer Einschub) folgt.'),
                         ['Priorität: Text (kurzer Einschub) folgt.'])
        self.assertEqual(split_sentences('Er sagt: „Guten Morgen“ und geht.'),
                         ['Er sagt: "Guten Morgen" und geht.'])
        self.assertLess(calculate_adaptive_pause('Text,'), .2)

    def test_hard_word_limit_without_punctuation(self):
        chunks = split_sentences(' '.join(['Wort'] * 101))
        self.assertEqual(sum(len(c.split()) for c in chunks), 101)
        self.assertTrue(all(len(c.split()) <= 80 for c in chunks))

    def test_bad_settings_and_migration(self):
        self.assertEqual(validate({'rate': '+25%'})['speed'], 1.25)
        self.assertEqual(validate({'speed': float('nan')})['speed'], DEFAULTS['speed'])
        self.assertEqual(validate({'volume': -4})['volume'], 0)
        self.assertEqual(validate({'voice': 'invalid'})['voice'], DEFAULTS['voice'])


class FakeStream:
    def __init__(self, callback=None, **kwargs):
        self.blocks = []
        self.callback = callback
        self.closed = False
        self.aborted = False
        self.primed = False

    def start(self): pass
    def stop(self): pass
    def write(self, block):
        if not self.primed and len(block) == 4800 and not np.any(block):
            self.primed = True
            return False
        self.blocks.append(block.copy())
        if self.callback:
            self.callback(len(self.blocks))
    def abort(self): self.aborted = True
    def close(self): self.closed = True


class AudioTests(unittest.TestCase):
    def render(self, speed=1, callback=None):
        stream = FakeStream(callback)
        player = AudioPlayer(lambda **kw: stream)
        player.set_profile('bypass')
        player.set_controls(speed, 1)
        return player, stream

    @staticmethod
    def tone():
        return (.1 * np.sin(np.arange(24000 * 2) * 2 * np.pi * 220 / 24000)).astype('float32')

    def test_tempo_duration_and_pitch(self):
        p, stream = self.render(1.5)
        p.play(self.tone(), 24000, 'Text.', threading.Event(), threading.Event())
        result = np.concatenate(stream.blocks)[:, 0]
        self.assertAlmostEqual(len(result) / 48000, 2.2 / 1.5, delta=.03)
        section = result[4800:48000]
        frequency = np.argmax(abs(np.fft.rfft(section))) * 48000 / len(section)
        self.assertAlmostEqual(frequency, 220, delta=3)
        self.assertTrue(stream.closed)

    def test_volume_changes_existing_audio(self):
        p, stream = self.render()
        stream.callback = lambda n: p.set_controls(1, 0) if n == 4 else None
        p.play(self.tone(), 24000, 'Text.', threading.Event(), threading.Event())
        self.assertGreater(np.max(abs(stream.blocks[2])), .05)
        self.assertEqual(np.max(abs(stream.blocks[6])), 0)

    def test_tempo_changes_existing_audio(self):
        p, stream = self.render()
        def during_write(n):
            if n == 10:
                p.set_controls(2, 1)
            time.sleep(.02)
        stream.callback = during_write
        p.play(self.tone(), 24000, 'Text.', threading.Event(), threading.Event())
        duration = sum(map(len, stream.blocks)) / 48000
        self.assertGreaterEqual(duration, 1.1)
        self.assertLess(duration, 1.8)
        p.close()

    def test_cancel_closes_stream_and_next_read_works(self):
        cancel = threading.Event()
        p, stream = self.render(callback=lambda n: cancel.set() if n == 3 else None)
        p.play(self.tone(), 24000, 'Text.', cancel, threading.Event())
        self.assertEqual(len(stream.blocks), 3)
        self.assertTrue(stream.aborted and stream.closed)
        other = FakeStream()
        p.stream_factory = lambda **kw: other
        p.play(self.tone(), 24000, 'Text.', threading.Event(), threading.Event())
        self.assertGreater(len(other.blocks), 3)


class FakeClient:
    def __init__(self): self.calls = 0; self.cancelled = False
    async def synthesize(self, text, **kwargs):
        self.calls += 1
        if 'Langsam' in text:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return np.zeros(240, dtype='float32'), 24000
    async def close(self): pass


class FakePlayer:
    def __init__(self): self.entered = threading.Event(); self.played = []
    def set_controls(self, *args): pass
    def set_profile(self, *args): pass
    def play(self, audio, sr, text, cancel, paused):
        self.played.append(text)
        self.entered.set()
        if 'Blockiert' in text:
            cancel.wait(3)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.client, self.player = FakeClient(), FakePlayer()
        self.events = []
        self.controller = PlaybackController(lambda *e: self.events.append(e), DEFAULTS,
                                             client=self.client, player=self.player)
    def tearDown(self): self.controller.close()

    def test_bounded_prefetch_and_stop(self):
        job = self.controller.start('Blockiert. ' + 'Weiter. ' * 100, DEFAULTS)
        self.assertTrue(self.player.entered.wait(2))
        time.sleep(.2)
        self.assertLessEqual(self.client.calls, 3)
        self.assertLessEqual(job.audio.qsize(), 2)
        self.controller.stop()
        self.assertTrue(job.done.wait(2))

    def test_superseded_network_job_is_cancelled(self):
        old = self.controller.start('Langsam.', DEFAULTS)
        deadline = time.monotonic() + 2
        while self.client.calls == 0 and time.monotonic() < deadline:
            time.sleep(.01)
        new = self.controller.start('Neu.', DEFAULTS)
        self.assertTrue(new.done.wait(2))
        self.assertTrue(old.done.wait(2))
        self.assertTrue(self.client.cancelled)
        self.assertEqual(self.player.played, ['Neu.'])


class WindowsTests(unittest.TestCase):
    def test_single_instance_and_activation(self):
        with tempfile.TemporaryDirectory() as directory, patch('windows_runtime.Path') as path:
            path.return_value.resolve.return_value.parent = Path(directory)
            first, second = SingleInstance(), SingleInstance()
        try:
            self.assertTrue(first.primary)
            self.assertFalse(second.primary)
            second.request_show()
            self.assertTrue(first.show_requested())
            self.assertFalse(first.show_requested())
        finally:
            second.close(); first.close()

    def test_failed_copy_never_uses_old_clipboard(self):
        with patch.object(clipboard, 'Snapshot') as snapshot, patch.object(clipboard, 'u32') as u32:
            u32.GetForegroundWindow.return_value = 123
            u32.GetAsyncKeyState.return_value = 0
            u32.GetClipboardSequenceNumber.return_value = 42
            with patch.object(clipboard, '_read_text', return_value=('ALT', 42)) as read:
                self.assertEqual(clipboard.capture_selection(threading.Event()), '')
                read.assert_not_called()
                snapshot.return_value.restore.assert_not_called()

    def test_unsavable_clipboard_is_reported_and_left_alone(self):
        with patch.object(clipboard, 'Snapshot', side_effect=OSError('Format')), \
                patch.object(clipboard, 'u32') as u32:
            u32.GetForegroundWindow.return_value = 123
            u32.GetAsyncKeyState.return_value = 0
            self.assertIsNone(clipboard.capture_selection(threading.Event()))
            u32.keybd_event.assert_not_called()

    def test_formats_windows_derives_are_not_copied(self):
        # A screenshot lists CF_DIB (8) and the derived CF_PALETTE (9); Office content lists
        # CF_ENHMETAFILE (14) and the derived CF_METAFILEPICT (3). Neither may stop the capture.
        for formats in ([8, 9, 2, 17], [14, 3]):
            listed = iter(formats + [0])
            with patch.object(clipboard, '_open'), patch.object(clipboard, 'u32') as u32, \
                    patch.object(clipboard, 'gdi'), patch.object(clipboard, 'k32') as k32, \
                    patch.object(clipboard.ctypes, 'memmove'):
                u32.EnumClipboardFormats.side_effect = lambda previous: next(listed)
                k32.GlobalSize.return_value = 16
                snapshot = clipboard.Snapshot(None)
                copied = [item[0] for item in snapshot.items]
                self.assertEqual(copied, [f for f in formats if f not in (3, 9)])
                snapshot.items.clear()

    def test_newer_clipboard_is_not_overwritten(self):
        snapshot = clipboard.Snapshot.__new__(clipboard.Snapshot)
        snapshot.items, snapshot.hwnd = [], None
        with patch.object(clipboard, '_open'), patch.object(clipboard, 'u32') as u32:
            u32.GetClipboardSequenceNumber.return_value = 3
            snapshot.restore(2)
            u32.EmptyClipboard.assert_not_called()

    def test_delayed_render_uses_sequence_after_reading(self):
        with patch.object(clipboard, 'Snapshot') as snapshot, patch.object(clipboard, 'u32') as u32:
            u32.GetForegroundWindow.return_value = 123
            u32.GetAsyncKeyState.return_value = 0
            u32.GetClipboardSequenceNumber.side_effect = [1, 2]
            with patch.object(clipboard, '_read_text', return_value=('Markierung', 3)):
                self.assertEqual(clipboard.capture_selection(threading.Event()), 'Markierung')
                snapshot.return_value.restore.assert_called_once_with(3)


if __name__ == '__main__':
    unittest.main()
