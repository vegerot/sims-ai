"""Can fish-audio/drama-3 give each Sim its own voice? Gemini judges speaker gender and whether a direction was read aloud.

1. The bake-off clips (no voice set): does the default voice follow the line's gender?
2. New clips: bracket directions ("[deep male voice]") and a `voice` id, on male and female lines.
Writes drama-voice-probe.jsonl; audio goes to ../../.local/exp31-tts/probe-*.mp3.
"""
import base64
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIMS = HERE.parents[1]
sys.path.insert(0, str(SIMS))
import companion as c  # noqa: E402

AUDIO = SIMS / '.local' / 'exp31-tts'
OUT = HERE / 'drama-voice-probe.jsonl'
MALE = "God, you're so wet. Don't you dare stop."
FEMALE = 'Kenya, you keep staring at the bread like it owes you money.'
PROBES = [  # (id, text, voice)
    ('m-plain', MALE, None),
    ('f-plain', FEMALE, None),
    ('m-dir-deep-male', '[deep male voice, breathless] ' + MALE, None),
    ('f-dir-deep-male', '[deep male voice, deadpan] ' + FEMALE, None),
    ('m-dir-young-woman', '[young woman, teasing] ' + MALE, None),
    ('m-dir-old-man', '[gravelly old man, grumpy] ' + MALE, None),
    ('f-voice-example-id', FEMALE, '9a9cf47702da476aa4629e2506d4a857'),  # The example id in Fish's OpenRouter migration doc.
]


def judge(data: bytes) -> dict:
    payload = {
        'model': 'google/gemini-3.8-flash', 'reasoning': {'effort': 'low'}, 'max_tokens': 2000,
        'response_format': {'type': 'json_object'},
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Listen to this clip. Reply with JSON only: {"transcript": verbatim words spoken, '
                                     '"gender": "male"|"female"|"unclear", "age": "child"|"young adult"|"adult"|"elderly", '
                                     '"tone": a few words}.'},
            {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(data).decode(), 'format': 'mp3'}},
        ]}],
    }
    resp = c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=60)
    content = json.loads(resp.read())['choices'][0]['message']['content'] or ''
    try:
        return json.loads(content)
    except json.JSONDecodeError:  # The first run came back truncated mid-string.
        return {'raw': content[:300]}


def existing(path: Path) -> dict:
    return {'probe': 'bakeoff:' + path.stem.split('__')[-1], **judge(path.read_bytes())}


def new(probe) -> dict:
    pid, text, voice = probe
    body = {'model': 'fish-audio/drama-3', 'input': text, 'response_format': 'mp3'}
    if voice:
        body['voice'] = voice
    t0 = time.monotonic()
    try:
        data = c._openrouter_request('POST', '/api/v1/audio/speech', json.dumps(body).encode('utf-8'), timeout=40).read()
    except Exception as exc:
        return {'probe': pid, 'input': text, 'voice': voice, 'error': str(exc)[:200]}
    secs = round(time.monotonic() - t0, 2)
    (AUDIO / f'probe-{pid}.mp3').write_bytes(data)
    return {'probe': pid, 'input': text, 'voice': voice, 'ttlt_s': secs, **judge(data)}


with ThreadPoolExecutor(6) as pool:
    rows = list(pool.map(existing, sorted(AUDIO.glob('fish-audio__drama-3__*.mp3')))) + list(pool.map(new, PROBES))
with OUT.open('w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f"{r['probe']:24s} {r.get('gender', '-'):7s} {r.get('age', '-'):12s} {r.get('ttlt_s', '')!s:>5} "
              f"{r.get('error') or r.get('transcript', '')[:70]!r}  [{r.get('tone', '')}]")
