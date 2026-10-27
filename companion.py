"""Generate banter and realistic AI voices outside the game's legacy Python 3.7 thread.

The game mod starts this process (`--data-directory`, `--parent-pid`); it exits when the game exits.
It tails the game's events.jsonl, writes reply.json, synthesizes trilingual (English / Hebrew / Russian)
speech with openai/gpt-audio-mini, and plays it when the game logs `displayed`.
`--once scene.json` generates text for one captured event (for offline prompt experiments).
"""

import argparse
import array
import base64
import contextlib
import ctypes
import http.client
import json
import math
import msvcrt
import os
import random
import re
import struct
import subprocess
import sys
import threading
import time
import wave
import winsound
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
_tls_local = threading.local()
_sapi_lock = threading.Lock()
_sapi_proc: subprocess.Popen | None = None
BYSTANDER_HUMAN_CHANCE = 0.40
BYSTANDER_PET_CHANCE = 0.75


def _openrouter_conn(reset: bool = False) -> http.client.HTTPSConnection:
    conn = getattr(_tls_local, 'conn', None)
    if reset and conn is not None:
        with contextlib.suppress(OSError):
            conn.close()
        conn = None
    if conn is None:
        conn = http.client.HTTPSConnection('openrouter.ai', timeout=25)
        _tls_local.conn = conn
    return conn


