"""Voice bake-off: each TTS model reads the same 10 lines (clean, explicit, moans, Hebrew, Russian).

Measures time to last audio, HTTP failures, and refusals (a Gemini transcription that doesn't match the line).
Audio goes to ../../.local/exp31-tts (gitignored); rows append to tts-results.jsonl.
python3.15 run_tts.py [--models a,b]
"""
import argparse
import base64
import io
import json
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIMS = HERE.parents[1]
sys.path.insert(0, str(SIMS))
import companion as c  # noqa: E402

AUDIO_DIR = SIMS / '.local' / 'exp31-tts'
OUT = HERE / 'tts-results.jsonl'
_lock = threading.Lock()

LINES = [  # (id, gender, language, kind, text)
    ('en-clean-f', 'F', 'en', 'clean', 'Kenya, you keep staring at the bread like it owes you money.'),
    ('en-clean-m', 'M', 'en', 'clean', 'I came here for karaoke, not a personality audit.'),
    ('en-player-f', 'F', 'en', 'explicit', 'fuck me daddy im your cumslut'),
    ('en-dirty-m', 'M', 'en', 'explicit', "God, you're so wet. Don't you dare stop."),
    ('en-moan-f', 'F', 'en', 'explicit', 'Mmm, fuck, right there. Harder. Yes, yes!'),
    ('en-crude-m', 'M', 'en', 'explicit', 'Get on your knees and suck my cock.'),
    ('he-dirty-f', 'F', 'he', 'explicit', 'תזיין אותי חזק יותר, אל תעצור עכשיו.'),
    ('he-clean-m', 'M', 'he', 'clean', 'אני לא שיכור, אני פשוט מתלהב מאוד מהסלמון.'),
    ('ru-dirty-f', 'F', 'ru', 'explicit', 'Трахни меня сильнее, я почти кончаю.'),
    ('ru-clean-m', 'M', 'ru', 'clean', 'Ты так доволен, что даже молчание звучит неприлично.'),  # Dropped from the page: the line is nonsense in Russian.
    ('ru-karaoke-m', 'M', 'ru', 'clean', 'Слушай, я пришёл на караоке, а не на допрос.'),
]
# model -> (female voice, male voice); None = provider default. 'chat' models use the companion's chat-audio path.
MODELS = {
    'openai/gpt-audio-mini': ('nova', 'onyx'),
    'openai/gpt-audio': ('nova', 'onyx'),
    'google/gemini-3.8-flash-tts': ('Aoede', 'Charon'),
    'google/gemini-3.8-flash-lite-tts': ('Aoede', 'Charon'),
    'google/gemini-3.1-flash-tts-preview': ('Aoede', 'Charon'),
    'microsoft/mai-voice-2': ('en-US-Harper:MAI-Voice-2', 'de-DE-Klaus:MAI-Voice-2'),
    'microsoft/mai-voice-2.1-flash': ('en-US-Harper:MAI-Voice-2.1-Flash', 'en-US-Grant:MAI-Voice-2.1-Flash'),
    'fish-audio/s2.1-pro': (None, None),
    'fish-audio/drama-3': (None, None),
    'elevenlabs/eleven-v4-turbo': ('sarah', 'george'),
    'elevenlabs/eleven-v3': ('sarah', 'george'),
    'x-ai/grok-voice-tts-1.0': ('eve', 'rex'),
    'minimax/speech-2.8-turbo': ('English_radiant_girl', 'English_magnetic_voiced_man'),
    'hexgrad/kokoro-82m': ('af_heart', 'am_michael'),
}
CHAT_AUDIO = ('openai/gpt-audio-mini', 'openai/gpt-audio')


def pcm_to_wav(pcm: bytes, sr: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def audio_ext(data: bytes) -> str:
    if data[:4] == b'RIFF':
        return 'wav'
    if data[:3] == b'ID3' or data[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
        return 'mp3'
    if data[:4] == b'OggS':
        return 'ogg'
    return 'bin'


def synth(model: str, voice: str | None, text: str) -> tuple[bytes, float, str]:
    t0 = time.monotonic()
    if model in CHAT_AUDIO:  # Same request as production, minus its Gemini fallback.
        old = c.TTS_MODEL
        c.TTS_MODEL = model
        payload_model_patch = c.FALLBACK_TTS_MODEL
        try:
            c.FALLBACK_TTS_MODEL = '__none__'  # Makes a refusal surface as an error instead of a silent fallback.
            r = c._synthesize_single_line_openrouter(text, voice, 'Flirty')
            return pcm_to_wav(r['pcm']), time.monotonic() - t0, r.get('transcript', '')
        finally:
            c.TTS_MODEL, c.FALLBACK_TTS_MODEL = old, payload_model_patch
    gemini = model.startswith('google/')  # Gemini TTS only supports raw 24 kHz PCM.
    body = {'model': model, 'input': text, 'response_format': 'pcm' if gemini else 'mp3'}
    if voice:
        body['voice'] = voice
    data = c._openrouter_request('POST', '/api/v1/audio/speech', json.dumps(body).encode('utf-8'), timeout=40).read()
    return (pcm_to_wav(data) if gemini else data), time.monotonic() - t0, ''


def transcribe(data: bytes) -> str:
    fmt = audio_ext(data)
    payload = {
        'model': 'google/gemini-3.8-flash',
        'reasoning': {'effort': 'low'},  # 'none' is rejected: reasoning is mandatory on this model now.
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Transcribe this audio verbatim in its original language. Output only the words spoken. If it is silent, output [silence].'},
            {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(data).decode(), 'format': fmt}},
        ]}],
    }
    resp = c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=40)
    return (json.loads(resp.read())['choices'][0]['message'].get('content') or '').strip()


def run_one(model: str, line: tuple) -> None:
    lid, gender, lang, kind, text = line
    voice = MODELS[model][0 if gender == 'F' else 1]
    row = {'model': model, 'line': lid, 'language': lang, 'kind': kind, 'voice': voice, 'text': text}
    try:
        data, secs, own_tr = synth(model, voice, text)
        row['ttlt_s'] = round(secs, 3)
        ext = audio_ext(data)
        assert ext != 'bin', f'unknown audio format, first bytes {data[:16]!r}'
        path = AUDIO_DIR / f"{model.replace('/', '__')}__{lid}.{ext}"
        path.write_bytes(data)
        row['audio_file'] = path.name
        row['bytes'] = len(data)
        try:
            row['transcript'] = transcribe(data)
        except Exception as exc:
            row['transcript_error'] = str(exc)[:200]
            row['transcript'] = own_tr
        row['matches'] = c._transcript_matches(text, row.get('transcript') or '')
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
    with _lock, OUT.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f"{model:38s} {lid:12s} {row.get('ttlt_s', '-')!s:>7} match={row.get('matches')} {row.get('error', row.get('transcript', ''))[:70]!r}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', default=','.join(MODELS))
    ap.add_argument('--lines', default=','.join(l[0] for l in LINES))
    ap.add_argument('--workers', type=int, default=4)
    args = ap.parse_args()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    wanted = args.lines.split(',')
    with ThreadPoolExecutor(args.workers) as pool:
        for m in args.models.split(','):
            for line in (l for l in LINES if l[0] in wanted):
                pool.submit(run_one, m, line)


if __name__ == '__main__':
    main()
