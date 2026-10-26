"""Online Microsoft speech synthesis, streamed as it arrives, with bounded requests and fallback."""
import io
import json
import re
from html import unescape
from xml.sax.saxutils import escape
import logging
import asyncio
from typing import AsyncIterator, Tuple, Optional
import aiohttp
import numpy as np
import soundfile as sf
import edge_tts
from edge_tts.constants import WSS_URL, WSS_HEADERS, SEC_MS_GEC_VERSION
from edge_tts.drm import DRM
from edge_tts.data_classes import TTSConfig
from edge_tts.communicate import connect_id, date_to_string, mkssml, ssml_headers_plus_data, _SSL_CTX

WARM_SECONDS = 20.0  # a pre-opened connection older than this is not trusted (25 s worked, 2026-10-26)


class ProgressiveMp3:
    """Decode a growing MP3 buffer.

    Decoding a byte prefix yields exactly the prefix of the full decode (checked
    with libsndfile/mpg123), so already emitted samples never change. The last
    frames are held back until more bytes arrive or the stream ends.
    """
    HOLD = 1152
    STEP = 3072

    def __init__(self):
        self.data = bytearray()
        self.emitted = 0
        self.decoded_at = 0
        self.sr = None

    def feed(self, chunk):
        self.data.extend(chunk)
        if len(self.data) - self.decoded_at < self.STEP:
            return None
        return self._decode(final=False)

    def finish(self):
        return self._decode(final=True)

    def _decode(self, final):
        self.decoded_at = len(self.data)
        try:
            audio, self.sr = sf.read(io.BytesIO(bytes(self.data)), dtype="float32")
        except (RuntimeError, sf.LibsndfileError):
            if final:
                raise
            return None
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        end = len(audio) if final else len(audio) - self.HOLD
        if end <= self.emitted:
            return None
        piece = audio[self.emitted:end]
        self.emitted = end
        return piece


def _voice_name(voice):
    if voice.startswith("Microsoft Server Speech"):
        return voice
    parts = voice.split("-")
    if len(parts) >= 3:
        return f"Microsoft Server Speech Text to Speech Voice ({parts[0]}-{parts[1]}, {parts[2]})"
    return voice


def _report_boundaries(message, on_boundary):
    """Pass each sentence and word start (seconds into this request's audio) with its text."""
    kinds = {"SentenceBoundary": "sentence", "WordBoundary": "word"}
    try:
        body = json.loads(message.split("\r\n\r\n", 1)[1])
        for item in body.get("Metadata", ()):
            if item.get("Type") in kinds:
                data = item["Data"]
                on_boundary(data["Offset"] / 1e7, unescape(data["text"]["Text"]), kinds[item["Type"]])
    except (IndexError, KeyError, TypeError, ValueError):
        logging.debug("Satzgrenze nicht lesbar", exc_info=True)


def _prepare_text(text):
    # Enhance colon prosody: when a colon introduces a clause, list or direct speech,
    # a newline instructs Edge TTS's neural model to insert an emphasized, natural rhetorical pause.
    # Use horizontal whitespace to avoid flattening multi-line paragraph structure.
    return re.sub(r':[ \t]+(?=[^\s])', ':\n', text.strip())


