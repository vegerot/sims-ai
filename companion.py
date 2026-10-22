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
MULTILINGUAL_CHANCE = 0.12

_stbl_cache: dict[int, str] | None = None
_sim_voice_assignments: dict[str, str] = {}

FEMALE_OPENROUTER_VOICES = ('coral', 'nova', 'shimmer', 'sage', 'ballad', 'alloy')
MALE_OPENROUTER_VOICES = ('ash', 'echo', 'onyx', 'verse', 'fable')

VOICE_ACTOR_PREFERRED_VOICE = {
    1685527063: 'ash',      # ma (Male Adult A)
    1685527060: 'onyx',     # mb (Male Adult B)
    1685527061: 'verse',    # mc (Male Adult C)
    1802970394: 'coral',    # fa (Female Adult A)
    1802970393: 'nova',     # fb (Female Adult B)
    1802970392: 'shimmer',  # fc (Female Adult C)
    1802970399: 'sage',     # fd (Female Adult D)
    1853303385: 'alloy',    # ca (Child A)
    1853303382: 'ballad',   # cb (Child B)
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


def humanize_rel_bit(
    bit: str,
    actor_name: str = 'Actor',
    target_name: str = 'Target',
    is_reverse: bool = False,
) -> str | None:
    if not bit:
        return None
    b = bit.strip()
    bl = b.lower()
    if any(x in bl for x in _NOISY_REL_BIT_SUBSTRINGS):
        return None
    subj = target_name if is_reverse else actor_name
    obj = actor_name if is_reverse else target_name

    exact_map = {
        'romantic-married': 'Married spouses',
        'romantic-engaged': 'Engaged fiancés',
        'romantic-significant_other': 'Romantic partners (Significant Others)',
        'romantic-broken_up': 'Broke up (ex-partners)',
        'romantic-divorced': 'Divorced ex-spouses',
        'romantic-hasbeenunfaithful': 'Cheated / unfaithful history',
        'romantic-havedonewoohoo_recently': 'Recently had WooHoo',
        'romantic-havedonewoohoo': 'Have had WooHoo together',
        'romantic_firstkiss': 'Shared their first kiss',
        'havebeenexes': 'Exes (used to date)',
        'havebeenromantic': 'Romantic history together',
        'hasbeenfriends': 'Used to be friends',
        'bit_nolongerfriends': 'Had a falling out (no longer friends)',
        'lifemilestonebit_fellinlove': 'Fell in love with each other',
        'shortterm_justbrokeupordivorced': 'Just broke up or divorced',
        'romanticcombo_soulmates': 'Soulmates',
        'romanticcombo_sweethearts': 'Sweethearts',
        'romanticcombo_lovebirds': 'Lovebirds',
        'romanticcombo_lovers': 'Lovers',
        'romanticcombo_romanticinterest': 'Romantic interest',
        'romanticcombo_itsveryawkward': "Romantic status: It's Very Awkward",
        'romanticcombo_badromance': 'Bad Romance',
        'romanticcombo_awkwardfriends': 'Awkward Friends',
        'romancetrope_wholesome': 'Wholesome romance dynamic',
        'romancetrope_unpredictable': 'Unpredictable / volatile romance dynamic',
        'familytrope_difficult': 'Difficult / strained family dynamic',
        'familytrope_distant': 'Distant family dynamic',
        'familytrope_close': 'Close family dynamic',
        'familytrope_jokesters': 'Jokesters family dynamic',
        'friendship-bff': 'Best Friends Forever (BFF)',
        'friendship-good_friends': 'Good friends',
        'friendship-friend': 'Friends',
        'friendship-disliked': 'Dislike each other',
        'friendship-despised': 'Despise each other',
        'friendship-nemesis': 'Sworn nemeses',
        'relationshipbits_mischief_partnersincrime': 'Partners in Crime',
        'relationshipbit_coworkers': 'Coworkers',
        'relationshipbit_compatibility_amazing': 'Amazing personality compatibility',
        'relationshipbit_compatibility_good': 'Good personality compatibility',
        'relationshipbit_compatibility_bad': 'Bad personality compatibility',
        'relationshipbit_compatibility_awful': 'Awful personality compatibility',
        'relationshipbit_fear_beingcheatedon_tracker': f'{subj} fears {obj} might cheat',
        'relationshipbit_fear_beingjudged_meantracker': f'{subj} fears being judged by {obj}',
        'relationshipbit_matchmaking_wentonblinddatewith': "Went on a blind date together (Cupid's Corner)",
        'relationshipbit_matchmaking_addedonmatchmakingapp': "Matched on Cupid's Corner dating app",
        'relationshipbit_metdisguisedalien': 'Met while disguised as an Alien',
        'relationshipbit_hsteam_rival': 'High School team rivals',
        'simtopet_relationshipbit_03_friend': 'Pet friend',
        'simtopet_relationshipbit_04_goodfriend': 'Beloved pet companion (Good Friend)',
        'relationshipbit_target_isdogownedby_actor': f"{obj} is {subj}'s pet dog",
        'relationshipbit_target_isdogownerof_actor': f"{obj} is {subj}'s human dog owner",
        'relationshipbit_target_iscatownedby_actor': f"{obj} is {subj}'s pet cat",
        'relationshipbit_target_iscatownerof_actor': f"{obj} is {subj}'s human cat owner",
        'turbodriver:wickedwhims_relbit_hadsex_7days': 'Had sex within the last 7 days',
        'turbodriver:wickedwhims_relbit_sex_relationships_lastsexpartner': f"{obj} is {subj}'s most recent sex partner",
        'turbodriver:wickedwhims_relbit_memories_memorytype_sex_firsttime': "Were each other's first-time sex partner",
        'turbodriver:wickedwhims_relbit_hadlewddreamabout': f'{subj} had a lewd dream about {obj}',
        'turbodriver:wickedwhims_relbit_attractiveness_noticed_hot': f'{subj} noticed {obj} is hot',
        'turbodriver:wickedwhims_relbit_attractiveness_visual_veryhigh': f'{subj} finds {obj} extremely attractive',
        'turbodriver:wickedwhims_relbit_attractiveness_visual_high': f'{subj} finds {obj} very attractive',
        'relbit_attraction_5_actor_veryattractedto_target': f'{subj} is very attracted to {obj}',
        'relbit_attraction_4_actor_attractedto_target': f'{subj} is attracted to {obj}',
        'relbit_attraction_2_actor_repelledby_target': f'{subj} is turned off / repelled by {obj}',
        'relbit_attraction_1_actor_veryrepelledby_target': f'{subj} is strongly repelled by {obj}',
        'relbit_relsat_4_actor_satisfiedwith_target': f'{subj} feels satisfied in relationship with {obj}',
        'relbit_relsat_2_actor_unsatisfiedwith_target': f'{subj} feels unsatisfied in relationship with {obj}',
        'relbit_relsat_1_actor_veryunsatisfiedwith_target': f'{subj} feels very unsatisfied in relationship with {obj}',
    }
    if bl in exact_map:
        return exact_map[bl]

    m_fam = re.match(r'^family_target_is([a-z]+)of_actor$', bl)
    if m_fam:
        role_raw = m_fam.group(1)
        role_map = {
            'sonordaughter': 'child (son/daughter)',
            'parent': 'parent',
            'brothersister': 'sibling',
            'halfsibling': 'half-sibling',
            'stepsibling': 'step-sibling',
            'stepparent': 'step-parent',
            'stepchild': 'step-child',
            'grandparent': 'grandparent',
            'grandchild': 'grandchild',
            'auntuncle': 'aunt/uncle',
            'niecenephew': 'niece/nephew',
            'cousin': 'cousin',
            'parentinlaw': 'parent-in-law',
            'siblinginlaw': 'sibling-in-law',
            'childinlaw': 'child-in-law',
            'relativeinlaw': 'in-law relative',
        }
        role = role_map.get(role_raw, role_raw)
        return f"{obj} is {subj}'s {role}"

    if 'familytrope_loving_target_isauthorityof_actor' in bl:
        return f'Loving family dynamic ({obj} is parent/authority to {subj})'
    if 'familytrope_loving_target_issubordinateof_actor' in bl:
        return f'Loving family dynamic ({subj} is parent/authority to {obj})'
    if 'familytrope_permissive' in bl:
        return 'Permissive family dynamic'
    if 'familytrope_compliant' in bl:
        return 'Compliant / respectful family dynamic'

    m_sent = re.match(r'^sentimentbit_actor_([a-z]+)_target_(st|lt)_([a-z0-9_]+)$', bl)
    if m_sent:
        emo_raw, dur, reason_raw = m_sent.groups()
        emo_map = {
            'bitterat': 'bitter toward',
            'furiousat': 'furious at',
            'hurtby': 'hurt by',
            'enamoredby': 'enamored with',
            'adoringto': 'adoring toward',
            'closeto': 'close to',
            'hascrushon': 'crushing on',
            'motivatedby': 'motivated by',
            'guiltyat': 'feeling guilty toward',
            'awkwardaround': 'awkward around',
        }
        reason_map = {
            'breakup': 'over their breakup',
            'cheating': 'over cheating',
            'saddened': 'after being hurt/saddened',
            'sleepcuddled': 'from cuddling in bed together',
            'movein_frommovingin': 'from moving in together',
            'qualitytime': 'from spending quality time together',
            'friendlyadvice': 'after friendly advice',
            'party': 'after a great party together',
            'impressed': 'and deeply impressed',
            'generic': '',
        }
        emo = emo_map.get(emo_raw, emo_raw)
        reason = reason_map.get(reason_raw, reason_raw.replace('_', ' '))
        dur_str = 'deeply ' if dur == 'lt' else ''
        suffix = f' ({reason})' if reason else ''
        return f'Sentiment: {subj} feels {dur_str}{emo} {obj}{suffix}'

    return None


def _summarize_rel_tags(
    bits: list[str],
    reverse_bits: list[str] | None,
    actor_name: str,
    target_name: str,
) -> list[str]:
    tags: list[str] = []
    for b in bits or []:
        label = humanize_rel_bit(b, actor_name, target_name, is_reverse=False)
        if label and label not in tags:
            tags.append(label)
    for rb in reverse_bits or []:
        label = humanize_rel_bit(rb, actor_name, target_name, is_reverse=True)
        if label and label not in tags:
            tags.append(label)
    return tags


def humanize_extra_trait(tname: str) -> tuple[str | None, str | None]:
    if not tname:
        return None, None
    t = tname.strip()
    tl = t.lower()

    m_pref = re.match(r'^trait_simpreference_(likes|dislikes)_([a-z0-9]+)_([a-z0-9_]+)$', tl)
    if m_pref:
        kind = m_pref.group(1)
        orig_item = t.split('_', 4)[-1]
        readable_item = re.sub(r'([a-z])([A-Z])', r'\1 \2', orig_item).replace('_', ' ')
        readable_cat = re.sub(r'([a-z])([A-Z])', r'\1 \2', t.split('_', 3)[3])
        if readable_cat.lower() in ('music', 'color', 'decor'):
            label = f'{readable_item} ({readable_cat.lower()})'
        else:
            label = readable_item
        return ('likes' if kind == 'likes' else 'dislikes'), label

    m_attr = re.match(r'^trait_attraction_([a-z0-9]+)_([a-z0-9_]+)_(turnon|turnoff)$', tl)
    if m_attr:
        parts = t.split('_')
        direction = 'turn_ons' if parts[-1].lower() == 'turnon' else 'turn_offs'
        cat = re.sub(r'([a-z])([A-Z])', r'\1 \2', parts[2])
        item = re.sub(r'([a-z])([A-Z])', r'\1 \2', '_'.join(parts[3:-1])).replace('_', ' ')
        return direction, f'{item} ({cat.lower()})'

    if tl.startswith('trait_fear_'):
        fear_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', t[len('trait_Fear_'):]).replace('_', ' ')
        return 'notable_traits', f'Fear of {fear_name}'

    if 'basemental:adhd' in tl or tl == 'adhd':
        return 'notable_traits', 'ADHD'
    if 'basemental:autonomy_cannabis' in tl:
        return 'notable_traits', 'Cannabis user'
    if 'basemental:parent_yell_at_teen' in tl:
        return 'notable_traits', 'Yelled at teen over drugs/behavior'
    if 'basemental:parentalreactions_suspicious' in tl:
        return 'notable_traits', 'Suspicious parent'
    m_ww = re.match(r'^turbodriver:wickedwhims_trait_personality_archetype_([a-z]+)_([a-z]+)$', tl)
    if m_ww:
        arch, deg = m_ww.groups()
        return 'notable_traits', f'{arch.title()} personality archetype ({deg})'
    if 'wickedwhims_trait_nudity_sleepnaked' in tl:
        return 'notable_traits', 'Sleeps naked'

    if tl.startswith('trait_petquirk_obsessed_'):
        item = re.sub(r'([a-z])([A-Z])', r'\1 \2', t[len('trait_PetQuirk_Obsessed_'):]).replace('_', ' ')
        return 'notable_traits', f'Pet quirk: obsessed with {item}'
    if tl.startswith('trait_petquirk_fear_'):
        item = re.sub(r'([a-z])([A-Z])', r'\1 \2', t[len('trait_PetQuirk_Fear_'):]).replace('_', ' ')
        if item.lower() == 'swiming':
            item = 'Swimming'
        return 'notable_traits', f'Pet quirk: afraid of {item}'
    pet_map = {
        'trait_misbehavior_pet_trasheat': 'Eats out of the trash',
        'trait_misbehaviors_pet_eatpeoplefood': 'Begs for and eats people food',
        'trait_misbehavior_pet_puddlesdrink': 'Drinks out of puddles',
        'trait_misbehavior_dog_bark': 'Loves barking loudly',
        'trait_misbehavior_pet_attack': 'Sometimes chases/attacks',
        'trait_misbehaviors_pet_wakeupsims': 'Wakes up sleeping Sims',
        'trait_pet_friendly_dog': 'Friendly dog',
        'trait_pet_hairy_dog': 'Fluffy/hairy coat',
        'trait_pet_friendly_cat': 'Friendly cat',
        'trait_petquirk_petbedspin': 'Spins in circles before lying down',
    }
    if tl in pet_map:
        return 'notable_traits', pet_map[tl]

    notable_map = {
        'trait_familiesim': 'Domestic (Family Sim)',
        'trait_familysim': 'Domestic (Family Sim)',
        'trait_quick_learner': 'Quick Learner',
        'trait_essenceofflavor': 'Essence of Flavor (foodie/chef)',
        'trait_business_savvy': 'Business Savvy',
        'trait_hometurf': 'Home Turf',
        'trait_collector': 'Collector',
        'trait_animal_attraction': 'Animal Affection',
        'trait_lovestruck': 'Lovestruck',
        'trait_gradeschool_a': 'Grade School A-Student',
        'trait_gradeschool_b': 'Grade School B-Student',
        'trait_gradeschool_c': 'Grade School C-Student',
        'trait_gradeschool_d': 'Grade School D-Student',
        'trait_gradeschool_f': 'Grade School F-Student',
    }
    if tl in notable_map:
        return 'notable_traits', notable_map[tl]

    return None, None


def humanize_career(career: dict, sim: dict, partner: dict | None = None) -> str | None:
    if not isinstance(career, dict):
        return None
    track_label = resolve_stbl(career.get('track_stbl'), sim, partner)
    title_label = resolve_stbl(career.get('title_stbl'), sim, partner)
    cid = str(career.get('id') or '')
    tid = str(career.get('track_id') or '')
    fallback_map = {
        'career_adult_culinary': 'Culinary',
        'career_adult_styleinfluencer': 'Style Influencer (Trend Setter)',
        'careers_adult_critic': 'Critic',
        'career_adult_sexworkercareer': 'Sex Worker',
        'careers_adult_gardener': 'Gardener',
        'career_adult_entertainer': 'Entertainer',
        'career_oddjob': 'Odd Jobs',
        'career_teen_highschool': 'High School Student',
        'careers_adult_freelancer_no_agency': 'Freelancer',
    }
    base_name = track_label or fallback_map.get(cid.lower())
    if not base_name and cid:
        cleaned_cid = re.sub(r'^careers?_(Adult|Teen)_', '', cid, flags=re.I)
        cleaned_cid = re.sub(r'Career$', '', cleaned_cid)
        base_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned_cid).replace('_', ' ').strip()
    if not base_name and tid:
        base_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', tid).replace('_', ' ').strip()
    if not base_name:
        return None
    lvl = int(career.get('level') or 0)
    parts = [base_name]
    if title_label and title_label.lower() != base_name.lower():
        parts.append(f'({title_label})')
    if lvl > 0:
        parts.append(f'Level {lvl}')
    if career.get('at_work'):
        parts.append('[currently at work]')
    return ' '.join(parts)


