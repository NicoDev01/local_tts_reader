"""Do the German voices say common English terms the English way?

Each term goes through the reader's own text preparation, is spoken alone and transcribed by
Whisper in English mode. A term passes when Whisper writes the English word, so it is a check
of what a listener most likely hears, not of phonetics.

Needs Whisper large-v3-turbo as a whisper.cpp server on 127.0.0.1:8179 (OpenWhispr ships one):
   whisper-server -m ggml-large-v3-turbo.bin --host 127.0.0.1 --port 8179 -l en
Then (online, Edge voices):
   .venv\\Scripts\\python.exe -B tests\\english_terms_check.py [Begriff ...] [--voices killian,katja,conrad]
"""
import asyncio
import io
import json
import re
import sys
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import soundfile as sf
import soxr
from high_fidelity_tts import HighFidelityTTSClient
from text_cleaner import clean_text, speakable

VOICES = {'killian': 'de-DE-KillianNeural', 'katja': 'de-DE-KatjaNeural', 'conrad': 'de-DE-ConradNeural'}

TERMS = """
Meeting Call Deadline Feedback Team Manager Business Startup Pitch Deal Sales Marketing Leads Customer
Service Support Onboarding Stakeholder Roadmap Sprint Workshop Coaching Recruiting Homeoffice Remote
Benefits Performance Insights Tracking Reporting Cashflow Budget Forecast Revenue Pricing Skills
Mindset Commitment Challenge Feature Features Release Launch Update Upgrade Tool Tools Workflow Content
Newsletter Online Offline Software Hardware Download Upload Account Password Browser Website Homepage
Link Cloud Server Backup E-Mail Chat Smartphone Laptop App Apps Shop Checkout Payment Subscription
Prompt Prompts Agent Agents Token Tokens Framework Library Repository Branch Deployment Deploy
Pipeline Frontend Fullstack Developer Coding Code Testing Tests Fix Container Docker Endpoint Request
Response Interface Plugin Extension Settings Dashboard Benchmark Latency Streaming Chatbot Copilot
Claude ChatGPT Cursor Context Reasoning Embedding Use-Case Best-Practice Know-how Open-Source
Pull-Request Machine-Learning Fine-Tuning Use-Cases Feedback-Schleife Team-Meeting Live-Demo
""".split()


def normalize(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def heard_as(term, transcript):
    want, got = normalize(term), normalize(transcript)
    return got in (want, want + 's', want.rstrip('s')) or (len(want) > 5 and want in got)


def whisper(audio, sr):
    pcm = soxr.resample(audio, sr, 16000)
    buf = io.BytesIO()
    sf.write(buf, pcm, 16000, format='WAV', subtype='PCM_16')
    boundary = uuid.uuid4().hex
    body = b''.join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        'Content-Type: audio/wav\r\n\r\n'.encode(), buf.getvalue(), b'\r\n',
        *(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
          for k, v in (('language', 'en'), ('temperature', '0'), ('response_format', 'json'))),
        f'--{boundary}--\r\n'.encode()])
    request = urllib.request.Request('http://127.0.0.1:8179/inference', body,
                                     {'Content-Type': f'multipart/form-data; boundary={boundary}'})
    for attempt in range(3):  # the server now and then drops a request
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read())['text'].strip()
        except OSError:
            if attempt == 2:
                raise


async def check(terms, voices, spoken=None):
    client, rows = HighFidelityTTSClient(), []
    try:
        for term in terms:
            text = spoken(term) if spoken else speakable(clean_text(term))
            row = {'term': term, 'sent': text}
            for name in voices:
                for attempt in range(3):
                    audio, sr = await client.synthesize(text, voice=VOICES[name], rate='+0%')
                    if len(audio):
                        break
                heard = whisper(audio, sr) if len(audio) else ''
                row[name] = (heard_as(term, heard), heard)
            rows.append(row)
            marks = ' '.join(f"{name}:{'ok' if row[name][0] else 'NEIN'} „{row[name][1]}“" for name in voices)
            print(f"{term:18} -> {text:22} {marks}", flush=True)
    finally:
        await client.close()
    return rows


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = [a for a in sys.argv[1:] if not a.startswith('--voices')]
    voices = next((a.split('=', 1)[1].split(',') for a in sys.argv[1:] if a.startswith('--voices=')), ['killian'])
    rows = asyncio.run(check(args or TERMS, voices))
    failed = [r['term'] for r in rows if not all(r[v][0] for v in voices)]
    print(f'\n{len(rows) - len(failed)}/{len(rows)} englisch gehört. Nicht: {", ".join(failed)}')
