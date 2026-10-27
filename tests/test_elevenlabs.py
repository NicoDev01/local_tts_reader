import asyncio
import base64
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from aiohttp import web

import elevenlabs_tts
from elevenlabs_tts import ElevenLabsClient, ElevenLabsError, Timings
from settings import DEFAULTS, validate
from speech_service import SpeechService

TEXT = "Hallo Welt. Wie geht's?"


def alignment(text, start=0.0, step=.05):
    return dict(characters=list(text),
                character_start_times_seconds=[start + i * step for i in range(len(text))],
                character_end_times_seconds=[start + (i + 1) * step for i in range(len(text))])


def pcm(seconds):
    return (np.full(int(24000 * seconds), 1000, dtype="<i2")).tobytes()


class TimingsTests(unittest.TestCase):
    def test_words_and_sentences_from_character_times(self):
        events = []
        timings = Timings(TEXT, lambda *e: events.append(e))
        timings.add(alignment(TEXT[:8]), 0.0)
        timings.add(alignment(TEXT[8:], 8 * .05), .4)  # times from the request start
        timings.finish()
        words = [(round(s, 2), w) for s, w, kind, _ in events if kind == "word"]
        sentences = [(round(s, 2), w) for s, w, kind, _ in events if kind == "sentence"]
        self.assertEqual(words, [(0.0, "Hallo"), (.3, "Welt."), (.6, "Wie"), (.8, "geht's?")])
        self.assertEqual(sentences, [(0.0, TEXT), (.6, "Wie geht's?")])

    def test_chunk_relative_times_are_shifted(self):
        events = []
        timings = Timings(TEXT, lambda *e: events.append(e))
        timings.add(alignment(TEXT[:12]), 0.0)
        timings.add(alignment(TEXT[12:]), .6)  # this chunk starts again at 0
        timings.finish()
        self.assertEqual(round(events[-1][0], 2), .8)


class FakeService:
    """Local stand-in for the ElevenLabs API."""

    def __init__(self, status=200, error=None, account=None):
        self.status, self.error, self.requests = status, error, []
        self.account = account or dict(tier="pro", status="active", character_count=1000,
                                       character_limit=600000)

    async def __aenter__(self):
        app = web.Application()
        app.router.add_post("/v1/text-to-speech/{voice}/stream/with-timestamps", self.speak)
        app.router.add_get("/v1/user/subscription", self.subscription)
        app.router.add_get("/v2/voices", self.voices)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *exc):
        await self.runner.cleanup()

    async def subscription(self, request):
        return web.json_response(self.account)

    async def voices(self, request):
        return web.json_response(dict(voices=[
            dict(voice_id="en1", name="Adam - Deep", labels={}, verified_languages=[]),
            dict(voice_id="en2", name="Bill | Wise", labels={"language": "en"},
                 verified_languages=[{"language": "de"}]),
            dict(voice_id="de1", name="Lena - Warm", labels={"language": "de"})]))

    async def speak(self, request):
        self.requests.append((request.match_info["voice"], dict(request.query), dict(request.headers),
                              await request.json()))
        if self.status != 200:
            return web.json_response({"detail": self.error}, status=self.status)
        response = web.StreamResponse()
        await response.prepare(request)
        audio = pcm(.5)
        for i, part in enumerate((TEXT[:12], TEXT[12:])):
            chunk = dict(audio_base64=base64.b64encode(audio[i * 12001:(i + 1) * 12001]).decode(),
                         alignment=alignment(part, i * .6))
            await response.write((json.dumps(chunk) + "\n").encode())
        await response.write_eof()
        return response


def run(coroutine):
    return asyncio.run(coroutine)