def humanize_skill(skill: dict, sim: dict, partner: dict | None = None) -> str | None:
    if not isinstance(skill, dict):
        return None
    label = resolve_stbl(skill.get('stbl'), sim, partner)
    sid = str(skill.get('id') or '')
    if not label and sid:
        sl = sid.lower()
        skill_map = {
            'homestylecooking': 'Homestyle Cooking',
            'gourmetcooking': 'Gourmet Cooking',
            'bartending': 'Mixology / Bartending',
            'cannabis_rollingskill': 'Cannabis Rolling',
            'sexpertise': 'Sexpertise',
            'videogaming': 'Video Gaming',
            'crossstitch': 'Cross-Stitch',
            'localculture': 'Local Culture',
        }
        for k, v in skill_map.items():
            if k in sl:
                label = v
                break
        if not label:
            cleaned_sid = re.sub(r'^(statistic_)?Skill_(Adult(Major|Minor)_)?', '', sid, flags=re.I)
            cleaned_sid = re.sub(r'_Skill$', '', cleaned_sid, flags=re.I)
            label = re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned_sid).replace('_', ' ').strip()
    if not label:
        return None
    lvl = int(skill.get('level') or 0)
    pts = float(skill.get('points') or 0.0)
    if lvl > 0:
        return f'{label} (Level {lvl})'
    if pts > 0:
        return f'{label} ({int(round(pts))} pts)'
    return label