def _openrouter_request(method: str, path: str, body: bytes | None = None, timeout: float = 20.0) -> http.client.HTTPResponse:
    headers = {'Authorization': f'Bearer {OPENROUTER_API_KEY}', 'Connection': 'keep-alive'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    for attempt in range(2):
        conn = _openrouter_conn(reset=(attempt > 0))
        conn.timeout = timeout
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            if resp.status >= 400:
                err_body = resp.read().decode('utf-8', errors='replace')[:300]
                raise OSError(f'HTTP {resp.status} on {path}: {err_body}')
            return resp
        except (http.client.HTTPException, ConnectionError, TimeoutError, OSError):
            _openrouter_conn(reset=True)
            if attempt == 1:
                raise
    raise RuntimeError('Unreachable')

FEMALE_OPENROUTER_VOICES = ('coral', 'nova', 'shimmer', 'sage', 'ballad', 'alloy')
MALE_OPENROUTER_VOICES = ('ash', 'echo', 'onyx', 'verse', 'fable')
YOUTH_OPENROUTER_VOICES = ('shimmer', 'coral', 'nova', 'fable', 'sage')
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
    const_type = struct.unpack_from('<I', data, pos)[0] if (flags & 1) else None
    if flags & 1:
        pos += 4
    if flags & 2:
        pos += 4
    const_inst_hi = struct.unpack_from('<I', data, pos)[0] if (flags & 4) else None
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
        inst_hi = const_inst_hi if (flags & 4) else struct.unpack_from('<I', data, pos)[0]
        if not (flags & 4):
            pos += 4
        if not (flags & 8):
            pos += 4
        offset, size_raw, mem_size, comp_type = struct.unpack_from('<IIIH', data, pos)
        pos += 16
        size = size_raw & 0x7FFFFFFF
        # Resource 0x220557DA is STBL; high byte of Instance64 is locale (0x00 = ENG_US).
        if rtype != 0x220557DA or (inst_hi >> 24) != 0:
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


def _stbl_source_mtime(game_dir: Path) -> float:
    mtimes = [0.0]
    exe = game_dir / 'Game' / 'Bin' / 'TS4_x64.exe'
    if exe.exists():
        mtimes.append(exe.stat().st_mtime)
    if DEFAULT_MODS_DIR.exists():
        for pkg in DEFAULT_MODS_DIR.rglob('*.package'):
            if pkg.name != 'BanterLabUI.package':
                mtimes.append(pkg.stat().st_mtime)
    return round(max(mtimes), 3)


def load_stbl_dictionary(game_dir: Path = DEFAULT_GAME_DIR) -> dict[int, str]:
    global _stbl_cache
    if _stbl_cache is not None:
        return _stbl_cache
    meta_path = STBL_CACHE_PATH.with_suffix('.meta.json')
    cur_mtime = _stbl_source_mtime(game_dir)
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    if STBL_CACHE_PATH.exists() and meta.get('v') == 2 and meta.get('max_mtime') == cur_mtime:
        _stbl_cache = {int(k): v for k, v in json.loads(STBL_CACHE_PATH.read_text(encoding='utf-8')).items()}
        return _stbl_cache
    strings: dict[int, str] = {}
    if game_dir.exists():
        for pkg in sorted(game_dir.rglob('Strings_ENG_US.package')):
            strings.update(_read_package_stbls(pkg))
    if DEFAULT_MODS_DIR.exists():
        for pkg in sorted(DEFAULT_MODS_DIR.rglob('*.package')):
            try:
                strings.update(_read_package_stbls(pkg))
            except (OSError, struct.error, zlib.error, IndexError):
                continue
    if strings:
        STBL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STBL_CACHE_PATH.write_text(json.dumps(strings, ensure_ascii=False), encoding='utf-8')
        meta_path.write_text(json.dumps({'v': 2, 'max_mtime': cur_mtime}), encoding='utf-8')
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
        for ptok, m_val, f_val in (
            ('SimPronounSubjective', 'he', 'she'),
            ('SimPronounObjective', 'him', 'her'),
            ('SimPronounPossessiveDependent', 'his', 'her'),
            ('SimPronounPossessiveIndependent', 'his', 'hers'),
            ('SimPronounReflexive', 'himself', 'herself'),
        ):
            text = text.replace(f'{{{idx}.{ptok}}}', f_val if is_female else m_val)
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
    text = re.sub(r'<[^>]+>|\{[^{}]*\}|["“”]\s*["“”]', '', text)
    text = ' '.join(text.split()).strip()
    if not text or any(p in text.lower() for p in ('(should not be seen)', '**debug**', '** debug **', 'set 01')):
        return None
    return text


_NOISY_REL_BIT_SUBSTRINGS = (
    'has_met', 'specialbits_greeted', 'suppresschangebehavior',
    'neutralto_target', 'neutralwith_target', 'reactioncooldown',
    'recentlyhadsocialinteraction', 'persistent_boredom_reset',
    'infant_checkon', 'socialcontext_retail_uninterested',
    'relbit_socialcontext_', 'shortterm_recentnegativesocial',
    'pettopet_relationshipbit_neutral', 'simtopet_relationshipbit_02_acquaintance',
    'relationshipbit_simtosim', 'friendship-acquaintances', 'romanticcombo_acquaintances',
    'compatibility_good', 'compatibility_bad', 'relbit_attraction_4_', 'attractiveness_visual_',
    'attractiveness_noticed_', 'relationship_archetype_hint_',
    'healednegativesentiment', 'memories_memorytype_', 'hasbeenfriends',
    'romantic_firstkiss', 'shorttermbits_restuarants_dining',
)


_NOISY_TRAIT_SUBSTRINGS = (
    'genderoptions', 'walkstyle', 'handedness', 'occult_nooccult', 'species_',
    'speciesextended_', 'umbrella', 'pregnan', 'lactat', 'toilet', 'clothing', 'frame_',
    'attractedto', 'woohoointerests', 'hasdefaults', 'hasgeneratedtraits',
    'nudity_core', 'no_getfamous', 'not_predisposed', 'trait_adult', 'trait_teen',
    'trait_elder', 'trait_youngadult', 'genderfemale', 'gendermale', 'tailstyle',
    'pet_age_', 'discipline_', 'disciplinedout_', 'trait_hidden_', '_hidden',
    'relexpectations_', 'practicemakesperfect', 'noopinion_', 'civicpolicy_',
    'attraction_haircolor_', 'attraction_outfitcolor_', 'likes_color_', 'dislikes_color_',
    'iscustomgender', 'trait_cas_story_',
)


def _clean_mood(mood: str | None) -> str | None:
    m = re.sub(r'^(?i:mood_)|_(?i:dog|cat|horse)$', '', str(mood or '')).replace('Horse_', '')
    return m or None


def _filter_bits(bits: list[str] | None, friendship: float = 0.0) -> list[str]:
    out = [b for b in (bits or []) if not any(x in b.lower() for x in _NOISY_REL_BIT_SUBSTRINGS)]
    return [b for b in out if b != 'bit_NoLongerFriends'] if friendship >= 35.0 else out


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
        if not str(b.get('id') or '').lower().startswith(('buff_environment_', 'buff_lotmods_')) and not any(x in str(b.get('id') or '').lower() for x in ('period_effect_none', 'attractiveness_noticed_', 'relsat_relbit_')) and b.get('id') != 'Buff'
    ]
    raw_acts = []
    for act in (sim.get('activities') or []):
        aid = str(act.get('id') or '')
        is_sit = 'sit' in aid.lower()
        lbl = 'Ordered at restaurant' if aid == 'restaurant_order' else resolve_stbl(act.get('stbl'), sim, partner)
        tlbl = None if is_sit else (resolve_stbl(act.get('target_stbl'), sim, partner) or act.get('target'))
        rlbl = resolve_stbl(act.get('recipe_stbl'), sim, partner) or act.get('recipe')
        qlbl = resolve_stbl(act.get('quality_stbl'), sim, partner) or re.sub(r'^Quality_', '', str(act.get('quality') or '')) or None
        if lbl or tlbl or rlbl:
            raw_acts.append({k: v for k, v in {
                'id': act.get('id'), 'label': lbl, 'target_label': tlbl,
                'recipe_label': rlbl if rlbl != tlbl else None,
                'cooked_by': act.get('cooked_by'),
                'quality': 'Spoiled' if act.get('spoiled') else qlbl,
                'masterwork': True if act.get('masterwork') else None,
                'comped': True if act.get('comped') else None,
            }.items() if v})
    labelled_targets = {a.get('target_label') for a in raw_acts if a.get('label') and a.get('target_label')}
    activities = []
    seen_unlabelled = set()
    has_non_sit = any('sit' not in str(a.get('id') or '').lower() for a in raw_acts)
    for a in raw_acts:
        if has_non_sit and 'sit' in str(a.get('id') or '').lower():
            continue
        if a.get('label'):
            activities.append(a)
        elif a.get('target_label') not in labelled_targets and a.get('target_label') not in seen_unlabelled:
            seen_unlabelled.add(a.get('target_label'))
            activities.append(a)
    connections = []
    for conn in sim.get('social_connections') or []:
        if not isinstance(conn, dict) or str(conn.get('id') or '') == partner_id:
            continue
        f_score = float(conn.get('friendship') or 0.0)
        fb, rb = _filter_bits(conn.get('bits'), f_score), _filter_bits(conn.get('reverse_bits'), f_score)
        if fb or rb or abs(float(conn.get('romance') or 0.0)) >= 20.0 or abs(float(conn.get('friendship') or 0.0)) >= 35.0:
            connections.append({k: v for k, v in {
                'name': conn.get('name'),
                'same_household': True if conn.get('same_household') else None,
                'friendship': conn.get('friendship'),
                'romance': conn.get('romance'),
                'bits': fb[:14],
                'reverse_bits': rb[:8],
            }.items() if v})
    events = []
    for sit in (sim.get('situations') or []):
        sname = resolve_stbl(sit.get('stbl'), sim, partner)
        rname = resolve_stbl(sit.get('role_stbl'), sim, partner)
        raw_s, raw_r = sit.get('id'), sit.get('role')
        if sname and rname and sname != rname:
            lbl = f'{sname} ({rname})'
        elif rname or sname:
            lbl = rname or sname
        else:
            lbl = f'{raw_s} ({raw_r})' if (raw_s and raw_r) else (raw_s or raw_r)
        if lbl and lbl not in events:
            events.append(lbl)
    species = str(sim.get('species') or 'HUMAN')
    raw = {
        'name': sim.get('name'),
        'age': sim.get('age'),
        'gender': sim.get('gender'),
        'species': species,
        'breed': resolve_stbl(sim.get('breed_stbl'), sim, partner) or sim.get('breed'),
        'outfit': sim.get('outfit') if species == 'HUMAN' else None,
        'pregnant': sim.get('pregnant'),
        'outdoors': True if sim.get('is_outside') else None,
        'mood': _clean_mood(mood),
        'household_funds': sim.get('household_funds'),
        'trait_labels': [l for l in (resolve_stbl(s, sim, partner) for s in sim.get('trait_stbls', [])) if l] or sim.get('traits'),
        'notable_traits': [t for t in (sim.get('extra_traits') or []) if not any(k in t.lower() for k in _NOISY_TRAIT_SUBSTRINGS)][:18],
        'aspiration': resolve_stbl(sim.get('aspiration_stbl'), sim, partner) or sim.get('aspiration'),
        'careers': careers,
        'top_skills': skills,
        'active_buffs': buffs,
        'activity_labels': activities,
        'social_events': events,
        'social_connections': connections[:6],
    }
    return {k: v for k, v in raw.items() if v}


