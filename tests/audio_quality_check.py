"""Explicit online integration check with synthetic German text, no captured data."""
import asyncio
import json
from pathlib import Path
import sys
import threading
import time

import numpy as np
import soundfile as sf
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_player import AudioPlayer
from high_fidelity_tts import HighFidelityTTSClient
from playback import PlaybackController
from settings import DEFAULTS

TEXT = ('Heute nehmen wir uns Zeit für einen ruhigen, verständlichen Text. '
        'Die Stimme soll natürlich klingen: mit klaren Satzanfängen und sanften Übergängen. '
        'Auch wenn wir schneller lesen, bleiben die Worte gut verständlich. '
        'Ein kurzer Einschub (wie dieser hier) gehört weiterhin zum gleichen Satz.')
OUT = Path(__file__).resolve().parent / 'artifacts' / 'smooth'


async def samples():
    OUT.mkdir(parents=True, exist_ok=True)
    client, player = HighFidelityTTSClient(), AudioPlayer()
    report = []
    try:
        for speed in (.7, 1, 1.25, 1.5, 2):
            start = time.monotonic()
            audio, sr = await asyncio.wait_for(client.synthesize(TEXT, rate=f'{round((speed-1)*100):+d}%'), 30)
            assert audio is not None and len(audio)
            prepared = player.prepare(audio, sr, speed)
            sf.write(OUT / f'nativ_{speed:.2f}x.wav', prepared.source, 48000)
            report.append(dict(speed=speed, request_seconds=round(time.monotonic()-start, 3),
                               audio_seconds=round(len(prepared.source)/48000, 3),
                               peak=float(np.max(np.abs(prepared.source)))))
            if speed == 1:
                old = player._stretch(prepared.source, 1.25)
                sf.write(OUT / 'vergleich_lokales_tempo_1.25x.wav', old, 48000)
            print(report[-1], flush=True)
    finally:
        await client.close()
        player.close()
    return report


def device_check():
    # Exercise the real Windows audio driver silently, including live changes.
    events, writes = [], [0]
    player = AudioPlayer()
    real_write = player._write
    def silent_write(block):
        writes[0] += 1
        if writes[0] in (20, 40, 60, 80):
            player.set_controls({20: .7, 40: 1.5, 60: 1.25, 80: 2}[writes[0]], 0)
        real_write(np.zeros_like(block))
    player._write = silent_write
    cfg = dict(DEFAULTS, speed=2.0, volume=0.0)
    controller = PlaybackController(lambda *a: events.append(a[1]), cfg, player=player)
    try:
        job = controller.start((TEXT + '\n\n') * 3, cfg)
        assert job.done.wait(90), 'Integration timeout'
        assert 'done' in events and 'error' not in events, events
        result = dict(device=str(sd.query_devices(kind='output')['name']),
                      writes=writes[0], underflows=player.underflows,
                      startup_underflows=player.startup_underflows, events=events)
        assert player.underflows == 0, result
        return result
    finally:
        controller.close()


if __name__ == '__main__':
    report = dict(samples=asyncio.run(samples()), device=device_check())
    (OUT / 'measurements.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report['device'], ensure_ascii=False), flush=True)