def humanize_aspiration(asp_id: str | None, asp_stbl: int | None, sim: dict, partner: dict | None = None) -> str | None:
    label = resolve_stbl(asp_stbl, sim, partner)
    if label:
        return label
    if not asp_id:
        return None
    asp_map = {
        'track_family_superparent': 'Super Parent',
        'track_family_a': 'Successful Lineage',
        'track_animal_a': 'Friend of the Animals',
        'track_food_b': 'Master Chef / Mixologist',
        'track_knowledge_a': 'Renaissance Sim',
        'track_knowledge_b': 'Computer Whiz',
        'track_knowledge_c': 'Nerd Brain',
        'track_location_a': 'City Native',
        'track_location_beachbum': 'Beach Life',
        'track_fortune_multiunit_legendarylandlord': 'Five-Star Property Owner (Landlord)',
        'track_nature_a': 'Freelance Botanist',
    }
    al = asp_id.lower()
    if al in asp_map:
        return asp_map[al]
    cleaned = re.sub(r'^Track_', '', asp_id, flags=re.I)
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned).replace('_', ' ').strip()


def humanize_lot_trait(zname: str) -> str | None:
    if not zname:
        return None
    z = zname.strip()
    zl = z.lower()
    if 'mueventapm_test' in zl:
        return None
    lot_map = {
        'zonemodifier_lottrait_romanticatmosphere': 'Romantic Atmosphere',
        'zonemodifier_lottrait_quakezone': 'Quake Zone',
        'zonemodifier_lottrait_homey': 'Homey',
        'zonemodifier_lottrait_greatacoustics': 'Great Acoustics',
        'zonemodifier_lottrait_highspeedinternet': 'Fast Internet',
        'zonemodifier_petworld_cathangout': 'Cat Hangout',
        'zonemodifier_petworld_doghangout': 'Dog Hangout',
        'zonemodifier_lottrait_greatsoil': 'Great Soil',
        'zonemodifier_lottrait_freshair': 'Fresh Air',
        'zonemodifier_lottrait_naturallight': 'Natural Light',
        'zonemodifier_lottrait_convivial': 'Convivial',
        'zonemodifier_lottrait_notrespassing': 'Private Dwelling (No Trespassing)',
    }
    if zl in lot_map:
        return lot_map[zl]
    cleaned = re.sub(r'^zoneModifier_(lotTrait_|PetWorld_)?', '', z, flags=re.I)
    return re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned).replace('_', ' ').strip()