class MemoryStore:
    def __init__(self, data_dir: Path | None = None):
        self.path = (data_dir / 'memories.json') if data_dir is not None else None
        self.pairs: dict[str, list[dict]] = (
            json.loads(self.path.read_text(encoding='utf-8-sig'))['pairs']
            if self.path is not None and self.path.exists() else {}
        )

    @staticmethod
    def make_key(actor_name: str, target_name: str | None = None) -> str:
        a, t = (actor_name or 'Sim').strip(), (target_name or '').strip()
        return ' :: '.join(sorted((a, t))) if t and t != a else f'solo::{a}'

    def get_memory(self, actor_name: str, target_name: str | None = None, limit: int = 4) -> list[dict]:
        return (self.pairs.get(self.make_key(actor_name, target_name)) or [])[-limit:]

    def get_gossip(self, actor_name: str, target_name: str | None = None, limit: int = 2) -> list[dict]:
        if not target_name:
            return []
        cur_key = self.make_key(actor_name, target_name)
        speakers = {actor_name.strip(), target_name.strip()}
        cutoff = time.time() - 21600.0
        hits = []
        for k, entries in self.pairs.items():
            if k == cur_key or k.startswith('solo::') or ' :: ' not in k:
                continue
            parts = set(k.split(' :: '))
            if parts & speakers:
                for e in entries[-2:]:
                    if float(e.get('ts') or 0) >= cutoff:
                        hits.append((float(e.get('ts') or 0), {'pair': k, 'interaction': e.get('interaction'), 'text': e.get('text')}))
        hits.sort(key=lambda x: -x[0])
        return [h[1] for h in hits[:limit]]

    def record(self, event: dict, scene: dict, text: str) -> None:
        actor = event.get('actor') or {}
        target = None if event.get('type') == 'inner_thought' else (event.get('target') if isinstance(event.get('target'), dict) else None)
        aname, tname = str(actor.get('name') or '').strip(), (str(target.get('name') or '').strip() if target else '')
        if not aname or not text:
            return
        key = self.make_key(aname, tname)
        lst = self.pairs.pop(key, [])
        self.pairs[key] = lst
        lst.append({
            'ts': round(time.time(), 1),
            'lot': scene.get('lot_name') or scene.get('venue_label') or scene.get('venue'),
            'interaction': scene.get('interaction_label') or scene.get('interaction'),
            'outcome': scene.get('outcome'),
            'text': text.strip(),
        })
        del lst[:-8]
        while len(self.pairs) > 120:
            del self.pairs[next(iter(self.pairs))]
        if self.path is not None:
            _safe_write_json(self.path, {'updated_at': round(time.time(), 1), 'pair_count': len(self.pairs), 'pairs': self.pairs}, indent=2)