class ClientTests(unittest.TestCase):
    def collect(self, service, **kwargs):
        async def go():
            async with service:
                client = ElevenLabsClient(lambda: "test-key", service.base)
                try:
                    events, pieces = [], []
                    async for piece, sr in client.synthesize_stream(
                            TEXT, "de1", kwargs.get("model", "eleven_flash_v2_5"), kwargs.get("speed", 1.5),
                            lambda *e: events.append(e), "Davor.", "Danach."):
                        pieces.append(piece)
                    return pieces, events, client.remaining()
                finally:
                    await client.close()
        return run(go())

    def test_streams_pcm_with_timings_and_clamped_speed(self):
        service = FakeService()
        pieces, events, remaining = self.collect(service)
        audio = np.concatenate(pieces)
        self.assertEqual(len(audio), 12000, "odd byte between chunks must be carried over")
        self.assertAlmostEqual(float(audio[0]), 1000 / 32768, places=5)
        voice, query, headers, body = service.requests[0]
        self.assertEqual((voice, query["output_format"], headers["xi-api-key"]), ("de1", "pcm_24000", "test-key"))
        self.assertEqual(body["voice_settings"], {"speed": 1.2})
        self.assertEqual((body["language_code"], body["previous_text"], body["next_text"]), ("de", "Davor.", "Danach."))
        self.assertIn((.6, "Wie geht's?", "sentence", 0.0), [(round(e[0], 2),) + e[1:] for e in events])
        self.assertEqual(remaining, 600000 - 1000 - len(TEXT) // 2)

    def test_v3_gets_neither_speed_nor_context_and_no_audio_tags(self):
        service = FakeService()
        _, _, remaining = self.collect(service, model="eleven_v3")
        body = service.requests[0][3]
        self.assertNotIn("voice_settings", body, "v3 ignores the speed setting")
        self.assertNotIn("previous_text", body, "v3 answers previous_text/next_text with 400")
        self.assertNotIn("next_text", body)
        self.assertEqual(body["language_code"], "de")
        self.assertEqual(remaining, 600000 - 1000 - len(TEXT), "v3 costs full credits")

    def test_v3_reads_square_brackets_instead_of_acting_them(self):
        async def go():
            async with FakeService() as service:
                client = ElevenLabsClient(lambda: "k", service.base)
                try:
                    async for _ in client.synthesize_stream("Siehe [1] und [lacht].", "de1", "eleven_v3"):
                        pass
                finally:
                    await client.close()
                return service.requests[0][3]["text"]
        self.assertEqual(run(go()), "Siehe (1) und (lacht).")

    def test_multilingual_v2_gets_no_language_code(self):
        service = FakeService()
        self.collect(service, model="eleven_multilingual_v2")
        self.assertNotIn("language_code", service.requests[0][3])

    def test_errors_tell_whether_to_give_up(self):
        with self.assertRaises(ElevenLabsError) as caught:
            self.collect(FakeService(401, {"status": "quota_exceeded", "message": "x"}))
        self.assertTrue(caught.exception.permanent)
        with self.assertRaises(ElevenLabsError) as caught:
            self.collect(FakeService(429, {"status": "too_many_concurrent_requests"}))
        self.assertFalse(caught.exception.permanent)

    def test_ended_plan_and_low_credits_stop_before_speaking(self):
        for account in (dict(tier="free", status="free", character_count=0, character_limit=10000),
                        dict(tier="pro", status="active", character_count=599000, character_limit=600000)):
            service = FakeService(account=account)
            with self.assertRaises(ElevenLabsError) as caught:
                self.collect(service)
            self.assertTrue(caught.exception.permanent)
            self.assertEqual(service.requests, [], "no paid request once the plan cannot cover it")

    def test_catalog_lists_german_voices_first(self):
        async def go():
            async with FakeService() as service:
                client = ElevenLabsClient(lambda: "k", service.base)
                try:
                    return await client.catalog()
                finally:
                    await client.close()
        catalog = run(go())
        self.assertEqual(catalog["voices"], [("de1", "Lena"), ("en2", "Bill"), ("en1", "Adam")])
        self.assertEqual(catalog["account"]["tier"], "pro")


class CounterTests(unittest.TestCase):
    def test_delayed_counter_keeps_own_requests_pending(self):
        client = ElevenLabsClient(lambda: "k")
        counts = iter([1000, 1000, 1300])

        async def get(path):
            return dict(tier="pro", status="active", character_count=next(counts), character_limit=600000)
        client._get = get
        run(client.account(refresh=True))
        client._sent = 500
        run(client.account(refresh=True))  # service has not counted them yet
        self.assertEqual(client.remaining(), 600000 - 1000 - 500)
        run(client.account(refresh=True))  # 300 of them counted now
        self.assertEqual(client.remaining(), 600000 - 1300 - 200)


class FakeEdge:
    def __init__(self):
        self.texts = []
    async def prewarm(self): pass
    async def synthesize_stream(self, text, **kwargs):
        self.texts.append((text, kwargs["rate"]))
        yield np.zeros(10, np.float32), 24000
    async def close(self): pass


class FakeEleven:
    def __init__(self, error=None, after_audio=False):
        self.error, self.after_audio, self.calls = error, after_audio, 0
    async def prewarm(self): pass
    async def synthesize_stream(self, *args):
        self.calls += 1
        if self.after_audio:
            yield np.ones(10, np.float32), 24000
        if self.error:
            raise self.error
        yield np.ones(10, np.float32), 24000
    async def close(self): pass


class ServiceTests(unittest.TestCase):
    config = dict(DEFAULTS, engine="elevenlabs", eleven_voice="de1", speed=1.5, eleven_model="eleven_flash_v2_5",
                  eleven_until=(dt.date.today() + dt.timedelta(days=5)).isoformat())
    v3 = dict(config, eleven_model="eleven_v3")

    def read(self, service):
        async def go():
            route = service.route(self.config)
            return route, [p async for p, _ in service.synthesize_stream("Clipboard.", route, self.config)]
        return run(go())

    def test_route_falls_back_and_says_why(self):
        reasons = []
        service = SpeechService(on_disable=reasons.append, edge=FakeEdge(), eleven=FakeEleven(), key=lambda: "k")
        route = service.route(self.config)
        self.assertEqual((route.engine, route.speed), ("elevenlabs", 1.2))
        self.assertEqual(service.route(self.config, today=dt.date.today() + dt.timedelta(days=6)).engine, "edge")
        self.assertIn("endete am", reasons[0])
        self.assertEqual(service.route(self.config).engine, "edge", "stays off until chosen again")
        service.enable()
        self.assertEqual(service.route(self.config).engine, "elevenlabs")
        no_key = SpeechService(on_disable=reasons.append, edge=FakeEdge(), eleven=FakeEleven(), key=lambda: None)
        self.assertEqual(no_key.route(self.config).engine, "edge")
        self.assertIn("Schlüssel", reasons[-1])

    def test_permanent_error_reads_on_with_edge(self):
        reasons, edge = [], FakeEdge()
        service = SpeechService(on_disable=reasons.append, edge=edge, key=lambda: "k",
                                eleven=FakeEleven(ElevenLabsError("Kontingent aufgebraucht.", True)))
        route, pieces = self.read(service)
        self.assertEqual(len(pieces), 1)
        self.assertEqual(edge.texts, [("Clip Board.", "+20%")], "Edge gets its spelling and the same tempo")
        self.assertEqual(reasons, ["Kontingent aufgebraucht."])

    def test_v3_keeps_its_own_pace_and_edge_stands_in_at_the_set_tempo(self):
        edge = FakeEdge()
        service = SpeechService(edge=edge, eleven=FakeEleven(ElevenLabsError("busy")), key=lambda: "k")
        route = service.route(self.v3)
        self.assertEqual((route.engine, route.speed, route.fixed), ("elevenlabs", 1.0, True))

        async def go():
            return [p async for p, _ in service.synthesize_stream("Satz.", route, self.v3)]
        run(go())
        self.assertEqual(edge.texts, [("Satz.", "+50%")], "Edge is not stretched either, so it speaks 1.5 itself")

    def test_passing_error_only_borrows_edge_for_this_section(self):
        reasons, edge = [], FakeEdge()
        service = SpeechService(on_disable=reasons.append, edge=edge, key=lambda: "k",
                                eleven=FakeEleven(ElevenLabsError("busy")))
        self.read(service)
        self.assertEqual((len(edge.texts), reasons, service.disabled), (1, [], None))

    def test_failure_after_audio_is_not_repeated_by_edge(self):
        edge = FakeEdge()
        service = SpeechService(edge=edge, key=lambda: "k",
                                eleven=FakeEleven(ConnectionError("weg"), after_audio=True))
        with self.assertRaises(ConnectionError):
            self.read(service)
        self.assertEqual(edge.texts, [])


class PlaybackRouteTests(unittest.TestCase):
    def test_sections_play_at_the_generated_tempo_with_their_neighbours(self):
        from playback import PlaybackController
        from tests.test_streaming import RecordingPlayer

        class Eleven(FakeEleven):
            async def synthesize_stream(self, text, voice, model, speed, on_boundary, previous, following):
                self.seen = (speed, previous, following)
                yield np.ones(48000, np.float32), 24000

        eleven, player = Eleven(), RecordingPlayer()
        service = SpeechService(edge=FakeEdge(), eleven=eleven, key=lambda: "k")
        controller = PlaybackController(lambda *a: None, ServiceTests.config, service, player)
        try:
            units = ["Erster Satz.", "Zweiter Satz.", "Dritter Satz."]
            job = controller.start(None, ServiceTests.config, units=units, first=1)
            self.assertTrue(job.done.wait(5))
            self.assertEqual(eleven.seen, (1.2, "Erster Satz.", None))
            self.assertEqual(player.pieces[0].speed, 1.2, "the player stretches only from 1.2 to 1.5")
        finally:
            controller.close()
            player.close()

    def test_v3_is_never_stretched_and_a_new_tempo_costs_no_regeneration(self):
        from playback import PlaybackController
        from tests.test_streaming import RecordingPlayer

        class Eleven(FakeEleven):
            async def synthesize_stream(self, *args):
                yield np.ones(48000, np.float32), 24000

        player = RecordingPlayer()
        player.set_controls(1.5, 1.0)
        service = SpeechService(edge=FakeEdge(), eleven=Eleven(), key=lambda: "k")
        controller = PlaybackController(lambda *a: None, ServiceTests.v3, service, player)
        try:
            job = controller.start(None, ServiceTests.v3, units=["Erster Satz.", "Zweiter Satz."])
            self.assertTrue(job.done.wait(5))
            piece = player.pieces[0]
            self.assertEqual((piece.fixed, piece.rate, piece.rendered), (True, 1.0, None))
            job.done.clear()  # pretend it is still reading
            self.assertIsNone(controller.respeed_plan(1.8))
        finally:
            controller.close()
            player.close()


class SettingsTests(unittest.TestCase):
    def test_elevenlabs_needs_an_end_date(self):
        self.assertEqual(validate(dict(engine="elevenlabs"))["engine"], "edge")
        self.assertEqual(validate(dict(engine="elevenlabs", eleven_until="kaputt"))["engine"], "edge")
        cfg = validate(dict(engine="elevenlabs", eleven_until="2027-01-25", eleven_model="gibt-es-nicht"))
        self.assertEqual((cfg["engine"], cfg["eleven_model"]), ("elevenlabs", DEFAULTS["eleven_model"]))

    def test_key_from_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("# Schlüssel\nELEVENLABS_API_KEY='sk_test'\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True), patch.object(elevenlabs_tts, "ENV_FILE", env), \
                    patch.object(elevenlabs_tts.winreg, "OpenKey", side_effect=OSError):
                self.assertEqual(elevenlabs_tts.api_key(), "sk_test")
                env.unlink()
                self.assertIsNone(elevenlabs_tts.api_key())


if __name__ == "__main__":
    unittest.main()
