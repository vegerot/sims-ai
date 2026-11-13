"""BanterLab's experiment harnesses in one CLI. The mod itself stays in src/, companion.py, and build.py.

    python3.15 lab.py exp05 resources                 map voice cues to base-game audio resources (read-only)
    python3.15 lab.py exp31 scenes                    freeze the scene set from her events
    python3.15 lab.py exp31 text [--models ...]       text bake-off -> text-results.jsonl
    python3.15 lab.py exp31 session MODEL:PROMPT ...  3-pass simulated evening -> session-results.jsonl
    python3.15 lab.py exp31 tts [--models ...]        voice bake-off -> tts-results.jsonl
    python3.15 lab.py exp31 analyze {text,session,tts,ratings}
    python3.15 lab.py exp31 eval                      build the blind rating page's data.json + key.json
    python3.15 lab.py exp31 serve                     serve the rating page on localhost:8731
    python3.15 lab.py exp31 probe {formats,drama-voices,drama-consistency,drama-cast}

Outputs land in the experiment's own folder (experiments/<NN-...>/), next to its result.json.
"""
import argparse
import base64
import collections
import copy
import gzip
import hashlib
import io
import json
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import companion as c

ROOT = Path(__file__).resolve().parent
EXP05 = ROOT / 'experiments' / '05-fixed-speech'
EXP31 = ROOT / 'experiments' / '31-variety-spice-model-and-voice-bakeoff'
EVAL = EXP31 / 'eval'
SCENES = EXP31 / 'scenes'
TTS_AUDIO = ROOT / '.local' / 'exp31-tts'
_write_lock = threading.Lock()


# ── Shared helpers ────────────────────────────────────────────────────────────────────────────────

def append_jsonl(path: Path, row: dict) -> None:
    with _write_lock, path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding='utf-8')] if path.exists() else []


def load_scenes() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted(SCENES.glob('[0-9]*.json'))}


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    """16-bit mono PCM -> WAV file bytes."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
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


def speak(model: str, text: str, voice: str | None = None, fmt: str = 'mp3') -> tuple[bytes, float]:
    """One OpenRouter /audio/speech call: (audio bytes, seconds)."""
    body = {'model': model, 'input': text, 'response_format': fmt, **({'voice': voice} if voice else {})}
    t0 = time.monotonic()
    data = c._openrouter_request('POST', '/api/v1/audio/speech', json.dumps(body).encode('utf-8'), timeout=40).read()
    return data, round(time.monotonic() - t0, 2)


def listen(clips: list[bytes], question: str, json_reply: bool = False) -> str:
    """Ask Gemini about one or more audio clips (WAV, MP3, or OGG); returns its text reply."""
    content = [{'type': 'text', 'text': question}] + [
        {'type': 'input_audio', 'input_audio': {'data': base64.b64encode(b).decode(), 'format': audio_ext(b)}} for b in clips]
    payload = {
        'model': 'google/gemini-3.8-flash',
        'reasoning': {'effort': 'low'},  # 'none' is rejected: reasoning is mandatory on this model now.
        'max_tokens': 3000,  # Smaller limits truncated JSON replies mid-string.
        'messages': [{'role': 'user', 'content': content}],
        **({'response_format': {'type': 'json_object'}} if json_reply else {}),
    }
    resp = c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=90)
    return (json.loads(resp.read())['choices'][0]['message'].get('content') or '').strip()


def listen_json(clips: list[bytes], question: str) -> dict:
    text = listen(clips, question, json_reply=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {'raw': text[:300]}


def _word_set(text: str) -> set[str]:
    clean = re.sub(r'[\u0300-\u036f\u0591-\u05c7]', '', text.lower().replace('ё', 'е'))
    words = re.findall(r'\w+', clean)
    return {w for w in words if len(w) >= 3} or set(words)


def transcript_matches(spoken_text: str, transcript: str) -> bool:
    """At least 60% of the line's words (3+ letters, accents and niqqud stripped) appear in the transcript."""
    spoken = _word_set(spoken_text)
    return not spoken or len(spoken & _word_set(transcript)) / len(spoken) >= 0.6


# ── Experiment 05: fixed English speech ───────────────────────────────────────────────────────────

