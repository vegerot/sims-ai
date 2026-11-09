"""Freeze the experiment's scene set: the replay set, real Nov 6 events (incl. WickedWhims), and harness sex scenes.

Run once: python3.15 make_scenes.py. Writes scenes/*.json and scenes/memories-snapshot.json.
"""
import copy
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIMS = HERE.parents[1]
OUT = HERE / 'scenes'
OUT.mkdir(exist_ok=True)

# Real events from her Nov 6 2026 session (events.jsonl), chosen to cover WickedWhims and repetition-prone types.
REAL = {
    'thought-1794037916038-3': '16-ww-thought-amie-watching',
    'thought-1794037939782-4': '17-ww-thought-gefen-mid-sex',
    'thought-1794037957981-5': '18-ww-thought-tal-mid-sex',
    'chat-1794038012694-6': '19-ww-player-chat-explicit',
    'drama-1794038076248-7': '20-ww-drama-satisfying-sex',
    '1794038156367-9': '21-ww-ask-for-sex-round-two',
    '1794012520310-7': '22-ww-ask-for-sex-rejected',
    '1794038088071-8': '23-flirt-while-naked',
    'thought-1794015851897-9': '24-thought-tipsy-restaurant',
    '1794012686227-11': '25-supportive-face-flop',
    'renov-1794015509999-1': '26-renovation-restaurant',
    '1794015713113-4': '27-restaurant-table-request',
}
LANGUAGE = {  # Forced languages, otherwise English (production picks Hebrew/Russian 12% of the time at random).
    '19-ww-player-chat-explicit': None,
    '06-karaoke-bar-yuvi-carlos': 'Hebrew (עברית)',
    '20-ww-drama-satisfying-sex': 'Russian (Русский)',
    '31-ww-sex-scene-climax': 'Hebrew (עברית)',
}

events = {}
for line in (SIMS / '.local' / 'data' / 'events.jsonl').open(encoding='utf-8'):
    e = json.loads(line)
    if e.get('event_id') in REAL and 'actor' in e:
        events[e['event_id']] = e
missing = set(REAL) - set(events)
assert not missing, missing

scenes = {}
for p in sorted((SIMS / 'experiments' / 'replay-set').glob('*.json')):
    scenes[p.stem] = json.loads(p.read_text(encoding='utf-8-sig'))
for eid, name in REAL.items():
    scenes[name] = events[eid]

# Harness-only sex scenes (the mod doesn't emit `sex_scene` yet): reuse the real mid-sex snapshot of gefen + tal.
base = events['chat-1794038012694-6']
for name, stage, anim in (
    ('28-ww-sex-scene-start', 'start', {'name': 'Slow Missionary', 'category': 'VAGINAL'}),
    ('29-ww-sex-scene-oral', 'change', {'name': 'Kneeling Blowjob', 'category': 'ORAL'}),
    ('30-ww-sex-scene-doggy', 'change', {'name': 'Doggy Style', 'category': 'VAGINAL'}),
    ('31-ww-sex-scene-climax', 'climax', {'name': 'Doggy Style', 'category': 'CLIMAX'}),
):
    ev = copy.deepcopy(base)
    ev.pop('player_message', None)
    ev.update(type='sex_scene', interaction='sex_scene', outcome='SEX', event_id=f'harness-{name}',
              sex_stage=stage, sex_animation=anim)
    scenes[name] = ev

for name, ev in scenes.items():
    ev['_language'] = LANGUAGE.get(name) or 'English'
    (OUT / f'{name}.json').write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding='utf-8')
shutil.copy(SIMS / '.local' / 'data' / 'memories.json', OUT / 'memories-snapshot.json')
print(len(scenes), 'scenes written to', OUT)
