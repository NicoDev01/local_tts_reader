"""Same text in every voice, processed like the app (tempo, level match, sound profile).

.venv\\Scripts\\python.exe -B tests\\voice_samples.py
Writes tests\\artifacts\\voices\\<Stimme>.wav
"""
import asyncio
import sys
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from audio_player import AudioPlayer, OUTPUT_SAMPLE_RATE
from high_fidelity_tts import HighFidelityTTSClient
from playback import voice_gain
from settings import VOICES, load_config

TEXT = ("Kurzer Hinweis: Die Stadtbibliothek öffnet ab dem 3. November bereits um 8:30 Uhr. "
        "Wer Bücher zurückgeben möchte (auch am Wochenende), nutzt den neuen Automaten im Erdgeschoss. "
        "Fragen beantwortet das Team gern vor Ort.")


async def main():
    config = load_config()
    speed = config["speed"]
    player, client = AudioPlayer(), HighFidelityTTSClient()
    player.set_profile(config["sound_profile"])
    player.set_controls(speed, 1.0)
    out = HERE / "artifacts" / "voices"
    out.mkdir(parents=True, exist_ok=True)
    try:
        for voice, name in VOICES.items():
            audio, sr = await client.synthesize(TEXT, voice=voice, rate=f"{round((speed - 1) * 100):+d}%")
            if audio is None:
                print(f"{name}: keine Antwort vom Dienst")
                continue
            prepared = player.prepare(audio, sr, speed, voice_gain(voice))
            path = out / f"{name.split(' (')[0]}{' (' + name.split(' (')[1] if ' (' in name else ''}.wav"
            sf.write(str(path), prepared.source, OUTPUT_SAMPLE_RATE)
            print(f"{name}: {len(prepared.source) / OUTPUT_SAMPLE_RATE:.1f} s")
    finally:
        await client.close()
        player.close()
    print(f"Hörproben: {out} (Tempo {speed:.2f}×, Klang {config['sound_profile']})")


asyncio.run(main())