class HighFidelityTTSClient:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self._warm: Optional[asyncio.Task] = None
        self._warm_at = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(sock_connect=6.0, sock_read=16.0)
                connector = aiohttp.TCPConnector(keepalive_timeout=15.0)
                self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
            return self._session

    async def _reset_session(self):
        await self._discard_warm()
        async with self._lock:
            if self._session:
                try:
                    if not self._session.closed:
                        await self._session.close()
                except Exception:
                    pass
                self._session = None

    async def close(self):
        await self._reset_session()

    async def _connect(self):
        session = await self._get_session()
        ws_url = (
            f"{WSS_URL}&ConnectionId={connect_id()}"
            f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
        )
        return await session.ws_connect(
            ws_url,
            headers=DRM.headers_with_muid(WSS_HEADERS),
            ssl=_SSL_CTX,
            compress=15,
            receive_timeout=14.0,
            heartbeat=15.0
        )

    async def prewarm(self):
        """Open the next connection while the selection is still being copied."""
        if self._warm and not self._warm.done():
            return
        await self._discard_warm()
        self._warm = asyncio.ensure_future(self._connect())
        self._warm_at = asyncio.get_running_loop().time()

    async def _discard_warm(self):
        task, self._warm = self._warm, None
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            ws = await task
            await ws.close()
        except BaseException:
            pass

    async def _take_ws(self):
        task = self._warm
        fresh = task is not None and asyncio.get_running_loop().time() - self._warm_at < WARM_SECONDS
        if fresh:
            self._warm = None
            try:
                ws = await task
                if not ws.closed:
                    return ws
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        else:
            await self._discard_warm()
        return await self._connect()

    async def _hd_audio(self, text, voice, rate, pitch, volume, on_boundary=None) -> AsyncIterator[bytes]:
        config = TTSConfig(voice=_voice_name(voice), rate=rate, volume=volume, pitch=pitch,
                           boundary="SentenceBoundary")
        ws = await self._take_ws()
        flag = "true" if on_boundary else "false"
        try:
            # Request 96kbps HD audio stream; sentence and word offsets drive the player's text display.
            cmd = (
                f"X-Timestamp:{date_to_string()}\r\n"
                "Content-Type:application/json; charset=utf-8\r\n"
                "Path:speech.config\r\n\r\n"
                '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                f'"sentenceBoundaryEnabled":"{flag}","wordBoundaryEnabled":"{flag}"'
                '},'
                '"outputFormat":"audio-24khz-96kbitrate-mono-mp3"'
                "}}}}\r\n"
            )
            await ws.send_str(cmd)
            ssml = ssml_headers_plus_data(connect_id(), date_to_string(), mkssml(config, escape(text)))
            await ws.send_str(ssml)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) >= 2:
                        hlen = int.from_bytes(msg.data[:2], "big")
                        if hlen > len(msg.data) - 2:
                            raise ValueError("Invalid audio frame")
                        headers = msg.data[2:2 + hlen]
                        if b"Path:audio" in headers.split(b"\r\n"):
                            yield msg.data[2 + hlen:]
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    if "Path:turn.end" in msg.data:
                        return
                    if on_boundary and "Path:audio.metadata" in msg.data:
                        _report_boundaries(msg.data, on_boundary)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
            raise ConnectionError("Incomplete speech response")
        finally:
            await ws.close()

    async def _fallback_audio(self, text, voice, rate, pitch, volume, on_boundary=None) -> AsyncIterator[bytes]:
        # Standard edge-tts Communicate with bounded timeouts
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume,
                                    boundary="SentenceBoundary", connect_timeout=6, receive_timeout=14)
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
            elif chunk["type"] == "SentenceBoundary" and on_boundary:
                on_boundary(chunk["offset"] / 1e7, chunk["text"], "sentence")

    async def synthesize_stream(
        self,
        text: str,
        voice: str = "de-DE-KillianNeural",
        rate: str = "+15%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
        on_boundary=None
    ) -> AsyncIterator[Tuple[np.ndarray, int]]:
        """Yield 24 kHz Float32 mono pieces while the service is still speaking.

        ``on_boundary(seconds, text, kind)`` receives each sentence and word start. The fallback
        is used only if the HD path fails before any audio was yielded; a later
        failure raises, since repeating audio would be worse.
        """
        if not text or not text.strip():
            return
        prep_text = _prepare_text(text)
        decoder = ProgressiveMp3()
        try:
            async for chunk in self._hd_audio(prep_text, voice, rate, pitch, volume, on_boundary):
                piece = decoder.feed(chunk)
                if piece is not None:
                    yield piece, decoder.sr
            if not decoder.data:
                raise ConnectionError("Incomplete speech response")
            # Keep a connection ready for the next section or a sentence jump.
            await self.prewarm()
            piece = decoder.finish()
            if piece is not None:
                yield piece, decoder.sr
            return
        except asyncio.CancelledError:
            raise
        except aiohttp.ClientResponseError as cre:
            if decoder.emitted:
                raise
            if cre.status == 403:
                DRM.handle_client_response_error(cre)
            logging.warning("HD-Sprachdienst HTTP %s; Fallback wird verwendet", cre.status)
            await self._reset_session()
        except Exception as e:
            if decoder.emitted:
                raise
            logging.warning("HD-Sprachdienst nicht verfügbar (%s); Fallback wird verwendet", type(e).__name__)
            await self._reset_session()

        decoder = ProgressiveMp3()
        try:
            async for chunk in self._fallback_audio(prep_text, voice, rate, pitch, volume, on_boundary):
                piece = decoder.feed(chunk)
                if piece is not None:
                    yield piece, decoder.sr
            if not decoder.data:
                raise ConnectionError("Fallback lieferte kein Audio")
            piece = decoder.finish()
            if piece is not None:
                yield piece, decoder.sr
        except asyncio.CancelledError:
            raise
        except Exception as fe:
            logging.warning("Fallback-Sprachdienst nicht verfügbar: %s", type(fe).__name__)
            raise

    async def synthesize(
        self,
        text: str,
        voice: str = "de-DE-KillianNeural",
        rate: str = "+15%",
        pitch: str = "+0Hz",
        volume: str = "+0%"
    ) -> Tuple[Optional[object], Optional[int]]:
        """
        Synthesizes text into 24kHz studio-quality Float32 audio directly in RAM.
        Returns: (audio_array_float32, sample_rate)
        """
        pieces, sr = [], None
        try:
            async for piece, sr in self.synthesize_stream(text, voice, rate, pitch, volume):
                pieces.append(piece)
        except asyncio.CancelledError:
            raise
        except Exception:
            return None, None
        if not pieces:
            return None, None
        return np.concatenate(pieces), sr