def exp05_resources(args) -> None:
    """Read-only map of animation voice cues to base-game audio resources (needs the sims4-workspace package reader)."""
    sys.path.insert(0, r'C:\Users\Max\code\github.com\sims\sims4-workspace')
    from util.datamining.package_reader import PackageReader

    def fnv1_64(name: str) -> int:
        value = 0xCBF29CE484222325
        for byte in name.lower().encode('utf-8'):
            value = ((value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF) ^ byte
        return value

    game = Path(r'C:\Program Files\EA Games\The Sims 4')
    # Match the sound-name/hash example published by the Sound Tool's creator.
    assert fnv1_64('voact_actinggig_havedrinkwith_riskysuccess_x_a1skill_fa') == 0xC1230D4B11426834
    path = game / 'Data/Client/ClientFullBuild1.package'
    package = PackageReader(str(path))
    package.read()
    counts = collections.Counter(entry.key.type_id for entry in package.entries)
    configs = {entry.key.instance: entry for entry in package.entries if entry.key.type_id == 0xFD04E3BE}
    matches = []
    for cue in ['vo_expr_greet_angry_25f', 'vo_expr_greet_uncomfortable_45f', 'vo_expr_greet_bored_40f', 'vo_expr_greet_sad_25f']:
        for voice in ['ma', 'mb', 'mc', 'fa', 'fc', 'fd', 'tma', 'tmb', 'tmc', 'tfa', 'tfc', 'tfd']:
            name = cue + '_' + voice
            entry = configs.get(fnv1_64(name))
            if entry is not None:
                data = package.extract_resource(entry)
                assert len(data) == entry.mem_size
                matches.append({'name': name, 'resource': str(entry.key), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    with wave.open(str(EXP05 / 'audio/fixed-hello.wav')) as clip:
        audio = {'text': 'Oh. Hello.', 'voice': 'Microsoft Zira Desktop - English (United States)',
                 'duration_seconds': round(clip.getnframes() / clip.getframerate(), 3), 'sample_rate': clip.getframerate(),
                 'channels': clip.getnchannels(), 'sample_width_bytes': clip.getsampwidth()}
    result = {
        'experiment': 'Fixed English speech: offline resource mapping and test clip',
        'game_build': '1.128.90.1030',
        'package': str(path.relative_to(game)),
        'resource_counts': {f'{key:08X}': counts[key] for key in [0xFD04E3BE, 0x01A527DB, 0x01EEF63A]},
        'config_matches': matches,
        'english_test_clip': audio,
        'sound_tool': {
            'release': '1.1.29',
            'creator_page': 'https://modthesims.info/d/639090/ts4-sound-tool.html',
            'archive_sha256': '8DF99B31AC5E14A6E81A836BCC775E67B38BBAA2A3371CB8B982BDBEA662C0BF',
            'downloaded': True,
        },
        'limits': [
            'Base resources only; patch and mod overrides have not been resolved.',
            'Cue names were found in base animation clips; no live cue trigger was observed.',
            'No packaged English resource, replacement, selective suppression, or gameplay test yet.',
            'Sound Tool is an offline asset utility, not TTS or a selected runtime dependency.',
        ],
    }
    (EXP05 / 'resource-map.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'audio_config_matches': len(matches), 'test_clip': audio}, indent=2))


# ── Experiment 31: scenes ─────────────────────────────────────────────────────────────────────────

# Real events from her Nov 6 2026 session (events.jsonl), chosen to cover WickedWhims and repetition-prone types.
REAL_EVENTS = {
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
FORCED_LANGUAGE = {  # Otherwise English (production picks Hebrew/Russian 12% of the time at random).
    '19-ww-player-chat-explicit': None,
    '06-karaoke-bar-yuvi-carlos': 'Hebrew (עברית)',
    '20-ww-drama-satisfying-sex': 'Russian (Русский)',
    '31-ww-sex-scene-climax': 'Hebrew (עברית)',
}


def exp31_scenes(args) -> None:
    """Freeze the scene set: the replay set, real Nov 6 events (incl. WickedWhims), and harness sex scenes."""
    SCENES.mkdir(exist_ok=True)
    events = {e['event_id']: e for e in read_jsonl(ROOT / '.local' / 'data' / 'events.jsonl')
              if e.get('event_id') in REAL_EVENTS and 'actor' in e}
    missing = set(REAL_EVENTS) - set(events)
    assert not missing, missing
    scenes = {p.stem: json.loads(p.read_text(encoding='utf-8-sig')) for p in sorted((ROOT / 'experiments' / 'replay-set').glob('*.json'))}
    for eid, name in REAL_EVENTS.items():
        scenes[name] = events[eid]
    # Harness-only sex scenes (the mod didn't emit `sex_scene` yet): reuse the real mid-sex snapshot of gefen + tal.
    base = events['chat-1794038012694-6']
    for name, stage, anim in (
        ('28-ww-sex-scene-start', 'start', {'name': 'Slow Missionary', 'category': 'VAGINAL'}),
        ('29-ww-sex-scene-oral', 'change', {'name': 'Kneeling Blowjob', 'category': 'ORAL'}),
        ('30-ww-sex-scene-doggy', 'change', {'name': 'Doggy Style', 'category': 'VAGINAL'}),
        ('31-ww-sex-scene-climax', 'climax', {'name': 'Doggy Style', 'category': 'CLIMAX'}),
    ):
        ev = copy.deepcopy(base)
        ev.pop('player_message', None)
        ev.update(type='sex_scene', interaction='sex_scene', outcome='SEX', event_id=f'harness-{name}', sex_stage=stage, sex_animation=anim)
        scenes[name] = ev
    for name, ev in scenes.items():
        ev['_language'] = FORCED_LANGUAGE.get(name) or 'English'
        (SCENES / f'{name}.json').write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding='utf-8')
    shutil.copy(ROOT / '.local' / 'data' / 'memories.json', SCENES / 'memories-snapshot.json')
    print(len(scenes), 'scenes written to', SCENES)


# ── Experiment 31: text and session runs ──────────────────────────────────────────────────────────

TEXT_MODELS = [
    'openai/gpt-6-luna', 'openai/gpt-6.1-terra', 'x-ai/grok-4.20', 'x-ai/grok-4.3',
    'deepseek/deepseek-v4.1-flash-1017', 'z-ai/glm-5.2', 'minimax/minimax-m3.1-flash',
    'mistralai/mistral-small-2603', 'google/gemini-omni-1.2-flash',
]
PROMPTS = {**{v: EXP31 / f'prompt-{v}.txt' for v in ('v1', 'v2', 'v3')}, 'prod': ROOT / 'prompt.txt'}
# Grok 4.7 refuses 'none' ("Reasoning is mandatory for this endpoint"), so it runs at its lowest effort; its reasoning
# tokens count against max_tokens, so reasoning models get more room.
REASONING = {'x-ai/grok-4.7': 'minimal'}


def scene_for(event: dict, prompt: str, mem: c.MemoryStore) -> dict:
    actor = str(event['actor'].get('name') or '')
    tname = mem.event_target_name(event)
    scene = c.build_scene(
        event, language=event['_language'], pair_memory=mem.get_memory(actor, tname),
        recent_gossip=mem.get_gossip(actor, tname),
        recent_lines=mem.get_recent_lines(actor, tname) if prompt != 'v1' else None,
    )
    if prompt == 'v1':  # Exactly what production sent before this experiment.
        scene.pop('spicy', None)
    return scene


def chat(model: str, system: str, scene: dict) -> dict:
    """The same chat request companion.generate() sends, with an experiment system prompt."""
    effort = REASONING.get(model, 'none')
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(scene, ensure_ascii=False)},
        ],
        'max_tokens': 320 if effort == 'none' else 2000,
        'reasoning': {'effort': effort},
    }
    return json.loads(c._openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=40).read())


def _text_one(model: str, prompt: str, name: str, event: dict, scene: dict, sample: int, out: Path) -> None:
    row = {'model': model, 'prompt': prompt, 'scene': name, 'sample': sample,
           'spicy': bool(c.is_spicy(event)), 'language': scene['language'], 'event_type': scene['event_type']}
    started = time.monotonic()
    try:
        result = chat(model, PROMPTS[prompt].read_text(encoding='utf-8'), scene)
        row['elapsed_s'] = round(time.monotonic() - started, 3)
        row['raw_text'] = (result['choices'][0]['message'].get('content') or '').strip()
        row['text'] = c._normalize_dialogue_lines(row['raw_text'], event, speaker_count=scene['speaker_count']) if row['raw_text'] else ''
        row['finish_reason'] = result['choices'][0].get('finish_reason')
        row['provider'] = result.get('provider')
        usage = result.get('usage') or {}
        row['cost_usd'] = usage.get('cost')
        row['reasoning_tokens'] = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
    except Exception as exc:  # Record and keep going: one model's 400 shouldn't stop the grid.
        row['elapsed_s'] = round(time.monotonic() - started, 3)
        body = getattr(exc, 'body', None) or (exc.read().decode('utf-8', 'replace') if hasattr(exc, 'read') else '')
        row['error'] = f'{type(exc).__name__}: {exc} {body[:300]}'
    append_jsonl(out, row)
    print(f"{model:36s} {prompt} {name:34s} {row['elapsed_s']:6.2f}s {(row.get('text') or row.get('error') or '')[:90]!r}", flush=True)


def exp31_text(args) -> None:
    """Text bake-off: every model x prompt over the frozen scenes, timed like companion.generate()."""
    c.load_stbl_dictionary()
    mem = c.MemoryStore(SCENES / '_mem')  # Loads scenes/_mem/memories.json (a frozen snapshot).
    scenes = load_scenes()
    if args.scenes:
        scenes = {k: v for k, v in scenes.items() if k.startswith(tuple(args.scenes.split(',')))}
    jobs = [(model, prompt, name, ev, scene_for(ev, prompt, mem), s, args.out)
            for model in args.models.split(',') for prompt in args.prompts.split(',')
            for name, ev in scenes.items() for s in range(args.samples)]
    print(len(jobs), 'calls', flush=True)
    with ThreadPoolExecutor(args.workers) as pool:
        for job in jobs:
            pool.submit(_text_one, *job)


def _session_one(spec: str, passes: int = 3) -> None:
    model, prompt = spec.split(':')
    snap = json.loads((SCENES / '_mem' / 'memories.json').read_text(encoding='utf-8'))
    mem = c.MemoryStore()  # path=None: record() keeps memory in RAM only.
    mem.pairs = copy.deepcopy(snap['pairs'])
    scenes = load_scenes()
    for i in range(passes):
        for name, ev in scenes.items():
            sc = scene_for(ev, prompt, mem)
            t0 = time.monotonic()
            row = {'model': model, 'prompt': prompt, 'pass': i, 'scene': name, 'spicy': c.is_spicy(ev)}
            try:
                raw = (chat(model, PROMPTS[prompt].read_text(encoding='utf-8'), sc)['choices'][0]['message'].get('content') or '').strip()
                row['text'] = c._normalize_dialogue_lines(raw, ev, speaker_count=sc['speaker_count']) if raw else ''
                if row['text']:
                    mem.record(ev, sc, row['text'])
            except Exception as exc:
                row['error'] = str(exc)[:200]
            row['elapsed_s'] = round(time.monotonic() - t0, 3)
            append_jsonl(EXP31 / 'session-results.jsonl', row)
    print('done', spec, flush=True)


def exp31_session(args) -> None:
    """Replay all scenes 3x in order with memory recording, like an evening: repetition only shows across a session."""
    c.load_stbl_dictionary()
    with ThreadPoolExecutor(len(args.specs)) as pool:
        list(pool.map(_session_one, args.specs))


# ── Experiment 31: voice bake-off ─────────────────────────────────────────────────────────────────

