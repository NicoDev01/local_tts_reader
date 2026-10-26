"""Same text in every voice, processed like the app (tempo, level match, sound profile).

.venv\\Scripts\\python.exe -B tests\\voice_samples.py
Writes tests\\artifacts\\voices\\<Stimme>.wav and <Stimme> Denglisch.wav (English tech terms)
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
# The free service accepts no SSML language tags, so how a voice handles English terms is
# a property of the voice itself; compare by ear.
DENGLISCH = ("Ich habe den Pull Request gemergt und das Deployment auf Staging getriggert. "
             "Das Feature ist jetzt ready for review, danach läuft der Build mit dem neuen Framework durch.")


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
            for text, suffix in ((TEXT, ""), (DENGLISCH, " Denglisch")):
                audio, sr = await client.synthesize(text, voice=voice, rate=f"{round((speed - 1) * 100):+d}%")
                if audio is None:
                    print(f"{name}{suffix}: keine Antwort vom Dienst")
                    continue
                prepared = player.prepare(audio, sr, speed, voice_gain(voice))
                sf.write(str(out / f"{name}{suffix}.wav"), prepared.source, OUTPUT_SAMPLE_RATE)
                print(f"{name}{suffix}: {len(prepared.source) / OUTPUT_SAMPLE_RATE:.1f} s")
    finally:
        await client.close()
        player.close()
    print(f"Hörproben: {out} (Tempo {speed:.2f}×, Klang {config['sound_profile']})")


asyncio.run(main())
