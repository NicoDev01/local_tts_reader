"""Pronunciation check: does our text preparation help or hurt the Microsoft voice?

Each case is spoken twice, from the raw text and from ``clean_text``; Whisper
transcribes both. The report shows what a listener would most likely hear.
Whisper writes numbers as digits and acronyms as words, so the report helps a
human judge; it is not a pass/fail test.

1. Synthesize (project environment, online):
   .venv\\Scripts\\python.exe -B tests\\pronunciation_check.py synthesize
2. Transcribe (separate throwaway environment; model cache in tests\\.whisper_cache, about 1.6 GB):
   uv run --isolated --no-project --python 3.12 --with faster-whisper==1.2.1 --with soundfile --with soxr python -I tests\\pronunciation_check.py transcribe
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "artifacts" / "pronunciation"

CASES = [
    "Am 3. Oktober 2026 um 14:30 Uhr beginnt das Treffen.",
    "Der Preis beträgt 1.299,99 € inkl. MwSt.",
    "Das kostet 3,5 Mio. Euro bzw. ca. 12 % mehr.",
    "Er wohnt in der Hauptstr. 12 in 80331 München.",
    "Siehe S. 45 ff. und Art. 3 Abs. 2 GG.",
    "Die Sitzung ist am Mo. 12.05. von 9-17 Uhr.",
    "Das Spiel endete 2:1 für Bayern.",
    "Version 2.3.1 wurde am 01.02.2025 veröffentlicht.",
    "Herr Dr. Müller und Frau Prof. Schmidt kamen.",
    "Die Temperatur lag bei -5 °C.",
    "Der 2. Weltkrieg endete 1945.",
    "Kinder ab 6 J. zahlen 5 € Eintritt.",
    "Die XY GmbH & Co. KG meldet Gewinne.",
    "Die Mieten stiegen um 5–7 % im Jahr 2024/25.",
    "Er war z. B. in den USA, d. h. in New York.",
    "Die KI erstellt ein PDF über die API.",
    "Die EU und die NASA arbeiten zusammen.",
    "Der Zug fährt um 18.45 Uhr ab Gleis 3.",
    "Ludwig XIV. regierte lange.",
    "Kosten: 15 €/Monat oder 150 €/Jahr.",
    "Tel.: +49 30 1234567",
    "Laut § 312 BGB gilt ein Widerrufsrecht.",
    "Die CPU hat 16 GB RAM und eine SSD.",
    "Am 24.12. ist Heiligabend.",
    "Das ist die 3. Auflage, Bd. 2.",
    "Schritte:\n1. Öffnen\n2. Speichern\n3. Schließen",
    "Die Datei liegt unter C:\\Users\\Max\\bericht.pdf.",
    "Ca. 2.500 Mitarbeiter, u. a. in Berlin, arbeiten dort.",
    "Ein Klick auf das Tray-Symbol öffnet das Tray-Menü.",
    "Das Plug-in liest die Clipboard-Daten aus.",
    "Das Pop-up erscheint nach dem Login im Browser-Tab.",
    "Schick mir die E-Mail mit dem Download-Link.",
]


def synthesize():
    import asyncio
    import soundfile as sf
    sys.path.insert(0, str(HERE.parent))
    from high_fidelity_tts import HighFidelityTTSClient
    from text_cleaner import clean_text, speakable

    async def run():
        client, rows = HighFidelityTTSClient(), []
        OUT.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(CASES):
            row = dict(case=i, text=text, cleaned=speakable(clean_text(text)))
            for kind, value in (("raw", text), ("cleaned", row["cleaned"])):
                audio, sr = await client.synthesize(value, rate="+0%")
                path = OUT / f"{i:02d}-{kind}.wav"
                sf.write(str(path), audio, sr)
                row[f"{kind}_seconds"] = round(len(audio) / sr, 2)
            rows.append(row)
            print(f"{i + 1}/{len(CASES)}", flush=True)
        await client.close()
        (OUT / "cases.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    asyncio.run(run())


def transcribe():
    import soundfile as sf
    import soxr
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8",
                         download_root=str(HERE / ".whisper_cache"))
    rows = json.loads((OUT / "cases.json").read_text(encoding="utf-8"))
    lines = ["| # | Eingabe | Whisper hört: roh | Whisper hört: aufbereitet | Dauer roh / aufb. |",
             "|---|---|---|---|---|"]
    for row in rows:
        heard = {}
        for kind in ("raw", "cleaned"):
            # Decode here: faster-whisper's own file decoding breaks with current PyAV releases.
            audio, sr = sf.read(str(OUT / f"{row['case']:02d}-{kind}.wav"), dtype="float32")
            audio = soxr.resample(audio, sr, 16000)
            segments, _ = model.transcribe(audio, language="de", beam_size=5, vad_filter=False)
            heard[kind] = " ".join(s.text.strip() for s in segments)
        row.update(heard_raw=heard["raw"], heard_cleaned=heard["cleaned"])
        cell = lambda s: s.replace("\n", " ⏎ ").replace("|", "/")
        lines.append(f"| {row['case']} | {cell(row['text'])} | {cell(heard['raw'])} | {cell(heard['cleaned'])} | "
                     f"{row['raw_seconds']} / {row['cleaned_seconds']} s |")
        print(lines[-1], flush=True)
    (OUT / "cases.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # -I ignores PYTHONIOENCODING
    {"synthesize": synthesize, "transcribe": transcribe}[sys.argv[1]]()
