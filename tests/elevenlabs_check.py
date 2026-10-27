"""Live check with the real ElevenLabs key: first-audio time, word timings and samples per model.

Costs credits (about 2 × 330 characters per model). Samples land in tests/artifacts/elevenlabs/.
    .venv\\Scripts\\python tests\\elevenlabs_check.py [voice_id]
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf

from elevenlabs_tts import MODELS, ElevenLabsClient, api_key

TEXT = ("Der Vorleser liest markierten Text vor. Am 3. November um 14:30 Uhr startet das Update 2.4 "
        "mit neuen Features: Das Plugin speichert Screenshots im Clipboard, und der Download-Link "
        "steht im Dashboard. Dr. Müller sagt: „Die Ergebnisse sind z. B. für Teams interessant.“")
OUT = Path(__file__).resolve().parent / "artifacts" / "elevenlabs"


async def main():
    if not api_key():
        sys.exit("Kein ELEVENLABS_API_KEY gefunden.")
    OUT.mkdir(parents=True, exist_ok=True)
    client = ElevenLabsClient()
    try:
        catalog = await client.catalog()
        account = catalog["account"] or {}
        print("Konto:", account.get("tier"), account.get("status"),
              f"{account.get('character_count')}/{account.get('character_limit')} Credits")
        voice = sys.argv[1] if len(sys.argv) > 1 else catalog["voices"][0][0]
        print("Stimme:", dict(catalog["voices"]).get(voice, voice))
        for model in MODELS:
            for attempt in (1, 2):  # the second request runs on a warm connection
                events, pieces, started, first = [], [], time.monotonic(), None
                async for piece, sr in client.synthesize_stream(TEXT, voice, model, 1.0,
                                                                lambda *e: events.append(e)):
                    first = first or time.monotonic() - started
                    pieces.append(piece)
                audio = np.concatenate(pieces)
                words = [e for e in events if e[2] == "word"]
                level = 20 * np.log10(np.sqrt(np.mean(audio[np.abs(audio) > .01] ** 2)) + 1e-9)
                print(f"{model:24} Versuch {attempt}: erstes Audio {first:.2f} s, gesamt "
                      f"{time.monotonic() - started:.2f} s, {len(audio) / sr:.1f} s Audio, {len(words)} Wörter, "
                      f"Pegel {level:.1f} dBFS, letztes Wort {words[-1][1]!r} bei {words[-1][0]:.2f} s")
            sf.write(str(OUT / f"{model}.wav"), audio, sr)
        await client.account(refresh=True)
        print("Danach:", client.remaining(), "Credits frei")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