def _clean_sim_for_prompt(sim: dict, partner: dict | None = None) -> dict:
    cleaned = {
        k: v for k, v in sim.items()
        if k not in (
            'id', 'trait_stbls', 'extra_traits', 'aspiration', 'aspiration_stbl',
            'breed_stbl', 'careers', 'skills', 'buffs', 'activities',
            'voice_actor', 'voice_actor_muted', 'voice_pitch', 'social_connections',
        )
    }
    breed_label = resolve_stbl(sim.get('breed_stbl'), sim, partner) or sim.get('breed')
    if breed_label:
        cleaned['breed'] = breed_label
    elif 'breed' in cleaned and not cleaned['breed']:
        del cleaned['breed']
    if sim.get('mood') and str(sim['mood']).startswith('Mood_'):
        cleaned['mood_label'] = str(sim['mood'])[5:]
    trait_labels = [
        label for label in (resolve_stbl(s, sim, partner) for s in sim.get('trait_stbls', []))
        if label
    ]
    if trait_labels:
        cleaned['trait_labels'] = trait_labels
    asp_label = humanize_aspiration(sim.get('aspiration'), sim.get('aspiration_stbl'), sim, partner)
    if asp_label:
        cleaned['aspiration'] = asp_label
    career_labels = [
        cl for cl in (humanize_career(c, sim, partner) for c in sim.get('careers', []) or [])
        if cl
    ]
    if career_labels:
        cleaned['careers'] = career_labels
    skill_labels = [
        sl for sl in (humanize_skill(sk, sim, partner) for sk in sim.get('skills', []) or [])
        if sl
    ]
    if skill_labels:
        cleaned['top_skills'] = skill_labels[:6]
    extra_buckets: dict[str, list[str]] = {
        'notable_traits': [],
        'likes': [],
        'dislikes': [],
        'turn_ons': [],
        'turn_offs': [],
    }
    for et in sim.get('extra_traits', []) or []:
        bkey, blabel = humanize_extra_trait(et)
        if bkey and blabel and blabel not in extra_buckets[bkey]:
            extra_buckets[bkey].append(blabel)
    for bkey, items in extra_buckets.items():
        if items:
            cleaned[bkey] = items[:8]
    active_buffs = []
    for b in sim.get('buffs', []):
        name = resolve_stbl(b.get('name_stbl'), sim, partner)
        reason = resolve_stbl(b.get('reason_stbl'), sim, partner)
        entry = {'id': b.get('id')}
        if name:
            entry['name'] = name
        if reason:
            entry['reason'] = reason
        active_buffs.append(entry)
    if active_buffs:
        cleaned['active_buffs'] = active_buffs
    activity_labels = []
    for act in sim.get('activities', []):
        act_entry = {'id': act.get('id')}
        act_label = resolve_stbl(act.get('stbl'), sim, partner)
        if act_label:
            act_entry['label'] = act_label
        target_label = resolve_stbl(act.get('target_stbl'), sim, partner)
        if target_label:
            act_entry['target_label'] = target_label
        elif act.get('target'):
            act_entry['target'] = act['target']
        recipe_label = resolve_stbl(act.get('recipe_stbl'), sim, partner)
        if recipe_label:
            act_entry['recipe_label'] = recipe_label
        elif act.get('recipe'):
            act_entry['recipe'] = act['recipe']
        activity_labels.append(act_entry)
    if activity_labels:
        cleaned['activity_labels'] = activity_labels

    partner_id = str(partner.get('id') or '') if isinstance(partner, dict) else ''
    partner_name = str(partner.get('name') or '') if isinstance(partner, dict) else ''
    sim_name = str(sim.get('name') or 'Sim')
    connections = []
    for conn in sim.get('social_connections', []) or []:
        if not isinstance(conn, dict):
            continue
        cid = str(conn.get('id') or '')
        cname = str(conn.get('name') or '')
        if (partner_id and cid == partner_id) or (partner_name and cname == partner_name):
            continue
        tags = _summarize_rel_tags(
            conn.get('bits') or [],
            conn.get('reverse_bits') or [],
            sim_name,
            cname or 'Sim',
        )
        if conn.get('same_household') and 'Lives in same household' not in tags:
            tags.insert(0, 'Lives in same household')
        if not tags and abs(float(conn.get('romance') or 0.0)) < 20.0 and abs(float(conn.get('friendship') or 0.0)) < 35.0:
            continue
        entry = {'name': cname}
        if conn.get('friendship'):
            entry['friendship'] = conn['friendship']
        if conn.get('romance'):
            entry['romance'] = conn['romance']
        if tags:
            entry['highlights'] = tags[:8]
        connections.append(entry)
    if connections:
        cleaned['social_connections'] = connections[:6]
    return cleaned



