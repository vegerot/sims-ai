"""Does drama-3 keep one voice across lines? A voice id vs a fixed bracket direction, three lines each.

Gemini hears the three clips of a set together and says whether one person speaks all of them.
Also: does a mood direction still work on top of a voice id, and what sample rate is response_format=pcm?
Writes drama-consistency-probe.json.
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIMS = HERE.parents[1]
sys.path.insert(0, str(SIMS))
import companion as c  # noqa: E402

AUDIO = SIMS / '.local' / 'exp31-tts'
LINES = [
    '[annoyed] I told you the toaster is not a phone charger.',
    '[flirty, breathless] Come here. No, closer than that.',
    '[sad, quiet] I just thought tonight would be different.',
]
SETS = {  # set -> (voice id or None, prefix added before each line's own direction)
    'voice-sarah': ('933563129e564b19a115bedd57b7406a', ''),
    'voice-adrian': ('bf322df2096a46f18c579d0baa36f41d', ''),
    'direction-man': (None, '[warm low-voiced man in his 30s] '),
    'direction-woman': (None, '[bright young woman with a raspy laugh] '),
}


def tts(text: str, voice, fmt: str) -> tuple[bytes, float]:
    body = {'model': 'fish-audio/drama-3', 'input': text, 'response_format': fmt}
    if voice:
        body['voice'] = voice
    t0 = time.monotonic()
    data = c._openrouter_request('POST', '/api/v1/audio/speech', json.dumps(body).encode('utf-8'), timeout=40).read()
    return data, round(time.monotonic() - t0, 2)


def ask(clips: list[bytes], question: str) -> str:
    content = [{'type': 'text', 'text': question}] + [
        {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(b).decode(), 'format': 'mp3'}} for b in clips]
    payload = {'model': 'google/gemini-3.8-flash', 'reasoning': {'effort': 'low'}, 'max_tokens': 2000,
               'messages': [{'role': 'user', 'content': content}]}
    resp = c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=90)
    return (json.loads(resp.read())['choices'][0]['message'].get('content') or '').strip()


out = {}
for name, (voice, prefix) in SETS.items():
    clips, secs = [], []
    for i, line in enumerate(LINES):
        data, s = tts(prefix + line, voice, 'mp3')
        (AUDIO / f'consistency-{name}-{i}.mp3').write_bytes(data)
        clips.append(data)
        secs.append(s)
    verdict = ask(clips, 'These three clips are lines from a video game character. Answer in 3 short lines: '
                         '1) SAME or DIFFERENT speaker across all three (judge voice timbre, not emotion), with confidence; '
                         '2) gender and rough age of each; 3) the emotion of each clip, and whether any bracketed stage direction was read aloud.')
    out[name] = {'voice': voice, 'prefix': prefix, 'ttlt_s': secs, 'verdict': verdict}
    print(f'=== {name} {secs}\n{verdict}\n', flush=True)

# PCM: compare its byte length with the MP3's duration (ffprobe) to infer the sample rate (16-bit mono assumed).
mp3, _ = tts('[calm] One two three four five six seven eight nine ten.', None, 'mp3')
pcm, _ = tts('[calm] One two three four five six seven eight nine ten.', None, 'pcm')
(AUDIO / 'pcm-probe.mp3').write_bytes(mp3)
dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(AUDIO / 'pcm-probe.mp3')],
                           capture_output=True, text=True).stdout.strip())
out['pcm'] = {'pcm_bytes': len(pcm), 'mp3_duration_s': dur, 'implied_rate_16bit_mono': round(len(pcm) / 2 / dur), 'first_bytes': pcm[:8].hex()}
print('pcm:', out['pcm'])
(HERE / 'drama-consistency-probe.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
