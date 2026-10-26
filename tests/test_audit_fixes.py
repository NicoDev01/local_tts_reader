import asyncio
import threading
import time
import unittest
import numpy as np

from audio_player import AudioPlayer, calculate_adaptive_pause, MASTERING_PROFILES
from high_fidelity_tts import HighFidelityTTSClient
from playback import PlaybackController
from settings import DEFAULTS
from text_cleaner import clean_text, split_sentences
from test_reader import FakeClient, FakePlayer


class AuditFixesTests(unittest.TestCase):
    def test_retry_recovers_from_transient_network_timeout(self):
        """A transient timeout on a single part must retry and succeed without aborting playback."""
        client = FakeClient()
        player = FakePlayer()
        events = []
        attempt_count = [0]

        async def flaking_synthesize(text, **kwargs):
            if "Wackelig" in text:
                attempt_count[0] += 1
                if attempt_count[0] == 1:
                    raise TimeoutError("Simulierter WebSocket-Timeout")
            return np.zeros(2400, dtype="float32"), 24000

        client.synthesize = flaking_synthesize
        controller = PlaybackController(lambda j, k, p: events.append(k), DEFAULTS, client, player)
        try:
            job = controller.start("Erster Teil.\n\nWackelig.\n\nLetzter Teil.", DEFAULTS)
            self.assertTrue(job.done.wait(5), "Job did not complete in time")
            self.assertEqual(attempt_count[0], 2, "Part should have retried once and succeeded on attempt 2")
            self.assertIn("done", events, "Reading should finish successfully despite transient timeout")
            self.assertNotIn("error", events, "Transient timeout should not cause an error notification")
            self.assertEqual(len(player.played), 3, "All 3 sections should be played")
        finally:
            controller.close()

    def test_session_cleanup_and_reset(self):
        """HighFidelityTTSClient must reset sessions cleanly on error and close without resource leaks."""
        client = HighFidelityTTSClient()
        loop = asyncio.new_event_loop()
        try:
            async def run_checks():
                session1 = await client._get_session()
                self.assertFalse(session1.closed)
                await client._reset_session()
                self.assertIsNone(client._session)
                self.assertTrue(session1.closed)

                session2 = await client._get_session()
                self.assertFalse(session2.closed)
                await client.close()
                self.assertIsNone(client._session)
                self.assertTrue(session2.closed)

            loop.run_until_complete(run_checks())
        finally:
            loop.close()

    def test_colon_and_dash_preservation(self):
        """Dashes should remain rhetorical Gedankenstriche, and colon line breaks stay paragraph boundaries."""
        # Dashes should not be collapsed into commas
        cleaned = clean_text("Ein kurzer Einschub – wie dieser hier – gehört dazu.")
        self.assertIn(" – wie dieser hier – ", cleaned)

        # Colon followed by newline should preserve paragraph separation
        cleaned_colon = clean_text("Wichtiger Hinweis:\nDies ist die Erklärung.")
        self.assertIn("Wichtiger Hinweis:\n\nDies ist die Erklärung.", cleaned_colon)
        parts = split_sentences(cleaned_colon)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].startswith("Wichtiger Hinweis:"))

    def test_adaptive_pause_structure(self):
        """Pauses after colons and paragraph breaks must be distinctly audible."""
        self.assertGreaterEqual(calculate_adaptive_pause("Titel:\n\n"), 0.40)
        self.assertGreaterEqual(calculate_adaptive_pause("Hinweis:"), 0.30)
        self.assertEqual(calculate_adaptive_pause("Satz."), 0.20)
        self.assertLess(calculate_adaptive_pause("Komma,"), 0.20)
        # Verify hierarchy: Paragraph >= Colon > Sentence > Semicolon > Comma
        p_par = calculate_adaptive_pause("Absatzende.\n\n")
        p_col = calculate_adaptive_pause("Doppelpunkt:")
        p_sen = calculate_adaptive_pause("Satzende.")
        p_sem = calculate_adaptive_pause("Semikolon;")
        p_com = calculate_adaptive_pause("Komma,")
        self.assertTrue(p_par > p_col > p_sen > p_sem > p_com,
                        f"Pause hierarchy violated: {p_par} > {p_col} > {p_sen} > {p_sem} > {p_com}")

    def test_ordinal_header_colon_preservation(self):
        """Numbered headers with colons should retain their colon for prosodic emphasis."""
        cleaned = clean_text("1. Schritt: Vorbereitung des Teigs.")
        self.assertIn("Erster Schritt: Vorbereitung des Teigs.", cleaned)
        cleaned_quartal = clean_text("2. Quartal: Quartalsergebnis.")
        self.assertIn("Zweites Quartal: Quartalsergebnis.", cleaned_quartal)

    def test_client_keepalive_and_timeout_configuration(self):
        """ClientSession must configure keepalive_timeout and adequate socket timeouts for long playbacks."""
        client = HighFidelityTTSClient()
        loop = asyncio.new_event_loop()
        try:
            async def check_session():
                session = await client._get_session()
                self.assertIsNotNone(session.connector)
                self.assertEqual(session.connector._keepalive_timeout, 15.0)
                self.assertGreaterEqual(session.timeout.sock_read, 15.0)
            loop.run_until_complete(check_session())
        finally:
            loop.run_until_complete(client.close())
            loop.close()

    def test_studio_warmth_presence_filter(self):
        """The studio_warmth profile should feature presence filtering for clear speech intelligibility."""
        board = MASTERING_PROFILES["studio_warmth"]
        filter_types = [type(f).__name__ for f in board]
        self.assertIn("HighpassFilter", filter_types)
        self.assertIn("PeakFilter", filter_types)
        self.assertIn("HighShelfFilter", filter_types)
        # Check that 3200Hz peak presence filter is active
        peaks = [f for f in board if type(f).__name__ == "PeakFilter"]
        cutoff_freqs = [f.cutoff_frequency_hz for f in peaks]
        self.assertTrue(any(3000 <= freq <= 3500 for freq in cutoff_freqs),
                        f"Expected presence peak around 3200Hz, got {cutoff_freqs}")