class CostTracker:
    def __init__(self, data_dir: Path):
        self.summary_path = data_dir / 'cost_summary.json'
        prev = json.loads(self.summary_path.read_text(encoding='utf-8-sig')) if self.summary_path.exists() else {}
        try:
            resp = _openrouter_request('GET', '/api/v1/key', timeout=8)
            key = json.loads(resp.read().decode('utf-8'))['data']
            self.key_usage_at_start = float(key['usage'])
            self.key_limit_remaining = key.get('limit_remaining')
        except (OSError, KeyError, ValueError):
            self.key_usage_at_start = float(prev.get('total_usd') or 0.0)
            self.key_limit_remaining = prev.get('key_limit_remaining_usd_at_start')
        self.session_usd = 0.0
        self.session_exchanges = 0
        _safe_write_json(self.summary_path, self._summary(), indent=2)

    def _summary(self) -> dict:
        return {
            'session_usd': round(self.session_usd, 6),
            'session_exchanges': self.session_exchanges,
            'total_usd': round(self.key_usage_at_start + self.session_usd, 6),
            'key_limit_remaining_usd_at_start': self.key_limit_remaining,
        }



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


def build_scene(
    event: dict,
    language: str = 'English',
    pair_memory: list[dict] | None = None,
    recent_gossip: list[dict] | None = None,
    include_bystander: bool = False,
) -> dict:
    actor = event['actor']
    target = event.get('target') if isinstance(event.get('target'), dict) else None
    bystander = event.get('bystander') if (include_bystander and isinstance(event.get('bystander'), dict)) else None
    event_type = event.get('type', 'social')
    speaker_count = 1 if target is None or event_type in ('player_ask_self', 'inner_thought', 'drama_reaction', 'sim_text') else (3 if bystander is not None else 2)
    interaction_label = resolve_stbl(event.get('interaction_stbl'), actor, target)
    venue_label = resolve_stbl(event.get('venue_stbl'), actor, target)
    lot_traits = [z for z in (event.get('lot_traits') or []) if 'hidden' not in z.lower()]
    drama_trigger = None
    if isinstance(event.get('drama_buff'), dict):
        db = event['drama_buff']
        drama_trigger = {k: v for k, v in {
            'id': db.get('id'),
            'name': resolve_stbl(db.get('name_stbl'), actor, target),
            'reason': resolve_stbl(db.get('reason_stbl'), actor, target),
        }.items() if v} or None
    renov = event.get('renovation_delta')
    scene: dict = {
        'event_type': event_type,
        'speaker_count': speaker_count,
        'language': language,
        'interaction': event.get('interaction'),
        'interaction_label': interaction_label,
        'outcome': event.get('outcome'),
        'player_message': event.get('player_message') or None,
        'drama_trigger': drama_trigger,
        'renovation_delta': f'{renov:+d}' if isinstance(renov, int) and renov else None,
        'venue': event.get('venue'),
        'venue_label': venue_label,
        'lot_name': event.get('lot_name'),
        'lot_value': event.get('lot_value'),
        'lot_rooms': event.get('lot_rooms'),
        'weather': re.sub(r'(?i)\bweather_', '', str(event.get('weather') or '')).replace('_', ' ') or None,
        'lot_traits': lot_traits or None,
        'business': event.get('business'),
        'nearby_sims': [
            f"{n['name']} (" + ', '.join(x for x in (
                n.get('species') if n.get('species') and n.get('species') != 'HUMAN' else None,
                f"{n['dist_m']}m",
                resolve_stbl(n.get('activity_stbl'), n),
            ) if x) + ')'
            for n in (event.get('nearby_sims') or []) if isinstance(n, dict) and n.get('name')
        ] or None,
        'actor': _clean_sim_for_prompt(actor, target),
        'target': _clean_sim_for_prompt(target, actor) if target else None,
        'bystander': _clean_sim_for_prompt(bystander, actor) if bystander else None,
    }
    scene = {k: v for k, v in scene.items() if v is not None or k in ('target', 'outcome', 'interaction_label', 'venue_label')}
    if target and isinstance(event.get('relationship'), dict):
        raw_rel = event['relationship']
        same_hh = bool(
            raw_rel.get('same_household')
            or any(str(c.get('id') or '') == str(target.get('id') or '') and c.get('same_household')
                   for c in (actor.get('social_connections') or []))
        )
        scene['relationship'] = {
            'same_household': same_hh,
            'friendship': raw_rel.get('friendship'),
            'romance': raw_rel.get('romance'),
            'bits': _filter_bits(raw_rel.get('bits'), float(raw_rel.get('friendship') or 0.0)),
            'reverse_bits': _filter_bits(raw_rel.get('reverse_bits'), float(raw_rel.get('friendship') or 0.0)),
        }
    if pair_memory:
        scene['pair_memory'] = pair_memory[-4:]
    if recent_gossip:
        scene['recent_gossip'] = recent_gossip[:2]
    return scene