class MemoryStore:
    """Persist per-Sim-pair and per-Sim solo dialogue history across lots and game sessions."""

    def __init__(self, data_dir: Path | None):
        self.data_dir = data_dir or (ROOT / '.local')
        self.path = self.data_dir / 'memories.json'
        self.pairs: dict[str, list[dict]] = {}
        if self.path.exists():
            self.pairs = json.loads(self.path.read_text(encoding='utf-8-sig'))['pairs']

    @staticmethod
    def make_key(actor_name: str, target_name: str | None = None) -> str:
        a = (actor_name or 'Sim').strip()
        t = (target_name or '').strip()
        if t and t != a:
            return ' :: '.join(sorted((a, t)))
        return f'solo::{a}'

    def get_memory(self, actor_name: str, target_name: str | None = None, limit: int = 4) -> list[dict]:
        key = self.make_key(actor_name, target_name)
        items = self.pairs.get(key) or []
        return items[-limit:]

    def record(self, event: dict, scene: dict, text: str) -> None:
        actor = event.get('actor') or {}
        target = event.get('target') if isinstance(event.get('target'), dict) else None
        aname = str(actor.get('name') or '').strip()
        tname = str(target.get('name') or '').strip() if target else ''
        if not aname or not text:
            return
        key = self.make_key(aname, tname)
        lst = self.pairs.setdefault(key, [])
        entry = {
            'ts': round(time.time(), 1),
            'lot': scene.get('lot_name') or scene.get('venue_label') or scene.get('venue'),
            'interaction': scene.get('interaction_label') or scene.get('interaction'),
            'outcome': scene.get('outcome'),
            'text': text.strip(),
        }
        lst.append(entry)
        if len(lst) > 8:
            del lst[:-8]
        self.save()

    def save(self) -> None:
        payload = {
            'updated_at': round(time.time(), 1),
            'pair_count': len(self.pairs),
            'pairs': self.pairs,
        }
        _safe_write_json(self.path, payload, indent=2)


