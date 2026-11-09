"""Which TTS engines can return WAV or raw PCM (the companion has no MP3 decoder), and at what sample rate?"""
import io
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import companion as c  # noqa: E402

ENGINES = {
    'x-ai/grok-voice-tts-1.0': 'eve', 'elevenlabs/eleven-v4-turbo': 'sarah', 'minimax/speech-2.8-turbo': 'English_radiant_girl',
    'fish-audio/drama-3': None, 'fish-audio/s2.1-pro': None, 'google/gemini-3.8-flash-lite-tts': 'Aoede',
}
TEXT = 'Mmm, fuck, right there. Harder. Yes, yes!'
results = {}
for model, voice in ENGINES.items():
    for fmt in ('wav', 'pcm'):
        body = {'model': model, 'input': TEXT, 'response_format': fmt, **({'voice': voice} if voice else {})}
        t0 = time.monotonic()
        try:
            data = c._openrouter_request('POST', '/api/v1/audio/speech', json.dumps(body).encode(), timeout=40).read()
            info = {'bytes': len(data), 'head': data[:4].hex(), 's': round(time.monotonic() - t0, 2)}
            if data[:4] == b'RIFF':
                with wave.open(io.BytesIO(data)) as w:
                    info.update(rate=w.getframerate(), width=w.getsampwidth(), channels=w.getnchannels(),
                                seconds=round(w.getnframes() / w.getframerate(), 2))
            else:
                info['seconds_if_24k_s16'] = round(len(data) / 48000, 2)
        except Exception as exc:
            info = {'error': str(exc)[:160]}
        results[f'{model} {fmt}'] = info
        print(model, fmt, info, flush=True)
(Path(__file__).with_name('format-probe.json')).write_text(json.dumps(results, indent=1), encoding='utf-8')