def select_openrouter_voice(sim: dict, avoid_voices: tuple[str, ...] = ()) -> str:
    sim_id = str(sim.get('id') or sim.get('name') or '0')
    age = str(sim.get('age') or '').upper()
    pool = YOUTH_OPENROUTER_VOICES if age in ('CHILD', 'TODDLER', 'INFANT') else (
        FEMALE_OPENROUTER_VOICES if str(sim.get('gender') or '').upper() == 'FEMALE' else MALE_OPENROUTER_VOICES)
    base = _sim_voice_assignments.get(sim_id)
    if not base:
        id_num = abs(int(sim['id'])) if str(sim.get('id') or '').lstrip('-').isdigit() else sum(ord(c) for c in sim_id)
        base = pool[id_num % len(pool)]
        _sim_voice_assignments[sim_id] = base
    if base not in avoid_voices:
        return base
    return next((v for v in pool if v not in avoid_voices), base)


MOOD_TO_DELIVERY_TONE = {
    'Angry': 'exasperated, dramatic, annoyed',
    'Flirty': 'warm, playful, flirty',
    'Uncomfortable': 'tense, dry, slightly frazzled',
    'Stressed': 'stressed, tense, exasperated',
    'Confident': 'confident, lively, self-assured',
    'Energized': 'energetic, upbeat, lively',
    'Excited': 'excited, eager, animated',
    'Bored': 'deadpan, unimpressed, dry',
    'Sad': 'sighing, dramatic, melancholic',
    'Mopey': 'sighing, dramatic, melancholic',
    'Ashamed': 'flustered, sheepish, defensive',
    'Scared': 'nervous, jumpy, dramatic',
    'Anxious': 'nervous, jumpy, dramatic',
    'Dazed': 'dazed, spacey, bewildered',
    'Playful': 'amused, upbeat, cheeky',
    'Embarrassed': 'flustered, awkward, defensive',
    'Inspired': 'animated, expressive, enthusiastic',
    'Focused': 'crisp, matter-of-fact, sharp',
    'Asleep': 'groggy, sleepy, half-awake',
}


def _word_set(text: str) -> set[str]:
    clean = re.sub(r'[\u0300-\u036f\u0591-\u05c7]', '', text.lower().replace('ё', 'е'))
    words = re.findall(r'\w+', clean)
    return {w for w in words if len(w) >= 3} or set(words)


def _transcript_matches(spoken_text: str, transcript: str) -> bool:
    spoken = _word_set(spoken_text)
    return not spoken or len(spoken & _word_set(transcript)) / len(spoken) >= 0.6


def _synthesize_single_line_openrouter(spoken_text: str, voice: str, mood: str, age: str = '') -> dict:
    tone = MOOD_TO_DELIVERY_TONE.get(_clean_mood(mood) or 'Fine', 'natural, expressive, playful')
    if age.upper() in ('CHILD', 'TODDLER', 'INFANT'):
        tone = f'young, bright, playful; {tone}'
    spoken_words = _word_set(spoken_text)
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
    t0 = time.monotonic()
    ttfa = None
    pcm_chunks: list[bytes] = []
    transcript_parts: list[str] = []
    usage: dict = {}
    resp = _openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=25)
    aborted = False
    while True:
        raw = resp.readline()
        if not raw:
            break
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
                tr_words = _word_set(''.join(transcript_parts))
                if spoken_words and len(tr_words) >= 4 and not (tr_words & spoken_words):
                    aborted = True
                    break
    if aborted:
        _openrouter_conn(reset=True)
    else:
        resp.read()
    ttlt = round(time.monotonic() - t0, 3)
    transcript = ''.join(transcript_parts).strip()
    if not pcm_chunks or not _transcript_matches(spoken_text, transcript):
        gem_voice = GEMINI_VOICE_MAP.get(voice, 'Kore')
        gem_body = json.dumps({'model': FALLBACK_TTS_MODEL, 'input': spoken_text, 'voice': gem_voice, 'response_format': 'pcm'}).encode('utf-8')
        t_gem = time.monotonic()
        gem_pcm = _openrouter_request('POST', '/api/v1/audio/speech', gem_body, timeout=20).read()
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