class CostTracker:
    """Session cost = sum of per-call `usage.cost`; total cost = the dedicated key's usage on OpenRouter."""

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


def detect_message_language(text: str | None) -> str | None:
    if not text:
        return None
    if re.search(r'[\u0590-\u05FF]', text):
        return 'Hebrew (עברית)'
    if re.search(r'[\u0400-\u04FF]', text):
        return 'Russian (Русский)'
    return None


def choose_scene_language(event: dict) -> str:
    """Reply in the player's language; otherwise English with a small Hebrew/Russian chance."""
    msg_lang = detect_message_language(event.get('player_message'))
    if msg_lang:
        return msg_lang
    r = random.random()
    if r < MULTILINGUAL_CHANCE / 2.0:
        return 'Hebrew (עברית)'
    if r < MULTILINGUAL_CHANCE:
        return 'Russian (Русский)'
    return 'English'


def build_scene(
    event: dict,
    recent_dialogue: list[str] | None = None,
    language: str = 'English',
    pair_memory: list[dict] | None = None,
) -> dict:
    actor = event['actor']
    target = event.get('target') if isinstance(event.get('target'), dict) else None
    actor_name = actor.get('name', 'Sim')
    target_name = target.get('name', 'Sim') if target else ''

    interaction_label = resolve_stbl(event.get('interaction_stbl'), actor, target)
    venue_label = resolve_stbl(event.get('venue_stbl'), actor, target)
    if not venue_label and event.get('venue') == 'venue_MultiUnit':
        venue_label = 'Multi-Unit Residential Rental'
    lot_name = event.get('lot_name')
    lot_trait_labels = [
        lt for lt in (humanize_lot_trait(z) for z in event.get('lot_traits', []) or [])
        if lt
    ]

    event_type = event.get('type', 'social')
    speaker_count = 1 if target is None or event_type in ('solo_vocal', 'player_ask_self') else 2
    action_desc = interaction_label or event.get('interaction', 'social')
    venue_base = venue_label or event.get('venue') or 'the lot'
    venue_desc = f"{lot_name!r} ({venue_base})" if lot_name else venue_base

    if event_type == 'player_ask_self':
        summary = (
            f"The player asks {actor_name} directly: {event.get('player_message')!r} "
            f"at {venue_desc}. {actor_name} answers in the first person (1 line)."
        )
    elif event_type == 'solo_vocal' or speaker_count == 1:
        summary = (
            f"{actor_name} ({actor.get('mood', 'Fine')}) is performing solo vocal action "
            f"{action_desc!r} at {venue_desc} (outcome: {event.get('outcome') or 'SUCCESS'}). "
            f"Write 1 spoken line for {actor_name}."
        )
    elif event.get('player_message'):
        summary = (
            f"{actor_name} says to {target_name} at {venue_desc}: {event.get('player_message')!r}. "
            f"Line 1 is {actor_name}'s exact line; Line 2 is {target_name}'s response."
        )
    else:
        summary = (
            f"{actor_name} ({actor.get('mood', 'Fine')}) just performed {action_desc!r} "
            f"with {target_name} ({target.get('mood', 'Fine') if target else ''}) "
            f"at {venue_desc} (outcome: {event.get('outcome') or 'SUCCESS'})."
        )

    scene: dict = {
        'event_type': event_type,
        'speaker_count': speaker_count,
        'language': language,
        'summary': summary,
        'interaction': event.get('interaction'),
        'interaction_label': interaction_label,
        'outcome': event.get('outcome'),
        'venue': event.get('venue'),
        'venue_label': venue_label,
        'lot_name': lot_name,
        'lot_traits': lot_trait_labels if lot_trait_labels else None,
        'business': event.get('business'),
        'actor': _clean_sim_for_prompt(actor, target),
        'target': _clean_sim_for_prompt(target, actor) if target else None,
    }
    scene = {k: v for k, v in scene.items() if v is not None or k in ('target', 'outcome', 'interaction_label', 'venue_label')}
    if target and isinstance(event.get('relationship'), dict):
        raw_rel = event['relationship']
        rel = {
            k: v for k, v in raw_rel.items()
            if k not in ('bit_stbls', 'bits', 'reverse_bits', 'reverse_bit_stbls')
        }
        raw_bits = list(raw_rel.get('bits') or [])
        rev_bits = list(raw_rel.get('reverse_bits') or [])
        rel['bits'] = [
            b for b in raw_bits
            if not any(x in b.lower() for x in _NOISY_REL_BIT_SUBSTRINGS)
        ]
        labels = [resolve_stbl(s, actor, target) for s in raw_rel.get('bit_stbls', [])]
        labels += [resolve_stbl(s, target, actor) for s in raw_rel.get('reverse_bit_stbls', [])]
        bit_labels = list(dict.fromkeys(label for label in labels if label))
        if bit_labels:
            rel['bit_labels'] = bit_labels
        highlights = _summarize_rel_tags(raw_bits, rev_bits, actor_name, target_name)
        if highlights:
            rel['highlights'] = highlights
        scene['relationship'] = rel

    if event.get('player_message'):
        scene['player_message'] = event['player_message']
    if pair_memory:
        scene['pair_memory'] = pair_memory[-4:]
    if recent_dialogue:
        scene['recent_dialogue'] = recent_dialogue[-3:]
    return scene