TTS_LINES = [  # (id, gender, language, kind, text)
    ('en-clean-f', 'F', 'en', 'clean', 'Kenya, you keep staring at the bread like it owes you money.'),
    ('en-clean-m', 'M', 'en', 'clean', 'I came here for karaoke, not a personality audit.'),
    ('en-player-f', 'F', 'en', 'explicit', 'fuck me daddy im your cumslut'),
    ('en-dirty-m', 'M', 'en', 'explicit', "God, you're so wet. Don't you dare stop."),
    ('en-moan-f', 'F', 'en', 'explicit', 'Mmm, fuck, right there. Harder. Yes, yes!'),
    ('en-crude-m', 'M', 'en', 'explicit', 'Get on your knees and suck my cock.'),
    ('he-dirty-f', 'F', 'he', 'explicit', 'תזיין אותי חזק יותר, אל תעצור עכשיו.'),
    ('he-clean-m', 'M', 'he', 'clean', 'אני לא שיכור, אני פשוט מתלהב מאוד מהסלמון.'),
    ('ru-dirty-f', 'F', 'ru', 'explicit', 'Трахни меня сильнее, я почти кончаю.'),
    ('ru-clean-m', 'M', 'ru', 'clean', 'Ты так доволен, что даже молчание звучит неприлично.'),  # Dropped from the page: nonsense Russian.
    ('ru-karaoke-m', 'M', 'ru', 'clean', 'Слушай, я пришёл на караоке, а не на допрос.'),
]
# model -> (female voice, male voice); None = provider default. The OpenAI chat-audio engines (gpt-audio, gpt-audio-mini)
# were dropped from the harness with their companion code path; their rows stay in tts-results.jsonl.
TTS_MODELS = {
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


def _tts_one(model: str, line: tuple) -> None:
    lid, gender, lang, kind, text = line
    voice = TTS_MODELS[model][0 if gender == 'F' else 1]
    row = {'model': model, 'line': lid, 'language': lang, 'kind': kind, 'voice': voice, 'text': text}
    try:
        gemini = model.startswith('google/')  # Gemini TTS only supports raw 24 kHz PCM.
        data, secs = speak(model, text, voice, 'pcm' if gemini else 'mp3')
        data = wav_bytes(data, 24000) if gemini else data
        row['ttlt_s'] = secs
        ext = audio_ext(data)
        assert ext != 'bin', f'unknown audio format, first bytes {data[:16]!r}'
        path = TTS_AUDIO / f"{model.replace('/', '__')}__{lid}.{ext}"
        path.write_bytes(data)
        row['audio_file'] = path.name
        row['bytes'] = len(data)
        try:
            row['transcript'] = listen([data], 'Transcribe this audio verbatim in its original language. Output only the words spoken. If it is silent, output [silence].')
        except Exception as exc:
            row['transcript_error'] = str(exc)[:200]
            row['transcript'] = ''
        row['matches'] = transcript_matches(text, row['transcript'])
    except Exception as exc:
        row['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
    append_jsonl(EXP31 / 'tts-results.jsonl', row)
    print(f"{model:38s} {lid:12s} {row.get('ttlt_s', '-')!s:>7} match={row.get('matches')} {row.get('error', row.get('transcript', ''))[:70]!r}", flush=True)


def exp31_tts(args) -> None:
    """Voice bake-off: each engine reads the same lines; Gemini transcribes each clip to catch refusals."""
    TTS_AUDIO.mkdir(parents=True, exist_ok=True)
    wanted = args.lines.split(',')
    with ThreadPoolExecutor(args.workers) as pool:
        for model in args.models.split(','):
            for line in (l for l in TTS_LINES if l[0] in wanted):
                pool.submit(_tts_one, model, line)


# ── Experiment 31: analysis ───────────────────────────────────────────────────────────────────────

MOOD_LIST = re.compile(r"\b(I['’]m|I am|She['’]s|He['’]s|You['’]re)\s+\w+,\s+\w+(,| and)")
SOMEHOW = re.compile(r',\s*(and|but)\s+(somehow|still)\b', re.I)


def analyze_text(args) -> None:
    """Per model x prompt: errors, latency, spice, repetition templates, kid-safety -> text-summary.json."""
    rows = read_jsonl(EXP31 / 'text-results.jsonl')
    explicit = re.compile(r'\b(fuck\w*|cum\w*|cock\w*|dick\w*|puss\w*|tits?|clit|wet|hard(er)?|ride|suck\w*|moan\w*|deep(er)?|inch\w*|thrust\w*|naked|ass)\b|mmm+|ahh+|oh god', re.I)
    explicit_he_ru = re.compile(r'(זיין|תזיין|זין|כוס|גומר|רטוב|מצוץ|קשה|трах|кончa|кончаю|член|киска|глубже|сильнее|мокр|стон|ебат)', re.I)
    dodge_re = re.compile(r'\b(blush\w*|review\w*|rating|stars?|critique|furniture|loveseat|overthink|salmon|dinner|plating)\b', re.I)
    kids = ('02-restaurant-joke-olive-kenya', '08-teen-advice-tala-jay')  # A TEEN is present: never sexual.

    def lines_of(text):
        return [l.split(':', 1)[-1].strip() for l in (text or '').splitlines() if l.strip()]

    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r['model'], r['prompt'])].append(r)
    print(f"{'model':36s} {'p':2s} {'n':>3s} {'err':>3s} {'p50':>5s} {'p90':>5s} {'spicyX':>6s} {'dodge':>5s} {'moodL':>5s} {'some':>4s} {'words':>5s} {'kidX':>4s} {'$':>7s}")
    summary = {}
    for (model, prompt), rs in sorted(groups.items()):
        ok = [r for r in rs if not r.get('error') and r.get('text')]
        lat = sorted(r['elapsed_s'] for r in ok)
        p50 = statistics.median(lat) if lat else float('nan')
        p90 = lat[int(0.9 * (len(lat) - 1))] if lat else float('nan')
        spicy = [r for r in ok if r['spicy']]
        spicy_x = sum(1 for r in spicy if explicit.search(r['text']) or explicit_he_ru.search(r['text']))
        dodge = sum(1 for r in spicy if dodge_re.search(r['text']))
        all_lines = [l for r in ok for l in lines_of(r['text'])]
        mood_l = sum(1 for l in all_lines if MOOD_LIST.search(l))
        some = sum(1 for l in all_lines if SOMEHOW.search(l))
        words = statistics.mean(len(l.split()) for l in all_lines) if all_lines else 0
        kid_x = sum(1 for r in ok if r['scene'] in kids and explicit.search(r['text']) and re.search(r'fuck|cock|cum|pussy|suck', r['text'], re.I))
        cost = sum(r.get('cost_usd') or 0 for r in rs)
        s = dict(n=len(rs), err=len(rs) - len(ok), p50=p50, p90=p90, spicy_explicit=f'{spicy_x}/{len(spicy)}', dodge=dodge,
                 mood_list=mood_l, somehow_still=some, lines=len(all_lines), mean_words=round(words, 1), kid_explicit=kid_x, cost=cost)
        summary[f'{model} {prompt}'] = s
        print(f"{model:36s} {prompt:2s} {len(rs):3d} {s['err']:3d} {p50:5.2f} {p90:5.2f} {s['spicy_explicit']:>6s} {dodge:5d} {mood_l:5d} {some:4d} {words:5.1f} {kid_x:4d} {cost:7.4f}")
    errs = collections.Counter((r['model'], r['error'][:120]) for r in rows if r.get('error'))
    if errs:
        print('\nerrors:')
        for (m, e), n in errs.most_common(12):
            print(f'  {n:3d} {m}: {e}')
    print('\ntotal cost $', round(sum(r.get('cost_usd') or 0 for r in rows), 4))
    (EXP31 / 'text-summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    if args.scenes:  # Print every line for the given scene prefixes, for reading.
        for r in sorted(rows, key=lambda r: (r['scene'], r['prompt'], r['model'])):
            if r['scene'].startswith(tuple(args.scenes.split(','))):
                print(f"\n[{r['scene']} {r['prompt']} {r['model']} {r['elapsed_s']}s] {r.get('text') or r.get('error')}")


def analyze_session(args) -> None:
    """Repetition across the simulated evenings: templates, repeated openings, n-gram reuse -> session-summary.json."""
    rows = read_jsonl(EXP31 / 'session-results.jsonl')
    setup_punch = re.compile(r'^[^.!?]{8,}[.!?]\s+\S.*[.!?]$')  # "Setup. Punchline." two-sentence shape
    stop = set('the a an and or but to of in on at for with my your you i me it is are was be this that so just not im i’m you’re it’s'.split())

    def words(s):
        return re.findall(r"[\w’']+", s.lower())

    summary = {}
    print(f"{'model:prompt':40s} {'lines':>5s} {'moodL':>5s} {'some':>4s} {'2sent':>5s} {'open2':>5s} {'tri':>5s}  top repeated words")
    for spec in sorted({f"{r['model']}:{r['prompt']}" for r in rows}):
        rs = [r for r in rows if f"{r['model']}:{r['prompt']}" == spec and r.get('text')]
        lines = [l.split(':', 1)[-1].strip() for r in rs for l in r['text'].splitlines() if l.strip()]
        lines = [l for l in lines if not l.startswith(('Woof', 'Meow'))]
        n = len(lines)
        mood = sum(bool(MOOD_LIST.search(l)) for l in lines)
        some = sum(bool(SOMEHOW.search(l)) for l in lines)
        two = sum(bool(setup_punch.search(l)) for l in lines)
        opens = collections.Counter(' '.join(words(l)[:2]) for l in lines)
        open_rep = sum(v for v in opens.values() if v > 1)
        tri_seen, tri_rep = set(), 0
        for l in lines:
            w = words(l)
            tris = {tuple(w[i:i + 3]) for i in range(len(w) - 2)}
            tri_rep += bool(tris & tri_seen)
            tri_seen |= tris
        content = collections.Counter(w for l in lines for w in set(words(l)) if w not in stop and len(w) > 3)
        top = ', '.join(f'{w}×{k}' for w, k in content.most_common(6))
        summary[spec] = dict(lines=n, mood_list=mood, somehow_still=some, setup_punchline=two,
                             repeated_openings=open_rep, lines_reusing_a_trigram=tri_rep, top_words=content.most_common(10))
        pct = lambda x: f'{100 * x / max(n, 1):4.0f}%'
        print(f'{spec:40s} {n:5d} {pct(mood):>5s} {pct(some):>4s} {pct(two):>5s} {pct(open_rep):>5s} {pct(tri_rep):>5s}  {top}')
    (EXP31 / 'session-summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')


def analyze_tts(args) -> None:
    """Per voice engine: verbatim reads by kind and language, latency -> tts-summary.json."""
    rows = read_jsonl(EXP31 / 'tts-results.jsonl')
    by = collections.defaultdict(list)
    for r in rows:
        by[r['model']].append(r)

    def frac(rs):
        return f"{sum(1 for r in rs if r.get('matches'))}/{len(rs)}"

    print(f"{'model':38s} {'clean':>6s} {'explic':>6s} {'en':>5s} {'he':>5s} {'ru':>5s} {'p50':>5s} {'p90':>5s}  errors")
    summary = {}
    for m, rs in sorted(by.items()):
        lat = sorted(r['ttlt_s'] for r in rs if 'ttlt_s' in r)
        p50 = statistics.median(lat) if lat else float('nan')
        p90 = lat[int(0.9 * (len(lat) - 1))] if lat else float('nan')
        k = {kind: frac([r for r in rs if r['kind'] == kind]) for kind in ('clean', 'explicit')}
        lg = {lang: frac([r for r in rs if r['language'] == lang]) for lang in ('en', 'he', 'ru')}
        errs = collections.Counter(r['error'][:60] for r in rs if r.get('error'))
        summary[m] = dict(**k, **lg, p50=p50, p90=p90, errors=dict(errs))
        print(f"{m:38s} {k['clean']:>6s} {k['explicit']:>6s} {lg['en']:>5s} {lg['he']:>5s} {lg['ru']:>5s} {p50:5.2f} {p90:5.2f}  {dict(errs) if errs else ''}")
    (EXP31 / 'tts-summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')
    mism = [r for r in rows if 'audio_file' in r and not r.get('matches')]
    print(f'\n{len(mism)} audio files whose transcript did not match:')
    for r in mism:
        print(f"  {r['model']:36s} {r['line']:12s} {(r.get('transcript') or r.get('transcript_error') or '')[:80]!r}")


def analyze_ratings(args) -> None:
    """Unblind human-ratings.jsonl with eval/key.json -> ratings-summary.json. Each rater's latest value per item wins;
    "anonymous" is Max (rated before the name field was used)."""
    key = json.loads((EVAL / 'key.json').read_text(encoding='utf-8'))
    tts = read_jsonl(EXP31 / 'tts-results.jsonl')
    auto = json.loads((EXP31 / 'session-summary.json').read_text(encoding='utf-8'))
    raters = {'Mina': 'Mina', 'anonymous': 'Max'}
    latest = {}  # (rater, section, item, candidate, kind) -> value
    for r in read_jsonl(EXP31 / 'human-ratings.jsonl'):
        if r['rater'] in raters:
            latest[(raters[r['rater']], r['section'], r['item'], r['candidate'], r['kind'])] = r['value']
    mean = lambda xs: round(statistics.mean(xs), 2) if xs else None
    line_meta = {r['line']: (r['language'], r['kind']) for r in tts}
    p50 = {m: statistics.median(r['ttlt_s'] for r in tts if r['model'] == m and 'ttlt_s' in r)
           for m in {r['model'] for r in tts if 'ttlt_s' in r}}
    summary = {}

    voice = collections.defaultdict(lambda: collections.defaultdict(list))  # model -> bucket -> stars
    pairs = []  # (Mina, Max) on the same clip, for agreement
    for lid, letters in key['voice'].items():
        lang, kind = line_meta[lid]
        for letter, model in letters.items():
            got = {who: latest.get((who, 'voice', lid, letter, 'stars')) for who in raters.values()}
            for who, v in got.items():
                if v:
                    for bucket in (who, f'{who} {kind}', f'{who} {lang}'):
                        voice[model][bucket].append(v)
            if got['Mina'] and got['Max']:
                pairs.append((got['Mina'], got['Max']))
    summary['voice'] = {m: {'p50_s': round(p50[m], 2), **{b: [mean(v), len(v)] for b, v in sorted(b.items())}} for m, b in voice.items()}
    print("🎧 Voice engines, Mina's mean stars (n) | Max's | latency p50")
    print(f"{'engine':38s} {'Mina':>9s} {'explicit':>9s} {'clean':>9s} {'en':>9s} {'he':>9s} {'ru':>9s} {'Max':>9s} {'p50':>6s}")
    fmt = lambda b, k: f"{mean(b[k]) or '-'!s:>5}({len(b[k])})" if b.get(k) else f"{'-':>9s}"
    for m, b in sorted(voice.items(), key=lambda kv: -(mean(kv[1]['Mina']) or 0)):
        print(f"{m:38s} " + ' '.join(f'{fmt(b, k):>9s}' for k in ('Mina', 'Mina explicit', 'Mina clean', 'Mina en', 'Mina he', 'Mina ru', 'Max'))
              + f" {p50[m]:6.2f}")
    if pairs:
        a, b = zip(*pairs)
        r = statistics.correlation(a, b) if len(pairs) > 2 else float('nan')
        summary['voice_agreement'] = {'clips_both_rated': len(pairs), 'pearson': round(r, 2)}
        print(f"\nMina vs Max on the {len(pairs)} clips both rated: Pearson r = {r:.2f}")

    print("\n🌙 Evenings (16 lines each): variety / fun, 1–5")
    print(f"{'model:prompt':42s} {'Mina var':>8s} {'Mina fun':>8s} {'Max var':>8s} {'Max fun':>8s} {'rep.open':>8s} {'trigram':>8s}")
    summary['session'] = {}
    for sid, spec in sorted(key['session'].items(), key=lambda kv: -(latest.get(('Mina', 'session', kv[0], '*', 'variety')) or 0)
                            - (latest.get(('Mina', 'session', kv[0], '*', 'fun')) or 0) / 10):
        got = {f'{who} {kind}': latest.get((who, 'session', sid, '*', kind)) for who in raters.values() for kind in ('variety', 'fun')}
        a = auto.get(spec, {})
        summary['session'][spec] = {**got, 'repeated_openings': a.get('repeated_openings'), 'lines_reusing_a_trigram': a.get('lines_reusing_a_trigram')}
        print(f"{spec:42s} " + ' '.join(f"{got[k] if got[k] else '-'!s:>8}" for k in got) + f" {a.get('repeated_openings', '-')!s:>8} {a.get('lines_reusing_a_trigram', '-')!s:>8}")

    best, bad, shown, cards = (collections.Counter() for _ in range(4))
    for scene, letters in key['text'].items():
        for who in raters.values():
            pick = latest.get((who, 'text', scene, '*', 'best'))
            if not pick:
                continue
            cards[who] += 1
            for letter, label in letters.items():
                shown[(who, label)] += 1
                bad[(who, label)] += latest.get((who, 'text', scene, letter, 'bad')) == 1
            best[(who, letters[pick])] += 1
    labels = sorted({label for letters in key['text'].values() for label in letters.values()})
    summary['text'] = {who: {label: {'best': best[(who, label)], 'bad': bad[(who, label)], 'cards': shown[(who, label)]} for label in labels}
                       for who in raters.values()}
    print(f"\n💬 Lines (partial: Mina rated {cards['Mina']}/31 cards, Max {cards['Max']}/31): ⭐ best / 👎 bad / cards shown")
    for label in sorted(labels, key=lambda l: -best[('Mina', l)]):
        print(f"{label:18s} Mina {best[('Mina', label)]:>2}⭐ {bad[('Mina', label)]:>2}👎 /{shown[('Mina', label)]:<3} Max {best[('Max', label)]:>2}⭐ {bad[('Max', label)]:>2}👎 /{shown[('Max', label)]}")
    (EXP31 / 'ratings-summary.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')


# ── Experiment 31: blind rating page ──────────────────────────────────────────────────────────────

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
# ru-clean-m was dropped (nonsense Russian); its old ratings stay in human-ratings.jsonl but are ignored.
VOICE_LINES = ['en-clean-f', 'en-moan-f', 'en-dirty-m', 'en-player-f', 'he-dirty-f', 'ru-karaoke-m', 'ru-dirty-f']


def _describe(ev: dict) -> dict:
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


def exp31_eval(args) -> None:
    """Build eval/data.json (blind: candidates are shuffled letters) and eval/key.json (letter -> model)."""
    text_rows = read_jsonl(EXP31 / 'text-results.jsonl')
    session_rows = read_jsonl(EXP31 / 'session-results.jsonl')
    tts_rows = read_jsonl(EXP31 / 'tts-results.jsonl')
    rng = random.Random(31)
    key = {'text': {}, 'voice': {}, 'session': {}}
    data = {'text': [], 'voice': [], 'session': []}
    # Ratings in human-ratings.jsonl point at letters, so a rebuild must keep every letter that already exists.
    old_key = json.loads((EVAL / 'key.json').read_text(encoding='utf-8')) if (EVAL / 'key.json').exists() else {}

    def shuffle_stable(section, item, things, name_of):
        """Shuffle things, unless the old key already fixed this item's order for the same set of things."""
        rng.shuffle(things)  # Always consume the rng, so items without an old order still get the original seed's order.
        old = old_key.get(section, {}).get(item)
        if old and sorted(old.values()) == sorted(name_of(t) for t in things):
            order = list(old.values())
            things.sort(key=lambda t: order.index(name_of(t)))
        return things

    for name, ev in load_scenes().items():
        cands = []
        for label, src, model, prompt in TEXT_CANDIDATES:
            if src == 'text':
                r = next((r for r in text_rows if r['scene'] == name and r['model'] == model and r['prompt'] == prompt), None)
            else:  # Pass 0 of the session simulation is a normal single call with the frozen memory.
                r = next((r for r in session_rows if r['scene'] == name and r['model'] == model and r['prompt'] == prompt and r['pass'] == 0), None)
            if r and r.get('text'):
                cands.append((label, r['text'], r.get('elapsed_s')))
        shuffle_stable('text', name, cands, lambda x: x[0])
        letters = 'ABCDEFGH'
        key['text'][name] = {letters[i]: x[0] for i, x in enumerate(cands)}
        data['text'].append({'id': name, **_describe(ev), 'spicy': c.is_spicy(ev),
                             'candidates': [{'id': letters[i], 'text': x[1]} for i, x in enumerate(cands)]})

    for lid in VOICE_LINES:
        rs = [r for r in tts_rows if r['line'] == lid and r.get('audio_file')]
        shuffle_stable('voice', lid, rs, lambda r: r['model'])
        key['voice'][lid] = {f'V{i + 1}': r['model'] for i, r in enumerate(rs)}
        data['voice'].append({'id': lid, 'text': rs[0]['text'] if rs else '',
                              'clips': [{'id': f'V{i + 1}', 'src': f"audio/{r['audio_file']}"} for i, r in enumerate(rs)]})

    specs = sorted({f"{r['model']}:{r['prompt']}" for r in session_rows})
    rng.shuffle(specs)
    if sorted(old_key.get('session', {}).values()) == sorted(specs):  # The session key is one flat S-id -> spec map.
        specs = list(old_key['session'].values())
    for i, spec in enumerate(specs):
        rs = [r for r in session_rows if f"{r['model']}:{r['prompt']}" == spec and r['pass'] == 1 and r.get('text')][:16]
        key['session'][f'S{i + 1}'] = spec
        data['session'].append({'id': f'S{i + 1}', 'lines': [r['text'] for r in rs]})

    EVAL.mkdir(exist_ok=True)
    (EVAL / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    (EVAL / 'key.json').write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(data['text']), 'scenes,', sum(len(v['clips']) for v in data['voice']), 'clips,', len(data['session']), 'sessions')


class _RatingHandler(SimpleHTTPRequestHandler):
    """index.html with data.json, the saved ratings, and the finished sections' real names inlined and gzipped (one
    round trip instead of three, which roughly halved the load over a slow Funnel relay); the clips; POST /rate."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(EVAL), **kwargs)

    def translate_path(self, path):
        if path.startswith('/audio/'):
            return str(TTS_AUDIO / Path(path[len('/audio/'):]).name)
        return super().translate_path(path)

    def do_GET(self):
        path = urlsplit(self.path).path  # Without the query, so '/key.json?x' can't slip past the check below.
        if path in ('/', '/index.html'):
            rows = read_jsonl(EXP31 / 'human-ratings.jsonl')
            data = json.loads((EVAL / 'data.json').read_text(encoding='utf-8'))
            key = json.loads((EVAL / 'key.json').read_text(encoding='utf-8'))
            names = {'voice': key['voice'], 'session': key['session']}  # Both rated in full; Lines stays blind until she finishes it.
            inline = json.dumps({'data': data, 'ratings': rows, 'names': names}, ensure_ascii=False).replace('</', '<\\/')  # A line can't close the <script>.
            # Every browser sends Accept-Encoding: gzip, so always compress; the JSON shrinks about 4x.
            body = gzip.compress((EVAL / 'index.html').read_text(encoding='utf-8').replace('__INLINE__', inline).encode('utf-8'))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')  # A reload must show the latest saved ratings.
            self.end_headers()
            self.wfile.write(body)
            return
        if path.endswith('key.json'):
            self.send_error(404)  # Keep it blind.
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/rate':
            self.send_error(404)
            return
        row = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        row['ts'] = time.time()
        with (EXP31 / 'human-ratings.jsonl').open('a', encoding='utf-8', newline='\n') as f:  # LF; Windows text mode would write CRLF.
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.send_response(204)
        self.end_headers()


def exp31_serve(args) -> None:
    """Serve the rating page on localhost only. The clips and lines come from her real save and are explicit. To let her
    rate from her house: `tailscale funnel --bg --set-path /rate-sims-banter 8731`, and `tailscale funnel reset` afterwards."""
    print('http://localhost:8731', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8731), _RatingHandler).serve_forever()


# ── Experiment 31: probes ─────────────────────────────────────────────────────────────────────────

def probe_formats(args) -> None:
    """Which TTS engines return WAV or raw PCM (the companion has no MP3 decoder), and at what rate? -> format-probe.json."""
    engines = {
        'x-ai/grok-voice-tts-1.0': 'eve', 'elevenlabs/eleven-v4-turbo': 'sarah', 'minimax/speech-2.8-turbo': 'English_radiant_girl',
        'fish-audio/drama-3': None, 'fish-audio/s2.1-pro': None, 'google/gemini-3.8-flash-lite-tts': 'Aoede',
    }
    results = {}
    for model, voice in engines.items():
        for fmt in ('wav', 'pcm'):
            try:
                data, secs = speak(model, 'Mmm, fuck, right there. Harder. Yes, yes!', voice, fmt)
                info = {'bytes': len(data), 'head': data[:4].hex(), 's': secs}
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
    (EXP31 / 'format-probe.json').write_text(json.dumps(results, indent=1), encoding='utf-8')


def probe_drama_voices(args) -> None:
    """Can drama-3 give each Sim its own voice? Gemini judges the bake-off clips (no voice set) and new clips with bracket
    directions and a voice id: speaker gender, and whether a direction was read aloud -> drama-voice-probe.jsonl."""
    male, female = "God, you're so wet. Don't you dare stop.", 'Kenya, you keep staring at the bread like it owes you money.'
    probes = [  # (id, text, voice)
        ('m-plain', male, None),
        ('f-plain', female, None),
        ('m-dir-deep-male', '[deep male voice, breathless] ' + male, None),
        ('f-dir-deep-male', '[deep male voice, deadpan] ' + female, None),
        ('m-dir-young-woman', '[young woman, teasing] ' + male, None),
        ('m-dir-old-man', '[gravelly old man, grumpy] ' + male, None),
        ('f-voice-example-id', female, '9a9cf47702da476aa4629e2506d4a857'),  # The example id in Fish's OpenRouter migration doc.
    ]
    question = ('Listen to this clip. Reply with JSON only: {"transcript": verbatim words spoken, '
                '"gender": "male"|"female"|"unclear", "age": "child"|"young adult"|"adult"|"elderly", "tone": a few words}.')

    def existing(path: Path) -> dict:
        return {'probe': 'bakeoff:' + path.stem.split('__')[-1], **listen_json([path.read_bytes()], question)}

    def new(probe) -> dict:
        pid, text, voice = probe
        try:
            data, secs = speak('fish-audio/drama-3', text, voice)
        except Exception as exc:
            return {'probe': pid, 'input': text, 'voice': voice, 'error': str(exc)[:200]}
        (TTS_AUDIO / f'probe-{pid}.mp3').write_bytes(data)
        return {'probe': pid, 'input': text, 'voice': voice, 'ttlt_s': secs, **listen_json([data], question)}

    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(existing, sorted(TTS_AUDIO.glob('fish-audio__drama-3__*.mp3')))) + list(pool.map(new, probes))
    with (EXP31 / 'drama-voice-probe.jsonl').open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
            print(f"{r['probe']:24s} {r.get('gender', '-'):7s} {r.get('age', '-'):12s} {r.get('ttlt_s', '')!s:>5} "
                  f"{r.get('error') or r.get('transcript', '')[:70]!r}  [{r.get('tone', '')}]")


def probe_drama_consistency(args) -> None:
    """Does drama-3 keep one voice across lines? A voice id vs a fixed bracket direction, three lines each, judged together;
    plus the sample rate of response_format=pcm (from the MP3's duration) -> drama-consistency-probe.json."""
    lines = [
        '[annoyed] I told you the toaster is not a phone charger.',
        '[flirty, breathless] Come here. No, closer than that.',
        '[sad, quiet] I just thought tonight would be different.',
    ]
    sets = {  # set -> (voice id or None, prefix added before each line's own direction)
        'voice-sarah': ('933563129e564b19a115bedd57b7406a', ''),
        'voice-adrian': ('bf322df2096a46f18c579d0baa36f41d', ''),
        'direction-man': (None, '[warm low-voiced man in his 30s] '),
        'direction-woman': (None, '[bright young woman with a raspy laugh] '),
    }
    out = {}
    for name, (voice, prefix) in sets.items():
        clips, secs = [], []
        for i, line in enumerate(lines):
            data, s = speak('fish-audio/drama-3', prefix + line, voice)
            (TTS_AUDIO / f'consistency-{name}-{i}.mp3').write_bytes(data)
            clips.append(data)
            secs.append(s)
        verdict = listen(clips, 'These three clips are lines from a video game character. Answer in 3 short lines: '
                                '1) SAME or DIFFERENT speaker across all three (judge voice timbre, not emotion), with confidence; '
                                '2) gender and rough age of each; 3) the emotion of each clip, and whether any bracketed stage direction was read aloud.')
        out[name] = {'voice': voice, 'prefix': prefix, 'ttlt_s': secs, 'verdict': verdict}
        print(f'=== {name} {secs}\n{verdict}\n', flush=True)
    # PCM byte length vs the MP3's duration (ffprobe), assuming 16-bit mono. Two separate generations differ in length,
    # so this estimate is rough: the response header said 44.1 kHz, which a listening test confirmed.
    text = '[calm] One two three four five six seven eight nine ten.'
    mp3, _ = speak('fish-audio/drama-3', text)
    pcm, _ = speak('fish-audio/drama-3', text, fmt='pcm')
    (TTS_AUDIO / 'pcm-probe.mp3').write_bytes(mp3)
    dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(TTS_AUDIO / 'pcm-probe.mp3')],
                               capture_output=True, text=True).stdout.strip())
    out['pcm'] = {'pcm_bytes': len(pcm), 'mp3_duration_s': dur, 'implied_rate_16bit_mono': round(len(pcm) / 2 / dur), 'first_bytes': pcm[:8].hex()}
    print('pcm:', out['pcm'])
    (EXP31 / 'drama-consistency-probe.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')