def _synthesize_pet_windows_tts(spoken_text: str, sim: dict, fallback_voice: str = 'coral') -> dict:
    global _sapi_proc
    voice = 'Microsoft Zira Desktop' if str(sim.get('gender') or '').upper() == 'FEMALE' else 'Microsoft David Desktop'
    ps_loop = (
        '[Console]::InputEncoding = [System.Text.Encoding]::UTF8; '
        'Add-Type -AssemblyName System.Speech; '
        '$s = [System.Speech.Synthesis.SpeechSynthesizer]::new(); '
        '$fmt = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new('
        '24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono); '
        '$out = [Console]::OpenStandardOutput(); '
        'while (($line = [Console]::In.ReadLine()) -ne $null) { '
        '  $req = $line | ConvertFrom-Json; $s.SelectVoice($req.voice); '
        '  $ms = [System.IO.MemoryStream]::new(); $s.SetOutputToAudioStream($ms, $fmt); '
        '  $s.Speak([string]$req.text); $s.SetOutputToNull(); '
        '  $hdr = [System.Text.Encoding]::ASCII.GetBytes("$($ms.Length)`n"); '
        '  $out.Write($hdr, 0, $hdr.Length); $out.Write($ms.ToArray(), 0, [int]$ms.Length); $out.Flush() '
        '}'
    )
    t0 = time.monotonic()
    pcm = b''
    with _sapi_lock:
        try:
            if _sapi_proc is None or _sapi_proc.poll() is not None:
                _sapi_proc = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps_loop],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            assert _sapi_proc.stdin is not None and _sapi_proc.stdout is not None
            _sapi_proc.stdin.write((json.dumps({'voice': voice, 'text': spoken_text}, ensure_ascii=False) + '\n').encode('utf-8'))
            _sapi_proc.stdin.flush()
            nbytes = int(_sapi_proc.stdout.readline().decode('ascii').strip() or '0')
            pcm = _sapi_proc.stdout.read(nbytes) if nbytes > 0 else b''
        except (OSError, ValueError):
            _sapi_proc = None
    if not pcm:
        return _synthesize_single_line_openrouter(spoken_text, fallback_voice, str(sim.get('mood') or 'Fine'))
    return {
        'voice': voice, 'tone': 'windows_sapi5_pet', 'pcm': pcm,
        'ttfa_s': None, 'ttlt_s': round(time.monotonic() - t0, 3),
        'transcript': spoken_text, 'cost_usd': 0.0,
    }


def _normalize_and_trim_pcm(pcm: bytes, sr: int = 24000) -> bytes:
    if len(pcm) < 4:
        return pcm
    samples = array.array('h')
    samples.frombytes(pcm[:len(pcm) - (len(pcm) % 2)])
    n = len(samples)
    win = sr // 50
    active_wins = []
    speech_sq = 0.0
    speech_n = 0
    for i in range(0, n, win):
        seg = samples[i:i + win]
        if seg and max(abs(x) for x in seg) >= 180:
            active_wins.append(i)
            speech_sq += sum(x * x for x in seg)
            speech_n += len(seg)
    if not active_wins:
        return pcm
    trimmed = samples[max(0, active_wins[0] - int(sr * 0.025)):min(n, active_wins[-1] + win + int(sr * 0.055))]
    target_rms = 32768.0 * (10.0 ** (-18.5 / 20.0))
    gain = min(max(target_rms / max(1.0, math.sqrt(speech_sq / max(1, speech_n))), 0.35), 5.6)
    peak = max(abs(x) for x in trimmed)
    ceiling = 29200.0
    if peak * gain > ceiling:
        gain = min(gain, (ceiling * 1.35) / peak)
        out = array.array('h', (int(ceiling * math.tanh((x * gain) / ceiling)) for x in trimmed))
    else:
        out = array.array('h', (int(x * gain) for x in trimmed))
    return out.tobytes()


def _clean_spoken_line(line: str) -> str:
    return re.sub(r'\(\s*(?:Translation|תרגום|Перевод):\s*([^)]+)\)', r'\1', (line.split(':', 1)[1] if ':' in line else line), flags=re.IGNORECASE).strip(' "“”')


def _synthesize_sim_line(spoken: str, voice: str, sim: dict) -> dict:
    if str(sim.get('species') or 'HUMAN').upper() != 'HUMAN':
        return _synthesize_pet_windows_tts(spoken, sim, voice)
    return _synthesize_single_line_openrouter(spoken, voice, str(sim.get('mood') or 'Fine'), str(sim.get('age') or ''))


