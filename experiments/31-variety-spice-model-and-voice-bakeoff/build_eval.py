"""Build eval/data.json (blind: candidates are shuffled letters) and eval/key.json (letter -> model) for the rating page."""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import companion as c  # noqa: E402
EVAL = HERE / 'eval'
rng = random.Random(31)


def load(name):
    p = HERE / name
    return [json.loads(l) for l in p.open(encoding='utf-8')] if p.exists() else []


text_rows = load('text-results.jsonl')
session_rows = load('session-results.jsonl')
tts_rows = load('tts-results.jsonl')
scenes = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted((HERE / 'scenes').glob('[0-9]*.json'))}

TEXT_CANDIDATES = [  # (label, source, model, prompt)
    ('luna v1 (today)', 'text', 'openai/gpt-6-luna', 'v1'),
    ('luna v2', 'text', 'openai/gpt-6-luna', 'v2'),
    ('luna v3', 'session', 'openai/gpt-6-luna', 'v3'),
    ('grok-4.20 v2', 'text', 'x-ai/grok-4.20', 'v2'),
    ('grok-4.20 v3', 'session', 'x-ai/grok-4.20', 'v3'),
    ('grok-4.3 v2', 'text', 'x-ai/grok-4.3', 'v2'),
    ('glm-5.2 v2', 'text', 'z-ai/glm-5.2', 'v2'),
    ('deepseek v2', 'text', 'deepseek/deepseek-v4.1-flash-1017', 'v2'),
]


def describe(ev):
    who = ev['actor'].get('name') + (f" → {ev['target'].get('name')}" if isinstance(ev.get('target'), dict) else '')
    bits = [ev.get('type'), who, str(ev.get('interaction') or '').split(':')[-1]]
    if ev.get('outcome'):
        bits.append(str(ev['outcome']))
    if ev.get('sex_animation'):
        bits.append(f"{ev['sex_animation']['name']} ({ev['sex_animation']['category']}, {ev.get('sex_stage')})")
    if ev.get('drama_buff'):
        bits.append(str(ev['drama_buff'].get('id')).split(':')[-1])
    if ev.get('_language') != 'English':
        bits.append(ev['_language'])
    return {'summary': ' · '.join(b for b in bits if b), 'player_message': ev.get('player_message')}


key = {'text': {}, 'voice': {}, 'session': {}}
data = {'text': [], 'voice': [], 'session': []}
# Ratings in human-ratings.jsonl point at letters, so a rebuild must keep every letter that already exists.
OLD_KEY = json.loads((EVAL / 'key.json').read_text(encoding='utf-8')) if (EVAL / 'key.json').exists() else {}


def shuffle_stable(section, item, things, name_of):
    """Shuffle things, unless the old key already fixed this item's order for the same set of things."""
    rng.shuffle(things)  # Always consume the rng, so items without an old order still get the original seed's order.
    old = OLD_KEY.get(section, {}).get(item)
    if old and sorted(old.values()) == sorted(name_of(t) for t in things):
        order = list(old.values())
        things.sort(key=lambda t: order.index(name_of(t)))
    return things


for name, ev in scenes.items():
    cands = []
    for label, src, model, prompt in TEXT_CANDIDATES:
        if src == 'text':
            r = next((r for r in text_rows if r['scene'] == name and r['model'] == model and r['prompt'] == prompt), None)
        else:  # Pass 0 of the session simulation is a normal single call with the frozen memory.
            r = next((r for r in session_rows if r['scene'] == name and r['model'] == model and r['prompt'] == prompt and r['pass'] == 0), None)
        if r and r.get('text'):
            cands.append((label, r['text'], r.get('elapsed_s')))
    shuffle_stable('text', name, cands, lambda c: c[0])
    letters = 'ABCDEFGH'
    key['text'][name] = {letters[i]: c[0] for i, c in enumerate(cands)}
    data['text'].append({'id': name, **describe(ev), 'spicy': c.is_spicy(ev),
                         'candidates': [{'id': letters[i], 'text': c[1]} for i, c in enumerate(cands)]})

# ru-clean-m was dropped (nonsense Russian); its old ratings stay in human-ratings.jsonl but are ignored.
VOICE_LINES = ['en-clean-f', 'en-moan-f', 'en-dirty-m', 'en-player-f', 'he-dirty-f', 'ru-karaoke-m', 'ru-dirty-f']
for lid in VOICE_LINES:
    rs = [r for r in tts_rows if r['line'] == lid and r.get('audio_file')]
    shuffle_stable('voice', lid, rs, lambda r: r['model'])
    key['voice'][lid] = {f'V{i + 1}': r['model'] for i, r in enumerate(rs)}
    data['voice'].append({'id': lid, 'text': rs[0]['text'] if rs else '',
                          'clips': [{'id': f'V{i + 1}', 'src': f"audio/{r['audio_file']}"} for i, r in enumerate(rs)]})

specs = sorted({f"{r['model']}:{r['prompt']}" for r in session_rows})
rng.shuffle(specs)
if sorted(OLD_KEY.get('session', {}).values()) == sorted(specs):  # The session key is one flat S-id -> spec map.
    specs = list(OLD_KEY['session'].values())
for i, spec in enumerate(specs):
    rs = [r for r in session_rows if f"{r['model']}:{r['prompt']}" == spec and r['pass'] == 1 and r.get('text')][:16]
    sid = f'S{i + 1}'
    key['session'][sid] = spec
    data['session'].append({'id': sid, 'lines': [r['text'] for r in rs]})

EVAL.mkdir(exist_ok=True)
(EVAL / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
(EVAL / 'key.json').write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding='utf-8')
print(len(data['text']), 'scenes,', sum(len(v['clips']) for v in data['voice']), 'clips,', len(data['session']), 'sessions')