def select_openrouter_voice(sim: dict, slot: int = 0, avoid_voice: str | None = None) -> str:
    """Assign a consistent, distinct OpenAI neural voice per Sim."""
    sim_id = str(sim.get('id') or sim.get('name') or slot)
    cached = _sim_voice_assignments.get(sim_id)
    if cached and cached != avoid_voice:
        return cached

    gender = str(sim.get('gender') or '').upper()
    pool = FEMALE_OPENROUTER_VOICES if gender == 'FEMALE' else MALE_OPENROUTER_VOICES
    va = int(sim.get('voice_actor') or 0)
    preferred = VOICE_ACTOR_PREFERRED_VOICE.get(va)

    try:
        id_num = abs(int(sim.get('id') or 0))
    except ValueError:
        id_num = sum(ord(c) for c in sim_id)

    if preferred in pool:
        base_idx = (pool.index(preferred) + (id_num % len(pool))) % len(pool)
    else:
        base_idx = (id_num + slot) % len(pool)

    chosen = pool[base_idx]
    if chosen == avoid_voice:
        chosen = pool[(base_idx + 1) % len(pool)]

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
    """True when the audio model actually read the line (it sometimes replies or refuses instead)."""
    def words(text: str) -> set[str]:
        return set(re.findall(r'\w+', text.lower()))
    spoken = words(spoken_text)
    return not spoken or len(spoken & words(transcript)) / len(spoken) >= 0.6


def _synthesize_single_line_openrouter(spoken_text: str, voice: str, mood: str) -> dict:
    clean_mood = (mood or 'Fine').replace('Mood_', '')
    tone = MOOD_TO_DELIVERY_TONE.get(clean_mood, 'natural, expressive, playful')
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
            if not ln.startswith('data: '):
                continue
            data_str = ln[6:]
            if data_str == '[DONE]':
                break
            chunk = json.loads(data_str)
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
        raise RuntimeError(f'Audio model did not read the line verbatim: {transcript!r}')
    return {
        'voice': voice,
        'tone': tone,
        'pcm': b''.join(pcm_chunks),
        'ttfa_s': ttfa,
        'ttlt_s': ttlt,
        'transcript': transcript,
        'cost_usd': float(usage.get('cost') or 0.0),
        'usage': usage,
    }