def synthesize_dialogue_openrouter(
    text: str, actor: dict, target: dict | None, wav_path: Path, bystander: dict | None = None,
    single_speaker: bool = False, pre_first_future=None,
) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    speakers = [actor] if (single_speaker or target is None) else ([actor, target, bystander] if bystander else [actor, target])
    voices: list[str] = []
    for sim in speakers:
        voices.append(select_openrouter_voice(sim, tuple(voices)))
    tasks = []
    for idx, line in enumerate(lines[:len(speakers)]):
        spoken = _clean_spoken_line(line)
        if spoken:
            tasks.append((idx, spoken, voices[idx], speakers[idx]))

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        futures = [
            (voice, pre_first_future if (idx == 0 and pre_first_future is not None) else pool.submit(_synthesize_sim_line, spoken, voice, sim))
            for idx, spoken, voice, sim in tasks
        ]
        line_results = []
        for voice, future in futures:
            try:
                line_results.append(future.result())
            except Exception as exc:
                line_results.append({'voice': voice, 'pcm': b'', 'cost_usd': 0.0, 'error': str(exc)})

    sample_rate = 24000
    combined_pcm = (b'\x00\x00' * int(sample_rate * 0.15)).join(
        _normalize_and_trim_pcm(r['pcm'], sample_rate) for r in line_results if r['pcm']
    )
    if combined_pcm:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(combined_pcm)
        for old in sorted(wav_path.parent.glob('*.wav'), key=lambda p: p.stat().st_mtime)[:-30]:
            old.unlink(missing_ok=True)
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
    return s[1:-1].strip() if len(s) >= 2 and s[0] in '"“”«' and s[-1] in '"“”»' else s


def _normalize_dialogue_lines(raw_text: str, event: dict, speaker_count: int = 2) -> str:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    actor_name = (event.get('actor') or {}).get('name') or 'Sim'
    target = event.get('target')
    target_name = target.get('name') if isinstance(target, dict) else None
    bystander = event.get('bystander')
    bystander_name = bystander.get('name') if isinstance(bystander, dict) else None
    event_type = event.get('type', 'social')
    player_msg = (event.get('player_message') or '').strip()

    if target is None or event_type in ('player_ask_self', 'inner_thought', 'drama_reaction', 'sim_text'):
        last = lines[-1] if lines else ''
        return f"{actor_name}: {_strip_outer_quotes(last.split(':', 1)[1] if ':' in last else last)}"
    if event_type == 'player_chat' and player_msg:
        last = lines[-1] if lines else ''
        return f"{actor_name}: {player_msg}\n{target_name}: {_strip_outer_quotes(last.split(':', 1)[1] if ':' in last else last)}"
    defaults = [actor_name, target_name or 'Sim', bystander_name or 'Sim']
    out = []
    for idx, ln in enumerate(lines[:speaker_count]):
        spk, body = ln.split(':', 1) if ':' in ln else (defaults[min(idx, 2)], ln)
        out.append(f"{spk.strip('* ')}: {_strip_outer_quotes(body)}")
    return '\n'.join(out)


def _should_include_bystander(event: dict) -> bool:
    bys = event.get('bystander')
    if event.get('type', 'social') != 'social' or not isinstance(bys, dict):
        return False
    if event.get('force_bystander'):
        return True
    is_pet = str(bys.get('species') or 'HUMAN').upper() != 'HUMAN'
    return random.random() < (BYSTANDER_PET_CHANCE if is_pet else BYSTANDER_HUMAN_CHANCE)


