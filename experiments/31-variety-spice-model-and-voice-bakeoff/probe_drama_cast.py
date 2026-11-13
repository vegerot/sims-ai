"""Audition a drama-3 voice cast: each library voice reads an English, a Hebrew, and a Russian line (16-bit 44.1 kHz PCM).

Gemini hears the three clips together: one speaker or not, gender and age, natural or not, and each transcript.
Writes drama-cast-probe.jsonl.
"""
import base64
import io
import json
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import companion as c  # noqa: E402

CAST = {  # group -> {name: Fish voice id}
    'female': {'Sarah': '933563129e564b19a115bedd57b7406a', 'Selene': 'b347db033a6549378b48d00acb0d06cd',
               'Hannah': '9a9cf47702da476aa4629e2506d4a857', 'Laura': 'e3cd384158934cc9a01029cd7d278634',
               'Paula': 'c2623f0c075b4492ac367989aee1576f', 'Friendly Women': 'b545c585f631496c914815291da4e893'},
    'male': {'Adrian': 'bf322df2096a46f18c579d0baa36f41d', 'Ethan': '536d3a5e000945adb7038665781a4aca',
             'Slax': 'c5f56a6cc2ec4fa8920cb4c5889a3fb7', 'alex': '1d52151a55eb4878a997bd06e816b5f6',
             'Narrator': '0327fdb5da9e4fd782899a8058c8ae2b'},
    'elder': {'History Voice': 'fbac16744ffa49a9a51c29b1bf19242a', 'Voice DL': '1936333080804be19655c6749b2ae7b2',
              'Measured Storyteller': '8906b5268cae414fb9b8d3da6e84413d'},
    'child': {'Aubrey': '029f407da0914eab9469a0edbc23efa8', 'Molly': 'a2b1bd5223d14144bf330c4656c9dd30',
              'Tim': 'bad4763220fe444993111e1683ff5342'},
}
LINES = [
    '[amused] You keep staring at the bread like it owes you money.',
    '[annoyed] אני לא שיכור, אני פשוט מתלהב מאוד מהסלמון.',
    '[annoyed] Слушай, я пришёл на караоке, а не на допрос.',
]


def wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm)
    return buf.getvalue()


def audition(item):
    group, name, vid = item
    clips = []
    for line in LINES:
        body = {'model': 'fish-audio/drama-3', 'input': line, 'voice': vid, 'response_format': 'pcm'}
        clips.append(wav(c._openrouter_request('POST', '/api/v1/audio/speech', json.dumps(body).encode(), timeout=40).read()))
    content = [{'type': 'text', 'text': (
        'Three clips of one game character: English, Hebrew, Russian. Reply in JSON only: {"same_speaker": true|false, '
        '"gender": "male"|"female"|"unclear", "age": "child"|"teen"|"young adult"|"adult"|"elderly", '
        '"natural": true|false, "quality_note": "few words", "transcripts": [three verbatim transcripts]}')}]
    content += [{'type': 'input_audio', 'input_audio': {'data': base64.b64encode(b).decode(), 'format': 'wav'}} for b in clips]
    payload = {'model': 'google/gemini-3.8-flash', 'reasoning': {'effort': 'low'}, 'max_tokens': 3000,
               'response_format': {'type': 'json_object'}, 'messages': [{'role': 'user', 'content': content}]}
    raw = json.loads(c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode(), timeout=90).read())
    text = raw['choices'][0]['message'].get('content') or ''
    try:
        v = json.loads(text)
    except json.JSONDecodeError:
        v = {'raw': text[:300]}
    tr = v.get('transcripts') or ['', '', '']
    v['verbatim'] = [c._transcript_matches(l.split('] ', 1)[1], t) for l, t in zip(LINES, tr)]
    return {'group': group, 'name': name, 'voice': vid, **v}


items = [(g, n, vid) for g, voices in CAST.items() for n, vid in voices.items()]
with ThreadPoolExecutor(6) as pool:
    rows = list(pool.map(audition, items))
with (HERE / 'drama-cast-probe.jsonl').open('w', encoding='utf-8') as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f"{r['group']:6s} {r['name']:21s} same={r.get('same_speaker')!s:5} {r.get('gender', '?'):7s} {r.get('age', '?'):11s} "
              f"natural={r.get('natural')!s:5} en/he/ru={r['verbatim']}  {r.get('quality_note', r.get('raw', ''))}")
