"""Generate banter and realistic AI voices outside the game's legacy Python 3.7 thread.

The game mod starts this process (`--data-directory`, `--parent-pid`); it exits when the game exits.
It tails the game's events.jsonl, writes reply.json, synthesizes trilingual (English / Hebrew / Russian)
speech with openai/gpt-audio-mini, and plays it when the game logs `displayed`.
`--once scene.json` generates text for one captured event (for offline prompt experiments).
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import ctypes
import json
import msvcrt
import os
from pathlib import Path
import random
import re
import struct
import time
import urllib.error
import urllib.request
import wave
import winsound
import zlib


ROOT = Path(__file__).resolve().parent
DEFAULT_GAME_DIR = Path(r'C:\Program Files\EA Games\The Sims 4')
DEFAULT_MODS_DIR = Path(r'C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4\Mods')
STBL_CACHE_PATH = ROOT / '.local' / 'stbl_en_us.json'
TTS_DIR = ROOT / '.local' / 'tts'
LOCK_PATH = ROOT / '.local' / 'companion.lock'
# Capped ($50) key dedicated to this project, so the key's own usage is the project's total cost.
OPENROUTER_API_KEY = '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'
CHAT_MODEL = 'openai/gpt-6-luna'
REASONING_EFFORT = 'none'
TTS_MODEL = 'openai/gpt-audio-mini'
FALLBACK_TTS_MODEL = 'google/gemini-3.8-flash-lite-tts'
MULTILINGUAL_CHANCE = 0.12

_stbl_cache: dict[int, str] | None = None
_sim_voice_assignments: dict[str, str] = {}

FEMALE_OPENROUTER_VOICES = ('coral', 'nova', 'shimmer', 'sage', 'ballad', 'alloy')
MALE_OPENROUTER_VOICES = ('ash', 'echo', 'onyx', 'verse', 'fable')
GEMINI_VOICE_MAP = {
    'coral': 'Kore', 'nova': 'Aoede', 'shimmer': 'Leda', 'sage': 'Zephyr', 'ballad': 'Aoede', 'alloy': 'Kore',
    'ash': 'Puck', 'echo': 'Fenrir', 'onyx': 'Charon', 'verse': 'Orus', 'fable': 'Puck',
}

def _refpack_decompress(data: bytes) -> bytes:
    pos = 0
    if data[0] not in (0x10, 0x50, 0x90, 0xD0) or data[1] != 0xFB:
        pos = 4
    flags = data[pos]
    pos += 2
    size_len = 4 if (flags & 0x80) else 3
    if flags & 0x01:
        pos += size_len
    for _ in range(size_len):
        pos += 1
    out = bytearray()
    while pos < len(data):
        b0 = data[pos]
        pos += 1
        if not (b0 & 0x80):
            b1 = data[pos]
            pos += 1
            proc = b0 & 0x03
            out.extend(data[pos:pos + proc])
            pos += proc
            offset = ((b0 & 0x60) << 3) + b1 + 1
            count = ((b0 & 0x1C) >> 2) + 3
            for _ in range(count):
                out.append(out[-offset])
        elif not (b0 & 0x40):
            b1 = data[pos]
            b2 = data[pos + 1]
            pos += 2
            proc = b1 >> 6
            out.extend(data[pos:pos + proc])
            pos += proc
            offset = ((b1 & 0x3F) << 8) + b2 + 1
            count = (b0 & 0x3F) + 4
            for _ in range(count):
                out.append(out[-offset])
        elif not (b0 & 0x20):
            b1 = data[pos]
            b2 = data[pos + 1]
            b3 = data[pos + 2]
            pos += 3
            proc = b0 & 0x03
            out.extend(data[pos:pos + proc])
            pos += proc
            offset = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
            count = ((b0 & 0x0C) << 6) + b3 + 5
            for _ in range(count):
                out.append(out[-offset])
        else:
            proc = ((b0 & 0x1F) + 1) << 2
            if proc <= 0x70:
                out.extend(data[pos:pos + proc])
                pos += proc
            else:
                proc = b0 & 0x03
                out.extend(data[pos:pos + proc])
                break
    return bytes(out)


def _read_package_stbls(pkg_path: Path) -> dict[int, str]:
    data = pkg_path.read_bytes()
    if data[:4] != b'DBPF':
        return {}
    index_count = struct.unpack_from('<I', data, 36)[0]
    index_offset = struct.unpack_from('<I', data, 64)[0] or struct.unpack_from('<I', data, 40)[0]
    pos = index_offset
    flags = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    const_type = None
    if flags & 1:
        const_type = struct.unpack_from('<I', data, pos)[0]
        pos += 4
    if flags & 2:
        pos += 4
    if flags & 4:
        pos += 4
    if flags & 8:
        pos += 4
    out: dict[int, str] = {}
    for _ in range(index_count):
        rtype = const_type if (flags & 1) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 1):
            pos += 4
        if not (flags & 2):
            pos += 4
        if not (flags & 4):
            pos += 4
        if not (flags & 8):
            pos += 4
        offset, size_raw, mem_size, comp_type = struct.unpack_from('<IIIH', data, pos)
        pos += 16
        size = size_raw & 0x7FFFFFFF
        if rtype != 0x220557DA:
            continue
        chunk = data[offset:offset + size]
        if comp_type and size != mem_size:
            if (len(chunk) >= 2 and chunk[0] in (0x10, 0x50) and chunk[1] == 0xFB) or (
                len(chunk) >= 6 and chunk[4] in (0x10, 0x50) and chunk[5] == 0xFB
            ):
                chunk = _refpack_decompress(chunk)
            else:
                chunk = zlib.decompress(chunk)
        if chunk[:4] != b'STBL':
            continue
        _, _, num_entries, _, _ = struct.unpack_from('<HBQHI', chunk, 4)
        spos = 21
        for _ in range(num_entries):
            k, _, slen = struct.unpack_from('<IBH', chunk, spos)
            spos += 7
            out[k] = chunk[spos:spos + slen].decode('utf-8', errors='replace')
            spos += slen
    return out


def load_stbl_dictionary(game_dir: Path = DEFAULT_GAME_DIR) -> dict[int, str]:
    global _stbl_cache
    if _stbl_cache is not None:
        return _stbl_cache
    if STBL_CACHE_PATH.exists():
        _stbl_cache = {
            int(k): v
            for k, v in json.loads(STBL_CACHE_PATH.read_text(encoding='utf-8')).items()
        }
        return _stbl_cache
    strings: dict[int, str] = {}
    if game_dir.exists():
        for pkg in sorted(game_dir.rglob('Strings_ENG_US.package')):
            strings.update(_read_package_stbls(pkg))
    if DEFAULT_MODS_DIR.exists():
        for pkg in sorted(DEFAULT_MODS_DIR.rglob('*.package')):
            try:
                strings.update(_read_package_stbls(pkg))
            except Exception:
                pass
    if strings:
        STBL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STBL_CACHE_PATH.write_text(json.dumps(strings, ensure_ascii=False), encoding='utf-8')
    _stbl_cache = strings
    return _stbl_cache


def resolve_stbl(string_id: int | None, actor: dict | None = None, target: dict | None = None) -> str | None:
    if not isinstance(string_id, int) or not string_id:
        return None
    raw = load_stbl_dictionary().get(string_id)
    if not raw:
        return None
    text = raw
    for idx, sim in (('0', actor), ('1', target)):
        if not sim:
            continue
        first_name = sim.get('name', '').split()[0] if sim.get('name') else ''
        full_name = sim.get('name', '')
        is_female = str(sim.get('gender', '')).upper() == 'FEMALE'
        text = text.replace('{' + idx + '.SimFirstName}', first_name)
        text = text.replace('{' + idx + '.SimName}', full_name)
        text = re.sub(
            r'\{M' + idx + r'\.([^{}]*)\}\{F' + idx + r'\.([^{}]*)\}',
            lambda m, fem=is_female: m.group(2 if fem else 1),
            text,
        )
        text = re.sub(
            r'\{F' + idx + r'\.([^{}]*)\}\{M' + idx + r'\.([^{}]*)\}',
            lambda m, fem=is_female: m.group(1 if fem else 2),
            text,
        )
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\{[^{}]*\}', '', text)
    text = ' '.join(text.split()).strip()
    if not text or '(should not be seen)' in text.lower():
        return None
    return text


_NOISY_REL_BIT_SUBSTRINGS = (
    'has_met', 'specialbits_greeted', 'suppresschangebehavior',
    'neutralto_target', 'neutralwith_target', 'nudity_reactioncooldown',
    'recentlyhadsocialinteraction', 'persistent_boredom_reset',
    'infant_checkon', 'socialcontext_retail_uninterested',
    'relbit_socialcontext_', 'shortterm_recentnegativesocial',
    'pettopet_relationshipbit_neutral', 'simtopet_relationshipbit_02_acquaintance',
    'relationshipbit_simtosim', 'friendship-acquaintances', 'romanticcombo_acquaintances',
)


_SPECIES_NAMES = {'1': 'HUMAN', '2': 'DOG', '3': 'CAT', '4': 'SMALLDOG', '5': 'FOX', '6': 'HORSE'}

_NOISY_TRAIT_SUBSTRINGS = (
    'genderoptions', 'walkstyle', 'handedness', 'occult_nooccult', 'species_',
    'speciesextended_', 'umbrella', 'pregnan', 'lactat', 'toilet', 'clothing', 'frame_',
    'attractedto', 'woohoointerests', 'hasdefaults', 'hasgeneratedtraits',
    'nudity_core', 'no_getfamous', 'not_predisposed', 'trait_adult', 'trait_teen',
    'trait_elder', 'trait_youngadult', 'genderfemale', 'gendermale', 'tailstyle',
    'pet_age_', 'discipline_', 'disciplinedout_', 'trait_hidden_',
    'relexpectations_', 'practicemakesperfect', 'noopinion_', 'civicpolicy_',
    'attraction_haircolor', 'attraction_outfitcolor',
)


def _filter_bits(bits: list[str] | None) -> list[str]:
    return [b for b in (bits or []) if not any(x in b.lower() for x in _NOISY_REL_BIT_SUBSTRINGS)]


def _clean_sim_for_prompt(sim: dict, partner: dict | None = None) -> dict:
    mood = str(sim.get('mood') or '')
    partner_id = str(partner.get('id') or '') if isinstance(partner, dict) else ''
    careers = [
        f"{resolve_stbl(c.get('track_stbl'), sim, partner) or c.get('track_id') or c.get('id')}"
        + (f" - {t}" if (t := resolve_stbl(c.get('title_stbl'), sim, partner)) else '')
        + f" (lvl {c.get('level')})"
        for c in (sim.get('careers') or [])
    ]
    skills = [
        f"{resolve_stbl(sk.get('stbl'), sim, partner) or sk.get('id')} (lvl {sk.get('level')})"
        for sk in (sim.get('skills') or [])[:6]
    ]
    buffs = [
        {k: v for k, v in {
            'id': b.get('id'),
            'name': resolve_stbl(b.get('name_stbl'), sim, partner),
            'reason': resolve_stbl(b.get('reason_stbl'), sim, partner),
        }.items() if v}
        for b in (sim.get('buffs') or [])
    ]
    activities = [
        {k: v for k, v in {
            'id': act.get('id'),
            'label': resolve_stbl(act.get('stbl'), sim, partner),
            'target_label': resolve_stbl(act.get('target_stbl'), sim, partner) or act.get('target'),
            'recipe_label': resolve_stbl(act.get('recipe_stbl'), sim, partner) or act.get('recipe'),
        }.items() if v}
        for act in (sim.get('activities') or [])
    ]
    connections = []
    for conn in sim.get('social_connections') or []:
        if not isinstance(conn, dict) or str(conn.get('id') or '') == partner_id:
            continue
        fb, rb = _filter_bits(conn.get('bits')), _filter_bits(conn.get('reverse_bits'))
        if fb or rb or abs(float(conn.get('romance') or 0.0)) >= 20.0 or abs(float(conn.get('friendship') or 0.0)) >= 35.0:
            connections.append({k: v for k, v in {
                'name': conn.get('name'),
                'same_household': True if conn.get('same_household') else None,
                'friendship': conn.get('friendship'),
                'romance': conn.get('romance'),
                'bits': fb[:8],
                'reverse_bits': rb[:6],
            }.items() if v})
    raw = {
        'name': sim.get('name'),
        'age': sim.get('age'),
        'gender': sim.get('gender'),
        'species': _SPECIES_NAMES.get(str(sim.get('species')), sim.get('species') or 'HUMAN'),
        'breed': resolve_stbl(sim.get('breed_stbl'), sim, partner) or sim.get('breed'),
        'mood': mood[5:] if mood.startswith('Mood_') else (mood or None),
        'household_funds': sim.get('household_funds'),
        'trait_labels': [l for l in (resolve_stbl(s, sim, partner) for s in sim.get('trait_stbls', [])) if l] or sim.get('traits'),
        'notable_traits': [t for t in (sim.get('extra_traits') or []) if not any(k in t.lower() for k in _NOISY_TRAIT_SUBSTRINGS)][:15],
        'aspiration': sim.get('aspiration'),
        'careers': careers,
        'top_skills': skills,
        'active_buffs': buffs,
        'activity_labels': activities,
        'social_connections': connections[:6],
    }
    return {k: v for k, v in raw.items() if v}


class MemoryStore:
    def __init__(self, data_dir: Path | None):
        self.data_dir = data_dir or (ROOT / '.local')
        self.path = self.data_dir / 'memories.json'
        self.pairs: dict[str, list[dict]] = (
            json.loads(self.path.read_text(encoding='utf-8-sig'))['pairs'] if self.path.exists() else {}
        )

    @staticmethod
    def make_key(actor_name: str, target_name: str | None = None) -> str:
        a, t = (actor_name or 'Sim').strip(), (target_name or '').strip()
        return ' :: '.join(sorted((a, t))) if t and t != a else f'solo::{a}'

    def get_memory(self, actor_name: str, target_name: str | None = None, limit: int = 4) -> list[dict]:
        return (self.pairs.get(self.make_key(actor_name, target_name)) or [])[-limit:]

    def record(self, event: dict, scene: dict, text: str) -> None:
        actor = event.get('actor') or {}
        target = event.get('target') if isinstance(event.get('target'), dict) else None
        aname, tname = str(actor.get('name') or '').strip(), (str(target.get('name') or '').strip() if target else '')
        if not aname or not text:
            return
        lst = self.pairs.setdefault(self.make_key(aname, tname), [])
        lst.append({
            'ts': round(time.time(), 1),
            'lot': scene.get('lot_name') or scene.get('venue_label') or scene.get('venue'),
            'interaction': scene.get('interaction_label') or scene.get('interaction'),
            'outcome': scene.get('outcome'),
            'text': text.strip(),
        })
        del lst[:-8]
        _safe_write_json(self.path, {'updated_at': round(time.time(), 1), 'pair_count': len(self.pairs), 'pairs': self.pairs}, indent=2)


class CostTracker:
    def __init__(self, data_dir: Path):
        self.summary_path = data_dir / 'cost_summary.json'
        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/key', headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            key = json.loads(resp.read().decode('utf-8'))['data']
        self.key_usage_at_start = float(key['usage'])
        self.key_limit_remaining = key.get('limit_remaining')
        self.session_usd = 0.0
        self.session_exchanges = 0

    def record_exchange(self, cost_usd: float) -> dict:
        self.session_usd += cost_usd
        self.session_exchanges += 1
        summary = {
            'session_usd': round(self.session_usd, 6),
            'session_exchanges': self.session_exchanges,
            'total_usd': round(self.key_usage_at_start + self.session_usd, 6),
            'key_limit_remaining_usd_at_start': self.key_limit_remaining,
        }
        _safe_write_json(self.summary_path, summary, indent=2)
        return summary


def choose_scene_language(event: dict) -> str:
    msg = event.get('player_message') or ''
    if re.search(r'[֐-׿]', msg):
        return 'Hebrew (עברית)'
    if re.search(r'[Ѐ-ӿ]', msg):
        return 'Russian (Русский)'
    r = random.random()
    if r < MULTILINGUAL_CHANCE / 2.0:
        return 'Hebrew (עברית)'
    return 'Russian (Русский)' if r < MULTILINGUAL_CHANCE else 'English'


def build_scene(event: dict, language: str = 'English', pair_memory: list[dict] | None = None) -> dict:
    actor = event['actor']
    target = event.get('target') if isinstance(event.get('target'), dict) else None
    event_type = event.get('type', 'social')
    speaker_count = 1 if target is None or event_type in ('solo_vocal', 'player_ask_self') else 2
    interaction_label = resolve_stbl(event.get('interaction_stbl'), actor, target)
    venue_label = resolve_stbl(event.get('venue_stbl'), actor, target)
    lot_traits = [z for z in (event.get('lot_traits') or []) if 'hidden' not in z.lower()]
    scene: dict = {
        'event_type': event_type,
        'speaker_count': speaker_count,
        'language': language,
        'interaction': event.get('interaction'),
        'interaction_label': interaction_label,
        'outcome': event.get('outcome'),
        'venue': event.get('venue'),
        'venue_label': venue_label,
        'lot_name': event.get('lot_name'),
        'lot_traits': lot_traits or None,
        'business': event.get('business'),
        'actor': _clean_sim_for_prompt(actor, target),
        'target': _clean_sim_for_prompt(target, actor) if target else None,
    }
    scene = {k: v for k, v in scene.items() if v is not None or k in ('target', 'outcome', 'interaction_label', 'venue_label')}
    if target and isinstance(event.get('relationship'), dict):
        raw_rel = event['relationship']
        scene['relationship'] = {
            'friendship': raw_rel.get('friendship'),
            'romance': raw_rel.get('romance'),
            'bits': _filter_bits(raw_rel.get('bits')),
            'reverse_bits': _filter_bits(raw_rel.get('reverse_bits')),
        }
    if event.get('player_message'):
        scene['player_message'] = event['player_message']
    if pair_memory:
        scene['pair_memory'] = pair_memory[-4:]
    return scene


def select_openrouter_voice(sim: dict, slot: int = 0, avoid_voice: str | None = None) -> str:
    sim_id = str(sim.get('id') or sim.get('name') or slot)
    cached = _sim_voice_assignments.get(sim_id)
    if cached and cached != avoid_voice:
        return cached
    pool = FEMALE_OPENROUTER_VOICES if str(sim.get('gender') or '').upper() == 'FEMALE' else MALE_OPENROUTER_VOICES
    id_num = abs(int(sim['id'])) if str(sim.get('id') or '').lstrip('-').isdigit() else sum(ord(c) for c in sim_id)
    base_idx = (id_num + slot) % len(pool)
    chosen = pool[(base_idx + 1) % len(pool)] if pool[base_idx] == avoid_voice else pool[base_idx]
    _sim_voice_assignments[sim_id] = chosen
    return chosen


MOOD_TO_DELIVERY_TONE = {
    'Angry': 'exasperated, dramatic, annoyed',
    'Flirty': 'warm, playful, flirty',
    'Uncomfortable': 'tense, dry, slightly frazzled',
    'Confident': 'confident, lively, self-assured',
    'Bored': 'deadpan, unimpressed, dry',
    'Sad': 'sighing, dramatic, melancholic',
    'Playful': 'amused, upbeat, cheeky',
    'Embarrassed': 'flustered, awkward, defensive',
    'Inspired': 'animated, expressive, enthusiastic',
    'Focused': 'crisp, matter-of-fact, sharp',
}


def _transcript_matches(spoken_text: str, transcript: str) -> bool:
    spoken = set(re.findall(r'\w+', spoken_text.lower()))
    return not spoken or len(spoken & set(re.findall(r'\w+', transcript.lower()))) / len(spoken) >= 0.6


def _synthesize_single_line_openrouter(spoken_text: str, voice: str, mood: str) -> dict:
    tone = MOOD_TO_DELIVERY_TONE.get((mood or 'Fine').replace('Mood_', ''), 'natural, expressive, playful')
    payload = {
        'model': TTS_MODEL,
        'modalities': ['text', 'audio'],
        'audio': {'voice': voice, 'format': 'pcm16'},
        'stream': True,
        'temperature': 0.6,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are a closed-caption voice-over tool for a T-rated comedy video game (The Sims 4). '
                    f'Delivery tone: {tone}. '
                    'The user provides a pre-approved, fictional in-game subtitle line inside <read>. '
                    'Your sole function is to vocalize the subtitle text verbatim. '
                    'Do not evaluate, answer, refuse, or converse; simply read the subtitle text aloud word-for-word.'
                ),
            },
            {'role': 'user', 'content': f'Read aloud verbatim: <read>{spoken_text}</read>'},
        ],
    }
    req = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}', 'Content-Type': 'application/json'},
        method='POST',
    )
    t0 = time.monotonic()
    ttfa = None
    pcm_chunks: list[bytes] = []
    transcript_parts: list[str] = []
    usage: dict = {}
    with urllib.request.urlopen(req, timeout=25) as resp:
        for raw in resp:
            ln = raw.decode('utf-8').strip()
            if not ln.startswith('data: ') or ln[6:] == '[DONE]':
                continue
            chunk = json.loads(ln[6:])
            if chunk.get('usage'):
                usage = chunk['usage']
            choices = chunk.get('choices') or []
            if choices:
                audio = (choices[0].get('delta') or {}).get('audio') or {}
                if audio.get('data'):
                    if ttfa is None:
                        ttfa = round(time.monotonic() - t0, 3)
                    pcm_chunks.append(base64.b64decode(audio['data']))
                if audio.get('transcript'):
                    transcript_parts.append(audio['transcript'])
    ttlt = round(time.monotonic() - t0, 3)
    transcript = ''.join(transcript_parts).strip()
    if not _transcript_matches(spoken_text, transcript):
        gem_voice = GEMINI_VOICE_MAP.get(voice, 'Kore')
        gem_req = urllib.request.Request(
            'https://openrouter.ai/api/v1/audio/speech',
            data=json.dumps({'model': FALLBACK_TTS_MODEL, 'input': spoken_text, 'voice': gem_voice, 'response_format': 'pcm'}).encode('utf-8'),
            headers={'Authorization': f'Bearer {OPENROUTER_API_KEY}', 'Content-Type': 'application/json'},
            method='POST',
        )
        t_gem = time.monotonic()
        with urllib.request.urlopen(gem_req, timeout=20) as gem_resp:
            gem_pcm = gem_resp.read()
        return {
            'voice': f'{voice}->{gem_voice}', 'tone': tone, 'pcm': gem_pcm,
            'ttfa_s': None, 'ttlt_s': round(time.monotonic() - t_gem, 3), 'transcript': spoken_text,
            'cost_usd': float(usage.get('cost') or 0.0), 'usage': usage, 'fallback_model': FALLBACK_TTS_MODEL,
        }
    return {
        'voice': voice, 'tone': tone, 'pcm': b''.join(pcm_chunks),
        'ttfa_s': ttfa, 'ttlt_s': ttlt, 'transcript': transcript,
        'cost_usd': float(usage.get('cost') or 0.0), 'usage': usage,
    }


def synthesize_dialogue_openrouter(text: str, actor: dict, target: dict | None, wav_path: Path) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    actor_voice = select_openrouter_voice(actor, 0)
    target_voice = select_openrouter_voice(target, 1, avoid_voice=actor_voice) if target else None
    tasks = []
    for idx, line in enumerate(lines[:1 if target is None else 2]):
        spoken = (line.split(':', 1)[1] if ':' in line else line).strip(' "“”')
        sim = actor if idx == 0 or target is None else target
        voice = actor_voice if idx == 0 or target_voice is None else target_voice
        if spoken:
            tasks.append((spoken, voice, str(sim.get('mood') or 'Fine')))

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        futures = [pool.submit(_synthesize_single_line_openrouter, *task) for task in tasks]
        line_results = []
        for (_, voice, _), future in zip(tasks, futures):
            try:
                line_results.append(future.result())
            except Exception as exc:
                line_results.append({'voice': voice, 'pcm': b'', 'cost_usd': 0.0, 'error': str(exc)})

    sample_rate = 24000
    combined_pcm = (b'\x00\x00' * int(sample_rate * 0.18)).join(r['pcm'] for r in line_results if r['pcm'])
    if combined_pcm:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(combined_pcm)
    return {
        'model': TTS_MODEL,
        'audio_file': str(wav_path) if combined_pcm else None,
        'lines': [{k: v for k, v in r.items() if k != 'pcm'} for r in line_results],
        'tts_elapsed_seconds': round(time.monotonic() - started, 3),
        'tts_cost_usd': round(sum(r['cost_usd'] for r in line_results), 6),
        'duration_seconds': round(len(combined_pcm) / (sample_rate * 2), 2),
    }


def _strip_outer_quotes(text: str) -> str:
    s = text.strip(' *')
    return s[1:-1].strip() if len(s) >= 2 and s[0] in '"“”' and s[-1] in '"“”' else s


def _normalize_dialogue_lines(raw_text: str, event: dict) -> str:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    actor_name = (event.get('actor') or {}).get('name') or 'Sim'
    target = event.get('target')
    target_name = target.get('name') if isinstance(target, dict) else None
    event_type = event.get('type', 'social')
    player_msg = (event.get('player_message') or '').strip()

    if target is None or event_type in ('solo_vocal', 'player_ask_self'):
        first = lines[0] if lines else ''
        return f"{actor_name}: {_strip_outer_quotes(first.split(':', 1)[1] if ':' in first else first)}"
    if event_type == 'player_chat' and player_msg:
        last = lines[-1] if lines else ''
        return f"{actor_name}: {player_msg}\n{target_name}: {_strip_outer_quotes(last.split(':', 1)[1] if ':' in last else last)}"
    out = []
    for idx, ln in enumerate(lines[:2]):
        spk, body = ln.split(':', 1) if ':' in ln else (actor_name if idx == 0 else (target_name or 'Sim'), ln)
        out.append(f"{spk.strip('* ')}: {_strip_outer_quotes(body)}")
    return '\n'.join(out)


def generate(
    event: dict,
    memory_store: MemoryStore,
    tts_dir: Path | None = None,
    cost_tracker: CostTracker | None = None,
) -> dict:
    language = choose_scene_language(event)
    actor_name = str(event['actor'].get('name') or '')
    target = event.get('target')
    pair_mem = memory_store.get_memory(actor_name, target.get('name') if target else None)
    scene = build_scene(event, language=language, pair_memory=pair_mem)
    payload = {
        'model': CHAT_MODEL,
        'messages': [
            {'role': 'system', 'content': (ROOT / 'prompt.txt').read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(scene, ensure_ascii=False)},
        ],
        'max_tokens': 300,
        'reasoning': {'effort': REASONING_EFFORT},
    }
    request = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + OPENROUTER_API_KEY, 'Content-Type': 'application/json'},
        method='POST',
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    raw_text = result['choices'][0]['message']['content'].strip()
    if not raw_text:
        raise ValueError('The model returned no dialogue.')
    text = _normalize_dialogue_lines(raw_text, event)
    usage = result.get('usage', {})
    out = {
        'event_id': event['event_id'],
        'event_type': event.get('type', 'social'),
        'speaker_count': scene['speaker_count'],
        'language': language,
        'text': text,
        'model': result.get('model', CHAT_MODEL),
        'finish_reason': result['choices'][0].get('finish_reason'),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'usage': usage,
    }
    cost_usd = float(usage.get('cost') or 0.0)
    if tts_dir is not None:
        out['tts'] = synthesize_dialogue_openrouter(text, event['actor'], target, tts_dir / f"{event['event_id']}.wav")
        cost_usd += out['tts']['tts_cost_usd']
    memory_store.record(event, scene, text)
    if cost_tracker is not None:
        out['cost_summary'] = cost_tracker.record_exchange(cost_usd)
    return out


def _is_pid_running(pid: int) -> bool:
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        return exit_code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _safe_write_json(target_path: Path, payload: dict, indent: int | None = None) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f'{target_path.stem}.{os.getpid()}.tmp')
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent), encoding='utf-8')
    for attempt in range(10):
        try:
            os.replace(tmp_path, target_path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def _acquire_single_instance_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_PATH.open('a+')
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return None
    return lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path, default=DEFAULT_MODS_DIR / 'BanterLab' / 'BanterLabData')
    parser.add_argument('--parent-pid', type=int, help='Exit when this process (the game) exits.')
    parser.add_argument('--once', type=Path, help='Generate text once from a captured event JSON file.')
    args = parser.parse_args()
    data = args.data_directory

    if args.once:
        event = json.loads(args.once.read_text(encoding='utf-8-sig'))
        print(json.dumps(generate(event, MemoryStore(ROOT / '.local' / 'once')), ensure_ascii=False, indent=2))
        return

    lock = _acquire_single_instance_lock()
    if lock is None:
        print('Another companion is already running; exiting.', flush=True)
        return
    reply_file = data / 'reply.json'
    events = data / 'events.jsonl'
    events.touch(exist_ok=True)
    load_stbl_dictionary()
    memories = MemoryStore(data)
    tracker = CostTracker(data)
    print(
        f'Listening (model={CHAT_MODEL}, tts={TTS_MODEL}, total so far=${tracker.key_usage_at_start:.4f}, '
        f'key remaining=${tracker.key_limit_remaining})',
        flush=True,
    )

    last_parent_check = time.monotonic()
    with events.open('r', encoding='utf-8') as incoming:
        incoming.seek(0, os.SEEK_END)
        while True:
            if args.parent_pid and time.monotonic() - last_parent_check > 2.0:
                last_parent_check = time.monotonic()
                if not _is_pid_running(args.parent_pid):
                    print('The game exited; companion exiting.', flush=True)
                    return
            offset = incoming.tell()
            line = incoming.readline()
            if not line or not line.endswith('\n'):
                incoming.seek(offset)
                time.sleep(0.15)
                continue
            event = json.loads(line)
            if event.get('type') == 'displayed':
                audio_path = (event.get('tts') or {}).get('audio_file')
                if audio_path:
                    winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                continue
            if event.get('type') not in ('social', 'player_chat', 'solo_vocal', 'player_ask_self'):
                continue
            try:
                reply = generate(event, memories, tts_dir=TTS_DIR, cost_tracker=tracker)
            except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
                reply = {'event_id': event['event_id'], 'error': str(exc)}
            _safe_write_json(reply_file, reply)
            if 'error' in reply:
                print(json.dumps(reply, ensure_ascii=False), flush=True)
                continue
            tts = reply['tts']
            failed = [ln['error'] for ln in tts['lines'] if 'error' in ln]
            print(
                f"[{reply['event_id']}] lang={reply['language']} chat={reply['elapsed_seconds']}s "
                f"tts={tts['tts_elapsed_seconds']}s audio={tts['duration_seconds']}s "
                f"voices={[ln['voice'] for ln in tts['lines']]} | session=${reply['cost_summary']['session_usd']:.4f} "
                f"total=${reply['cost_summary']['total_usd']:.4f}" + (f' | silent lines: {failed}' if failed else ''),
                flush=True,
            )


if __name__ == '__main__':
    main()