def synthesize_dialogue_openrouter(text: str, actor: dict, target: dict | None, wav_path: Path) -> dict:
    """Synthesize each line in parallel; a failed line (e.g. a refusal) is silent instead of failing the exchange."""
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
    pause_bytes = b'\x00\x00' * int(sample_rate * 0.18)
    combined_pcm = pause_bytes.join(r['pcm'] for r in line_results if r['pcm'])
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


def _normalize_dialogue_lines(raw_text: str, event: dict) -> str:
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    actor_name = (event.get('actor') or {}).get('name') or 'Sim'
    target = event.get('target')
    target_name = target.get('name') if isinstance(target, dict) else None
    event_type = event.get('type', 'social')
    player_msg = (event.get('player_message') or '').strip()

    if target is None or event_type in ('solo_vocal', 'player_ask_self'):
        first = lines[0] if lines else ''
        spoken = first.split(':', 1)[1].strip() if ':' in first else first
        spoken = spoken.strip(' "“”*')
        return f'{actor_name}: {spoken}'

    if event_type == 'player_chat' and player_msg:
        reply_line = lines[-1] if lines else ''
        spoken_reply = reply_line.split(':', 1)[1].strip() if ':' in reply_line else reply_line
        spoken_reply = spoken_reply.strip(' "“”*')
        return f'{actor_name}: {player_msg}\n{target_name}: {spoken_reply}'

    out_lines = []
    for idx, ln in enumerate(lines[:2]):
        default_speaker = actor_name if idx == 0 else (target_name or 'Sim')
        if ':' in ln:
            spk, body = ln.split(':', 1)
            out_lines.append(f"{spk.strip('* ')}: {body.strip(' \"“”*')}")
        else:
            out_lines.append(f"{default_speaker}: {ln.strip(' \"“”*')}")
    return '\n'.join(out_lines)


def generate(
    event: dict,
    memory_store: MemoryStore,
    recent_dialogue: list[str] | None = None,
    tts_dir: Path | None = None,
    cost_tracker: CostTracker | None = None,
) -> dict:
    language = choose_scene_language(event)
    actor_name = str(event['actor'].get('name') or '')
    target = event.get('target')
    pair_mem = memory_store.get_memory(actor_name, target.get('name') if target else None)
    scene = build_scene(event, recent_dialogue=recent_dialogue, language=language, pair_memory=pair_mem)
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
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _safe_write_json(target_path: Path, payload: dict, indent: int | None = None) -> None:
    """Atomic replace; retry briefly because OneDrive sync can hold the target open (observed WinError 5)."""
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


def _console_log(message: str, data_dir: Path) -> None:
    """Print, and mirror to companion_console.jsonl so the game can show it in the cheat console."""
    print(message, flush=True)
    entry = {'ts': time.time(), 'pid': os.getpid(), 'text': message}
    with (data_dir / 'companion_console.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _acquire_single_instance_lock():
    """Return an open, locked file, or None if another companion holds the lock."""
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
    recent_by_zone: dict[str, list[str]] = {}
    load_stbl_dictionary()
    memories = MemoryStore(data)
    tracker = CostTracker(data)
    _console_log(
        f'Listening (model={CHAT_MODEL}, tts={TTS_MODEL}, total so far=${tracker.key_usage_at_start:.4f}, '
        f'key remaining=${tracker.key_limit_remaining})', data)

    last_parent_check = time.monotonic()
    with events.open('r', encoding='utf-8') as incoming:
        incoming.seek(0, os.SEEK_END)
        while True:
            if args.parent_pid and time.monotonic() - last_parent_check > 2.0:
                last_parent_check = time.monotonic()
                if not _is_pid_running(args.parent_pid):
                    _console_log('The game exited; companion exiting.', data)
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
            recent = recent_by_zone.setdefault(str(event.get('venue') or 'default'), [])
            try:
                reply = generate(event, memories, recent_dialogue=recent, tts_dir=TTS_DIR, cost_tracker=tracker)
                recent.append(reply['text'])
                del recent[:-6]
            except (urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError) as exc:
                reply = {'event_id': event['event_id'], 'error': str(exc)}
            _safe_write_json(reply_file, reply)
            if 'error' in reply:
                _console_log(json.dumps(reply, ensure_ascii=False), data)
                continue
            tts = reply['tts']
            failed = [ln['error'] for ln in tts['lines'] if 'error' in ln]
            _console_log(
                f"[{reply['event_id']}] lang={reply['language']} chat={reply['elapsed_seconds']}s "
                f"tts={tts['tts_elapsed_seconds']}s audio={tts['duration_seconds']}s "
                f"voices={[ln['voice'] for ln in tts['lines']]} | session=${reply['cost_summary']['session_usd']:.4f} "
                f"total=${reply['cost_summary']['total_usd']:.4f}" + (f' | silent lines: {failed}' if failed else ''),
                data,
            )


if __name__ == '__main__':
    main()