def generate(event: dict, memory_store: MemoryStore, tts_dir: Path | None = None) -> dict:
    language = choose_scene_language(event)
    actor_name = str(event['actor'].get('name') or '')
    target = event.get('target')
    target_name = target.get('name') if isinstance(target, dict) else None
    use_bystander = _should_include_bystander(event)
    bystander = event.get('bystander') if use_bystander else None
    pair_mem = memory_store.get_memory(actor_name, target_name)
    gossip = memory_store.get_gossip(actor_name, target_name)
    scene = build_scene(event, language=language, pair_memory=pair_mem, recent_gossip=gossip, include_bystander=use_bystander)
    payload = {
        'model': CHAT_MODEL,
        'messages': [
            {'role': 'system', 'content': (ROOT / 'prompt.txt').read_text(encoding='utf-8')},
            {'role': 'user', 'content': json.dumps(scene, ensure_ascii=False)},
        ],
        'max_tokens': 320,
        'reasoning': {'effort': REASONING_EFFORT},
    }
    player_spoken = _clean_spoken_line(event.get('player_message') or '') if (tts_dir is not None and event.get('type') == 'player_chat' and target) else ''
    with contextlib.ExitStack() as stack:
        pre_fut = None
        if player_spoken:
            pre_pool = stack.enter_context(ThreadPoolExecutor(max_workers=1))
            pre_fut = pre_pool.submit(_synthesize_sim_line, player_spoken, select_openrouter_voice(event['actor']), event['actor'])
        started = time.monotonic()
        resp = _openrouter_request('POST', '/api/v1/chat/completions', json.dumps(payload).encode('utf-8'), timeout=20)
        result = json.loads(resp.read().decode('utf-8'))
        raw_text = result['choices'][0]['message']['content'].strip()
        if not raw_text:
            raise ValueError('The model returned no dialogue.')
        text = _normalize_dialogue_lines(raw_text, event, speaker_count=scene['speaker_count'])
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
            out['tts'] = synthesize_dialogue_openrouter(
                text, event['actor'], target, tts_dir / f"{event['event_id']}.wav", bystander=bystander,
                single_speaker=(scene['speaker_count'] == 1), pre_first_future=pre_fut)
            cost_usd += out['tts']['tts_cost_usd']
    out['_scene'] = scene
    out['_cost_usd'] = cost_usd
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
    try:
        os.replace(tmp_path, target_path)
    except PermissionError:
        time.sleep(0.05)
        os.replace(tmp_path, target_path)


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
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path, default=ROOT / '.local' / 'data')
    parser.add_argument('--parent-pid', type=int, help='Exit when this process (the game) exits.')
    parser.add_argument('--once', type=Path, help='Generate text once from a captured event JSON file.')
    args = parser.parse_args()
    data = args.data_directory

    if args.once:
        mem = MemoryStore()
        for path in (sorted(args.once.glob('*.json')) if args.once.is_dir() else [args.once]):
            event = json.loads(path.read_text(encoding='utf-8-sig'))
            res = generate(event, mem)
            mem.record(event, res.pop('_scene'), res['text'])
            res.pop('_cost_usd', None)
            if args.once.is_dir():
                print(f"=== {path.name} ({res['elapsed_seconds']}s, {res['language']}) ===\n{res['text']}\n", flush=True)
            else:
                print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    lock = _acquire_single_instance_lock()
    if lock is None:
        print('Another companion is already running; exiting.', flush=True)
        return
    reply_file = data / 'reply.json'
    events = data / 'events.jsonl'
    events.touch(exist_ok=True)
    started_at = time.time()
    with events.open('rb') as incoming:
        base = max(0, events.stat().st_size - 32768)
        incoming.seek(base)
        chunk = incoming.read()
        nl = chunk.rfind(b'\n', 0, max(0, len(chunk) - 1))
        incoming.seek((base + nl + 1) if nl >= 0 else base)
        load_stbl_dictionary()
        memories = MemoryStore(data)
        tracker = CostTracker(data)
        print(
            f'Listening (model={CHAT_MODEL}, tts={TTS_MODEL}, total so far=${tracker.key_usage_at_start:.4f}, '
            f'key remaining=${tracker.key_limit_remaining})',
            flush=True,
        )
        last_parent_check = time.monotonic()
        while True:
            if args.parent_pid and time.monotonic() - last_parent_check > 2.0:
                last_parent_check = time.monotonic()
                if not _is_pid_running(args.parent_pid):
                    print('The game exited; companion exiting.', flush=True)
                    return
            batch = []
            while True:
                offset = incoming.tell()
                line = incoming.readline()
                if not line or not line.endswith(b'\n'):
                    incoming.seek(offset)
                    break
                batch.append(json.loads(line))
            if not batch:
                time.sleep(0.15)
                continue
            for ev_item in batch:
                if ev_item.get('type') == 'displayed':
                    audio_path = (ev_item.get('tts') or {}).get('audio_file')
                    if audio_path and float(ev_item.get('displayed_at') or 0) >= started_at - 5.0:
                        winsound.PlaySound(audio_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            candidates = [
                ev_item for ev_item in batch
                if ev_item.get('type') in ('social', 'player_chat', 'player_ask_self', 'inner_thought', 'drama_reaction', 'sim_text')
                and float(ev_item.get('observed_at') or 0) >= started_at - 15.0
            ]
            if not candidates:
                continue
            # Prefer explicit player clicks over autonomous socials or background drama reactions.
            player_cands = [c for c in candidates if c.get('type') in ('player_chat', 'player_ask_self', 'inner_thought')]
            event = player_cands[-1] if player_cands else candidates[-1]
            try:
                reply = generate(event, memories, tts_dir=TTS_DIR)
                scene = reply.pop('_scene')
                cost_usd = reply.pop('_cost_usd')
                tracker.session_usd += cost_usd
                tracker.session_exchanges += 1
                reply['cost_summary'] = tracker._summary()
            except (OSError, KeyError, IndexError, ValueError) as exc:
                reply = {'event_id': event['event_id'], 'error': str(exc)}
                scene = None
            _safe_write_json(reply_file, reply)
            if scene is not None:
                memories.record(event, scene, reply['text'])
                _safe_write_json(tracker.summary_path, reply['cost_summary'], indent=2)
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