DRAMA_CAST = {  # group -> {name: Fish voice id}; companion.py's voice pools come from this audition.
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
CAST_LINES = [
    '[amused] You keep staring at the bread like it owes you money.',
    '[annoyed] אני לא שיכור, אני פשוט מתלהב מאוד מהסלמון.',
    '[annoyed] Слушай, я пришёл на караоке, а не на допрос.',
]


def probe_drama_cast(args) -> None:
    """Audition drama-3 library voices: English, Hebrew, and Russian lines each (16-bit 44.1 kHz PCM), judged together
    for gender, age, naturalness, and verbatim reads -> drama-cast-probe.jsonl."""
    def audition(item):
        group, name, vid = item
        clips = [wav_bytes(speak('fish-audio/drama-3', line, vid, 'pcm')[0], 44100) for line in CAST_LINES]
        v = listen_json(clips, (
            'Three clips of one game character: English, Hebrew, Russian. Reply in JSON only: {"same_speaker": true|false, '
            '"gender": "male"|"female"|"unclear", "age": "child"|"teen"|"young adult"|"adult"|"elderly", '
            '"natural": true|false, "quality_note": "few words", "transcripts": [three verbatim transcripts]}'))
        tr = v.get('transcripts') or ['', '', '']
        v['verbatim'] = [transcript_matches(l.split('] ', 1)[1], t) for l, t in zip(CAST_LINES, tr)]
        return {'group': group, 'name': name, 'voice': vid, **v}

    items = [(g, n, vid) for g, voices in DRAMA_CAST.items() for n, vid in voices.items()]
    with ThreadPoolExecutor(6) as pool:
        rows = list(pool.map(audition, items))
    with (EXP31 / 'drama-cast-probe.jsonl').open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
            print(f"{r['group']:6s} {r['name']:21s} same={r.get('same_speaker')!s:5} {r.get('gender', '?'):7s} {r.get('age', '?'):11s} "
                  f"natural={r.get('natural')!s:5} en/he/ru={r['verbatim']}  {r.get('quality_note', r.get('raw', ''))}")


# ── Experiment 32: Grok 4.7, voice moods, and repeats, on captured game data ──────────────────────

EXP32 = ROOT / 'experiments' / '32-grok-4.7-voice-moods-and-repeats'
SEQUENCES = {  # Frozen from real play: her whole Nov 6 evening, and the Nov 12 play-test's 8 WickedWhims events.
    'nov6': EXP32 / 'scenes' / 'nov6-evening.json',
    'sex': EXP32 / 'scenes' / 'playtest-sex-sequence.json',
}
VARIANTS = {  # Appended to the production prompt.
    'prod': '',
    'change-rule': (
        '\nSex scene changes: on `sex_stage: "change"`, react to the new position itself (what its `name` says the bodies are '
        'doing, the angle, the pace), not to the act of switching. Never say switch, change, flip, or again, and never reuse '
        'an opening or a phrase from `pair_memory`.\n'),
    'repeat-hint': (
        '\nRepeats: `repeat_count` is how many times these two Sims already did this same interaction recently. When it is '
        'present, the moment is a rerun: play off the repetition, or take a clearly different angle; never restate an idea '
        'from `pair_memory`.\n'),
}


def _repeat_count(mem: c.MemoryStore, actor: str, target: str | None, scene: dict) -> int:
    label = scene.get('interaction_label') or scene.get('interaction')
    return sum(1 for e in mem.pairs.get(mem.make_key(actor, target), []) if e.get('interaction') == label)


def _sequence(seq: str, model: str, variant: str, rep: int) -> None:
    """Replay one frozen sequence in order with a fresh in-RAM memory, recording each reply like production."""
    mem = c.MemoryStore()
    system = PROMPTS['prod'].read_text(encoding='utf-8') + VARIANTS[variant]
    for i, ev in enumerate(json.loads(SEQUENCES[seq].read_text(encoding='utf-8'))):
        actor, target = str(ev['actor'].get('name') or ''), mem.event_target_name(ev)
        scene = c.build_scene(ev, language='English',  # Fixed for comparable runs; production picks Hebrew/Russian 12% at random.
                              pair_memory=mem.get_memory(actor, target), recent_gossip=mem.get_gossip(actor, target),
                              recent_lines=mem.get_recent_lines(actor, target))
        if variant == 'repeat-hint' and (n := _repeat_count(mem, actor, target, scene)):
            scene['repeat_count'] = n
        row = {'seq': seq, 'model': model, 'variant': variant, 'rep': rep, 'i': i, 'event_type': scene['event_type'],
               'interaction': scene.get('interaction_label') or scene.get('interaction'), 'repeat_count': scene.get('repeat_count'),
               'sex': (ev.get('sex_stage'), (ev.get('sex_animation') or {}).get('name'), ev.get('sex_roles')) if ev.get('sex_stage') else None}
        t0 = time.monotonic()
        try:
            result = chat(model, system, scene)
            row['elapsed_s'] = round(time.monotonic() - t0, 3)
            raw = (result['choices'][0]['message'].get('content') or '').strip()
            row['text'] = c._normalize_dialogue_lines(raw, ev, speaker_count=scene['speaker_count']) if raw else ''
            row['reasoning_tokens'] = ((result.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
            if row['text']:
                mem.record(ev, scene, row['text'])
        except Exception as exc:
            row['elapsed_s'] = round(time.monotonic() - t0, 3)
            row['error'] = str(exc)[:300]
        append_jsonl(EXP32 / f'{seq}-results.jsonl', row)
    print('done', seq, model, variant, rep, flush=True)


def exp32_replay(args) -> None:
    """Replay a frozen real sequence (her Nov 6 evening, or the play-test's sex events) per model x variant x rep."""
    c.load_stbl_dictionary()
    jobs = [(args.seq, m, v, r) for m in args.models.split(',') for v in args.variants.split(',') for r in range(args.reps)]
    with ThreadPoolExecutor(len(jobs)) as pool:
        list(pool.map(lambda j: _sequence(*j), jobs))


def _words(s: str) -> list[str]:
    return re.findall(r"[\w’']+", s.lower())


def exp32_analyze(args) -> None:
    """Per model x variant: latency, errors, and within-run repetition (openings, trigram reuse, switch words, host reruns)."""
    switch = re.compile(r'\b(switch\w*|chang\w*|flip\w*|again|already)\b', re.I)
    explicit = re.compile(r'\b(fuck\w*|cum\w*|cock\w*|dick\w*|puss\w*|tits?|clit|wet|suck\w*|moan\w*|deep(er)?|thrust\w*|naked|ass)\b', re.I)
    for seq in ('nov6', 'sex'):
        rows = read_jsonl(EXP32 / f'{seq}-results.jsonl')
        if not rows:
            continue
        print(f'\n=== {seq}: {len(rows)} replies')
        print(f"{'model':16s} {'variant':12s} {'runs':>4s} {'err':>3s} {'p50':>5s} {'p90':>5s} {'open2':>6s} {'tri':>6s} {'switch':>6s} {'explX':>6s} {'words':>5s}")
        for model, variant in sorted({(r['model'], r['variant']) for r in rows}):
            rs = [r for r in rows if r['model'] == model and r['variant'] == variant]
            ok = [r for r in rs if r.get('text')]
            lat = sorted(r['elapsed_s'] for r in ok)
            opens = tris = sw = expl = n = 0
            words = []
            for rep in sorted({r['rep'] for r in rs}):
                lines = [l.split(':', 1)[-1].strip() for r in sorted((r for r in ok if r['rep'] == rep), key=lambda r: r['i'])
                         for l in r['text'].splitlines() if l.strip()]
                seen_open, seen_tri = collections.Counter(), set()
                for l in lines:
                    w = _words(l)
                    seen_open[' '.join(w[:2])] += 1
                    t = {tuple(w[j:j + 3]) for j in range(len(w) - 2)}
                    tris += bool(t & seen_tri)
                    seen_tri |= t
                    sw += bool(switch.search(l))
                    expl += bool(explicit.search(l))
                    words.append(len(w))
                opens += sum(v - 1 for v in seen_open.values() if v > 1)
                n += len(lines)
            pct = lambda x: f'{100 * x / max(n, 1):5.0f}%'
            print(f"{model.split('/')[-1]:16s} {variant:12s} {len({r['rep'] for r in rs}):4d} {len(rs) - len(ok):3d} "
                  f"{statistics.median(lat):5.2f} {lat[int(0.9 * (len(lat) - 1))]:5.2f} {pct(opens):>6s} {pct(tris):>6s} {pct(sw):>6s} {pct(expl):>6s} "
                  f"{statistics.mean(words) if words else 0:5.1f}")
        if args.show:
            for r in sorted(rows, key=lambda r: (r['model'], r['variant'], r['rep'], r['i'])):
                if r['rep'] == 0:
                    tag = f"{r['sex'][0]} {r['sex'][1]}" if r.get('sex') else (r.get('interaction') or '')
                    print(f"  [{r['model'].split('/')[-1]} {r['variant']} #{r['i']} {tag}{' x' + str(r['repeat_count']) if r.get('repeat_count') else ''}] "
                          f"{(r.get('text') or r.get('error') or '').replace(chr(10), ' | ')}")


# Proposed delivery directions for the moods MOOD_TO_DELIVERY_TONE lacks; the most common ones in her play.
NEW_MOOD_TONES = {
    'Fine': 'relaxed, conversational, easygoing',
    'Happy': 'bright, cheerful, warm',
    'Tense': 'tight, clipped, on edge',
    'Sex': 'breathless, aroused, moaning between words',  # TURBODRIVER:WickedWhims_Mood_Sex
}


def exp32_voice_moods(args) -> None:
    """Generic direction vs a mood-specific one on real lines: same drama-3 voice, Gemini picks the better fit blind."""
    lines = [  # (speaker gender, mood, situation, line) from the Nov 12 play-test and her Nov 6 evening.
        ('F', 'Sex', 'mid-sex, oral', 'Yes, right there, lick me deeper.'),
        ('M', 'Sex', 'mid-sex, oral', 'Mmm, you taste so fucking good already.'),
        ('F', 'Sex', 'mid-sex, spanking', 'Harder, smack it like you mean it.'),
        ('M', 'Sex', 'mid-sex, missionary', 'Hold on tight, taking you harder now.'),
        ('F', 'Happy', 'after a kiss in the rain', "That kiss was smoother than this rain. Your turn to impress me."),
        ('M', 'Happy', 'flirting at a restaurant', 'Good. I was hoping your eyes had excellent taste.'),
        ('F', 'Happy', 'pitching a business idea', "Brilliant idea: let's make bubble tea our business expense."),
        ('F', 'Fine', 'asking the host for a table', 'Could we get a specific table, preferably one with dessert nearby?'),
        ('M', 'Fine', 'restaurant host seating her', "Certainly. I'll find you a table worthy of your standards."),
        ('M', 'Fine', 'chatting about cooking', 'Same here, though my family calls it stealing dinner.'),
    ]
    voices = {'F': c.FEMALE_VOICES['Selene'], 'M': c.MALE_VOICES['Slax']}  # The voices the play-test Sims got.
    generic = 'natural, expressive, playful'  # What all of these got before: no entry for Fine, Happy, or WickedWhims' Sex.
    rng = random.Random(32)
    out = []
    for i, (g, mood, situation, line) in enumerate(lines):
        a, _ = speak('fish-audio/drama-3', f'[{generic}] {line}', voices[g], 'pcm')
        b, _ = speak('fish-audio/drama-3', f'[{NEW_MOOD_TONES[mood]}] {line}', voices[g], 'pcm')
        a, b = wav_bytes(a, 44100), wav_bytes(b, 44100)
        (TTS_AUDIO / f'mood-{i}-generic.wav').write_bytes(a)
        (TTS_AUDIO / f'mood-{i}-mood.wav').write_bytes(b)
        first_is_mood = rng.random() < 0.5
        clips = [b, a] if first_is_mood else [a, b]
        v = listen_json(clips, (
            f'Two deliveries of the same video game line by the same voice. Context: the speaker feels "{mood if mood != "Sex" else "aroused"}", '
            f'situation: {situation}. Line: "{line}". Reply in JSON only: {{"better": 1|2, "fit_1": 1-5, "fit_2": 1-5, "why": "few words"}}, '
            'judging which delivery fits the feeling and situation better.'))
        mood_won = v.get('better') == (1 if first_is_mood else 2)
        fits = (v.get('fit_1'), v.get('fit_2')) if first_is_mood else (v.get('fit_2'), v.get('fit_1'))
        row = {'i': i, 'mood': mood, 'line': line, 'mood_direction_won': mood_won, 'fit_mood': fits[0], 'fit_generic': fits[1], 'why': v.get('why')}
        out.append(row)
        print(f"{mood:5s} mood-won={mood_won!s:5s} fit mood/generic={fits[0]}/{fits[1]}  {line[:50]!r}  ({v.get('why')})", flush=True)
    with (EXP32 / 'voice-moods.jsonl').open('w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"\nmood direction won {sum(r['mood_direction_won'] for r in out)}/{len(out)}")


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    experiments = parser.add_subparsers(dest='experiment', required=True)

    exp05 = experiments.add_parser('exp05', help='Fixed English speech').add_subparsers(dest='command', required=True)
    exp05.add_parser('resources', help=exp05_resources.__doc__).set_defaults(run=exp05_resources)

    exp31 = experiments.add_parser('exp31', help='Variety, spice, model, and voice bake-off').add_subparsers(dest='command', required=True)
    exp31.add_parser('scenes', help=exp31_scenes.__doc__).set_defaults(run=exp31_scenes)
    text = exp31.add_parser('text', help=exp31_text.__doc__)
    text.add_argument('--models', default=','.join(TEXT_MODELS))
    text.add_argument('--prompts', default='v1,v2')
    text.add_argument('--samples', type=int, default=1)
    text.add_argument('--scenes', default='', help='comma-separated scene-name prefixes')
    text.add_argument('--workers', type=int, default=6)
    text.set_defaults(run=exp31_text, out=EXP31 / 'text-results.jsonl')
    session = exp31.add_parser('session', help=exp31_session.__doc__)
    session.add_argument('specs', nargs='+', metavar='MODEL:PROMPT')
    session.set_defaults(run=exp31_session)
    tts = exp31.add_parser('tts', help=exp31_tts.__doc__)
    tts.add_argument('--models', default=','.join(TTS_MODELS))
    tts.add_argument('--lines', default=','.join(l[0] for l in TTS_LINES))
    tts.add_argument('--workers', type=int, default=4)
    tts.set_defaults(run=exp31_tts)
    analyze = exp31.add_parser('analyze', help='summarize a results file').add_subparsers(dest='what', required=True)
    analyze_text_p = analyze.add_parser('text', help=analyze_text.__doc__)
    analyze_text_p.add_argument('scenes', nargs='?', default='', help='also print every line for these comma-separated scene prefixes')
    analyze_text_p.set_defaults(run=analyze_text)
    analyze.add_parser('session', help=analyze_session.__doc__).set_defaults(run=analyze_session)
    analyze.add_parser('tts', help=analyze_tts.__doc__).set_defaults(run=analyze_tts)
    analyze.add_parser('ratings', help=analyze_ratings.__doc__).set_defaults(run=analyze_ratings)
    exp31.add_parser('eval', help=exp31_eval.__doc__).set_defaults(run=exp31_eval)
    exp31.add_parser('serve', help=exp31_serve.__doc__).set_defaults(run=exp31_serve)
    probe = exp31.add_parser('probe', help='one-off voice engine probes').add_subparsers(dest='what', required=True)
    probe.add_parser('formats', help=probe_formats.__doc__).set_defaults(run=probe_formats)
    probe.add_parser('drama-voices', help=probe_drama_voices.__doc__).set_defaults(run=probe_drama_voices)
    probe.add_parser('drama-consistency', help=probe_drama_consistency.__doc__).set_defaults(run=probe_drama_consistency)
    probe.add_parser('drama-cast', help=probe_drama_cast.__doc__).set_defaults(run=probe_drama_cast)

    exp32 = experiments.add_parser('exp32', help='Grok 4.7, voice moods, and repeats on captured game data').add_subparsers(dest='command', required=True)
    text32 = exp32.add_parser('text', help='exp31 text bake-off on the 31 frozen scenes, production prompt -> exp32 text-results.jsonl')
    text32.add_argument('--models', default='x-ai/grok-4.20,x-ai/grok-4.7')
    text32.add_argument('--prompts', default='prod')
    text32.add_argument('--samples', type=int, default=1)
    text32.add_argument('--scenes', default='')
    text32.add_argument('--workers', type=int, default=6)
    text32.set_defaults(run=exp31_text, out=EXP32 / 'text-results.jsonl')
    replay = exp32.add_parser('replay', help=exp32_replay.__doc__)
    replay.add_argument('seq', choices=sorted(SEQUENCES))
    replay.add_argument('--models', default='x-ai/grok-4.20,x-ai/grok-4.7')
    replay.add_argument('--variants', default='prod')
    replay.add_argument('--reps', type=int, default=2)
    replay.set_defaults(run=exp32_replay)
    analyze32 = exp32.add_parser('analyze', help=exp32_analyze.__doc__)
    analyze32.add_argument('--show', action='store_true', help='print every line of rep 0')
    analyze32.set_defaults(run=exp32_analyze)
    exp32.add_parser('voice-moods', help=exp32_voice_moods.__doc__).set_defaults(run=exp32_voice_moods)

    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
