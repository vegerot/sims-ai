"""Observe socials, support player-to-Sim and Ask-Self chat, and display spoken banter.

Controlled from Page 1 of the Sim Pie Menu (or `banter.stop` / `banter.status` / `banter.logs` / `banter.reload`).
Model calls and OpenRouter gpt-audio-mini speech synthesis run in the external Python 3.15 companion,
which this module starts automatically with `--parent-pid`.
"""

import contextlib
import functools
import importlib
import json
import os
import subprocess
import sys
import time
import traceback
import zipimport

import alarms
import build_buy
import clock
import services
import sims4.commands
import sims4.resources
from crafting.crafting_tunable import CraftingTuning
from distributor.ops import SetVoiceActor
from distributor.shared_messages import IconInfoData
from distributor.system import Distributor
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.interaction import Interaction
from relationships.relationship_track import RelationshipTrack
from sims4.localization import LocalizationHelperTuning
from sims4.utils import flexmethod
from singletons import DEFAULT
from ui.ui_dialog_generic import UiDialogTextInputOkCancel
from ui.ui_dialog_notification import UiDialogNotification
from ui.ui_dialog_picker import SimPickerRow, UiSimPicker
from zone import Zone

_enabled = globals().get('_enabled', True)
_original_voice_actors = globals().get('_original_voice_actors', {})
_muted_until = globals().get('_muted_until', {})
_audio_until = globals().get('_audio_until', 0.0)
_last_social = globals().get('_last_social')
_last_partner_id = globals().get('_last_partner_id')
_event_count = globals().get('_event_count', 0)
_pending = None
_alarm = None
_pie_classes = ()
_companion_proc = globals().get('_companion_proc')
_last_companion_spawn = 0.0
_seen_errors = set()
_skip_counts = globals().get('_skip_counts', {})
_drama_zone_id = globals().get('_drama_zone_id')
_seen_drama_buffs = globals().get('_seen_drama_buffs', set())
_last_drama_check = 0.0
_last_drama_at = 0.0
_bb_prev_value = None

_MUTE_VOICE_ACTOR = 0x7FFFFFFF
_PENDING_TIMEOUT_SECONDS = 25.0
_PASSIVE_CONTAINERS = ('sim_Chat', 'sim_BeAffectionate', 'SimToPet_Socials', 'simToPet_Socials_Converse', 'petSocial_DogToDog_SocialGroup', 'petSocial_PetToPet_SocialGroup')
_IDLE_POSTURES = ('sim-stand', 'sim_Stand_Exclusive', 'sim-sit')
_SPECIES_NAMES = {1: 'HUMAN', 2: 'DOG', 3: 'CAT', 4: 'SMALLDOG', 5: 'FOX', 6: 'HORSE'}
_SEASON_NAMES = {0: 'SUMMER', 1: 'FALL', 2: 'WINTER', 3: 'SPRING'}
_INTERPERSONAL_DRAMA_KEYWORDS = (
    'datedebrief', 'woohoo', 'hadsex', 'afterglow', 'sexsatisfaction_', 'hadsatisfyingsex',
    'hadunsatisfyingsex', 'caughtsexcheating', 'breakup', 'broken_up', 'divorc',
    'cheated', 'unfaithful', 'engaged', 'married', 'firstkiss',
)
_DRAMA_BUFF_KEYWORDS = _INTERPERSONAL_DRAMA_KEYWORDS + (
    'fire', 'bladderfailure', 'electrocut', 'pregnancy_trimester', 'pregnancy_incoming',
    'promotion', 'demot', 'fired', 'mortified', 'hysterical', 'enraged',
    'karaokemachine_endbuff', 'food_cooking_0', 'food_experimental_3', 'burnout',
    'cannabis_smoked_', 'highon_weed_', 'alcohol_wasted_', 'hangoverbuff',
)
_OUTFIT_NAMES = {
    1: 'FORMAL', 2: 'ATHLETIC', 3: 'SLEEP', 4: 'PARTY', 5: 'BATHING',
    6: 'CAREER', 7: 'SITUATION', 8: 'SPECIAL', 9: 'SWIMWEAR', 10: 'HOTWEATHER', 11: 'COLDWEATHER',
}

_PROJECT_ROOT = r'C:\Users\Max\workspace\github.com\vegerot\ai-conversations\gaming\sims-ai'
_data_directory = os.path.join(_PROJECT_ROOT, '.local', 'data')
_reply_path = os.path.join(_data_directory, 'reply.json')
_COMPANION_PATH = os.path.join(_PROJECT_ROOT, 'companion.py')
_PYTHON = r'C:\Users\Max\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\python.exe'


class _BanterInputDialog(UiDialogTextInputOkCancel):
    def __init__(self, owner, *args, **kwargs):
        super().__init__(owner, *args, **kwargs)
        self.text_input_responses = {}

    def on_text_input(self, text_input_name='', text_input=''):
        self.text_input_responses[text_input_name] = text_input
        return True

    def build_msg(self, text_input_overrides=None, additional_tokens=(), **kwargs):
        msg = super().build_msg(additional_tokens=(), **kwargs)
        msg.text_input.add().text_input_name = 'message'
        return msg


def _record(record):
    os.makedirs(_data_directory, exist_ok=True)
    with open(os.path.join(_data_directory, 'events.jsonl'), 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def _record_error():
    tb = traceback.format_exc()
    if tb not in _seen_errors:
        _seen_errors.add(tb)
        _record({'type': 'error', 'observed_at': time.time(), 'traceback': tb})


def _string_hash(value, *tokens):
    if value is None:
        return None
    for attr in ('_string_id', 'hash'):
        h = getattr(value, attr, None)
        if isinstance(h, int) and h:
            return h
    if isinstance(value, int) and value:
        return value
    if callable(value):
        try:
            loc = value(*tokens) if tokens else value()
            h = getattr(loc, 'hash', None) or getattr(loc, '_string_id', None)
            if isinstance(h, int) and h:
                return h
        except Exception:
            pass
    return None


def _sim_name(sim_or_info):
    info = getattr(sim_or_info, 'sim_info', sim_or_info)
    return f'{info.first_name} {info.last_name}'.strip()


def _is_human(info):
    sp = getattr(info, 'extended_species', None) or getattr(info, 'species', 1)
    return getattr(sp, 'name', _SPECIES_NAMES.get(sp, 'HUMAN')) == 'HUMAN'


def _true_voice_actor(info):
    sim_id = int(info.sim_id)
    if sim_id in _original_voice_actors:
        return _original_voice_actors[sim_id]
    current = int(getattr(info, 'voice_actor', 0))
    if current and current != _MUTE_VOICE_ACTOR:
        _original_voice_actors[sim_id] = current
        return current
    if not _is_human(info):
        return current
    gender = str(getattr(getattr(info, 'gender', None), 'name', '')).upper()
    return 1802970394 if gender == 'FEMALE' else 1685527063


def _set_voice_actor(info, actor_hash):
    if actor_hash and int(getattr(info, 'voice_actor', 0)) != actor_hash:
        info.voice_actor = actor_hash
        sim = info.get_sim_instance()
        if sim is not None:
            Distributor.instance().add_op(sim, SetVoiceActor(actor_hash))


def _mute_replaced(infos, seconds):
    deadline = time.monotonic() + seconds
    for info in infos:
        # Only mute instantiated human Simlish; pets keep barks/meows and off-lot Sims make no audio.
        if info is not None and _is_human(info) and info.get_sim_instance() is not None:
            _true_voice_actor(info)
            _set_voice_actor(info, _MUTE_VOICE_ACTOR)
            _muted_until[int(info.sim_id)] = deadline


def _restore_mutes(force=False):
    now = time.monotonic()
    manager = services.sim_info_manager()
    if manager is None:
        return 0
    count = 0
    for sim_id, deadline in list(_muted_until.items()):
        if force or now >= deadline:
            del _muted_until[sim_id]
            info = manager.get(sim_id)
            if info is not None:
                _set_voice_actor(info, _true_voice_actor(info))
                count += 1
    if force:
        for info in manager.values():
            if info.get_sim_instance() is not None and int(getattr(info, 'voice_actor', 0)) == _MUTE_VOICE_ACTOR:
                _set_voice_actor(info, _true_voice_actor(info))
                count += 1
    return count


def _companion_alive():
    return _companion_proc is not None and _companion_proc.poll() is None


def _ensure_companion_running():
    global _companion_proc, _last_companion_spawn
    if _companion_alive() or time.monotonic() - _last_companion_spawn < 10.0:
        return
    _last_companion_spawn = time.monotonic()
    os.makedirs(_data_directory, exist_ok=True)
    cmd = [_PYTHON, _COMPANION_PATH, '--data-directory', _data_directory, '--parent-pid', str(os.getpid())]
    with open(os.path.join(_data_directory, 'companion.stdout.log'), 'a', encoding='utf-8') as out_f, \
         open(os.path.join(_data_directory, 'companion.stderr.log'), 'a', encoding='utf-8') as err_f:
        _companion_proc = subprocess.Popen(
            cmd, cwd=os.path.dirname(_COMPANION_PATH), stdout=out_f, stderr=err_f,
            creationflags=subprocess.CREATE_NO_WINDOW)
    _record({'type': 'companion_spawned', 'pid': _companion_proc.pid, 'observed_at': time.time()})


def _notify(title, text, owner=None, secondary_owner=None, timeout_ms=None):
    factory_kwargs = {
        'title': lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(title),
        'text': lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(text),
        'expand_behavior': UiDialogNotification.UiDialogNotificationExpandBehavior.FORCE_EXPAND,
        'visual_type': UiDialogNotification.UiDialogNotificationVisualType.SPEECH,
        'information_level': UiDialogNotification.UiDialogNotificationLevel.SIM,
    }
    if timeout_ms and int(timeout_ms) > 0:
        factory_kwargs['timeout_duration'] = int(timeout_ms)
    dialog = UiDialogNotification.TunableFactory().default(owner, **factory_kwargs)
    kwargs = {}
    if owner is not None:
        kwargs['icon_override'] = IconInfoData(obj_instance=owner)
    if secondary_owner is not None:
        kwargs['secondary_icon_override'] = IconInfoData(obj_instance=secondary_owner)
    dialog.show_dialog(**kwargs)


def _crafted_details(obj):
    crafting = getattr(obj, 'crafting_component', None)
    recipe = crafting.get_recipe() if crafting is not None and hasattr(crafting, 'get_recipe') else None
    if recipe is None:
        return {}
    out = {
        'recipe': getattr(recipe, '__name__', type(recipe).__name__),
        'recipe_stbl': _string_hash(getattr(recipe, 'get_recipe_name', None)),
    }
    crafter_id = int(getattr(crafting, 'crafter_sim_id', 0) or 0)
    if crafter_id:
        mgr = services.sim_info_manager()
        crafter = mgr.get(crafter_id) if mgr is not None else None
        if crafter is not None:
            out['cooked_by'] = _sim_name(crafter)
    if hasattr(obj, 'has_state'):
        q_state = getattr(CraftingTuning, 'QUALITY_STATE', None)
        if q_state is not None and obj.has_state(q_state):
            q_val = obj.get_state(q_state)
            if q_val is not None:
                out['quality'] = getattr(q_val, '__name__', None)
                out['quality_stbl'] = _string_hash(getattr(q_val, 'display_name', None))
        f_state = getattr(CraftingTuning, 'FRESHNESS_STATE', None)
        if f_state is not None and obj.has_state(f_state) and obj.get_state(f_state) is getattr(CraftingTuning, 'SPOILED_STATE_VALUE', None):
            out['spoiled'] = True
        m_state = getattr(CraftingTuning, 'MASTERWORK_STATE', None)
        if m_state is not None and obj.has_state(m_state) and obj.get_state(m_state) is getattr(CraftingTuning, 'MASTERWORK_STATE_VALUE', None):
            out['masterwork'] = True
    return {k: v for k, v in out.items() if v}


def _activity_entry(act_id, stbl, target_obj):
    is_sim_target = target_obj is not None and getattr(target_obj, 'is_sim', False)
    entry = {
        'id': act_id, 'stbl': stbl,
        'target': _sim_name(target_obj) if is_sim_target else (type(target_obj).__name__ if target_obj is not None else None),
        'target_stbl': None if is_sim_target else (_string_hash(getattr(target_obj, 'catalog_name', None)) if target_obj is not None else None),
    }
    if target_obj is not None:
        entry.update(_crafted_details(target_obj))
    return entry


def _sim_activities(sim, info=None):
    if sim is None:
        return []
    activities = []
    seen_targets = set()
    for si in (getattr(sim, 'si_state', None) or ()):
        if getattr(si, 'is_social', False) or type(si).__name__ in _IDLE_POSTURES:
            continue
        target_obj = getattr(si, 'target', None)
        stbl = _string_hash(getattr(si, 'display_name', None), sim, target_obj)
        if not stbl and target_obj is None:
            continue
        if target_obj is not None:
            seen_targets.add(id(target_obj))
        activities.append(_activity_entry(type(si).__name__, stbl, target_obj))
    for aspect in (getattr(getattr(sim, 'posture_state', None), 'carry_aspects', None) or ()):
        carried = getattr(aspect, 'target', None) if aspect is not None else None
        if carried is not None and id(carried) not in seen_targets:
            seen_targets.add(id(carried))
            activities.append(_activity_entry('carrying', None, carried))
    if sim is not None and info is not None:
        vs = services.venue_service()
        zd = vs.get_zone_director() if (vs is not None and hasattr(vs, 'get_zone_director')) else None
        if zd is not None and hasattr(zd, 'get_active_group_order_for_sim'):
            grp = zd.get_active_group_order_for_sim(int(info.sim_id))
            so = grp.get_sim_order(int(info.sim_id)) if grp is not None else None
            rmgr = services.get_instance_manager(sims4.resources.Types.RECIPE) if so is not None else None
            if so is not None and rmgr is not None:
                comped = bool(getattr(grp, 'is_complimentary', False))
                for rid in (getattr(so, 'food_recipe_id', None), getattr(so, 'drink_recipe_id', None)):
                    rec = rmgr.get(rid) if rid else None
                    if rec is not None:
                        entry = {'id': 'restaurant_order', 'stbl': None, 'target': None, 'target_stbl': None,
                                 'recipe': getattr(rec, '__name__', None),
                                 'recipe_stbl': _string_hash(getattr(rec, 'get_recipe_name', None))}
                        if comped:
                            entry['comped'] = True
                        activities.append(entry)
    return activities[:6]


def _sim_situations(sim, info):
    if sim is None:
        return []
    sit_mgr = services.get_zone_situation_manager()
    if sit_mgr is None or not hasattr(sit_mgr, 'get_situations_sim_is_in'):
        return []
    out = []
    for sit in (sit_mgr.get_situations_sim_is_in(sim) or ()):
        sit_name = type(sit).__name__
        low = sit_name.lower()
        if any(k in low for k in ('walkby', 'single_job', 'leave', 'ungreeted', 'player_visiting', 'pivotalmoment', 'holidaysituation', '_sub_')):
            continue
        user_facing = bool(getattr(sit, 'is_user_facing', False))
        job = sit.get_current_job_for_sim(sim) if hasattr(sit, 'get_current_job_for_sim') else None
        job_stbl = _string_hash(getattr(job, 'tooltip_name', None) or getattr(job, 'display_name', None), info) if job is not None else None
        sit_stbl = _string_hash(getattr(sit, '_display_name', None))
        if user_facing or job_stbl or any(k in low for k in ('date', 'restaurant', 'diner', 'party', 'wedding', 'hangout', 'business')):
            out.append({
                'id': sit_name, 'stbl': sit_stbl,
                'role': getattr(job, '__name__', None) if job is not None else None,
                'role_stbl': job_stbl,
            })
    return out[:3]


def _sim_careers(info):
    tracker = getattr(info, 'career_tracker', None)
    careers_out = []
    for career in (getattr(tracker, 'careers', None) or {}).values():
        track = getattr(career, 'current_track_tuning', None)
        level_tuning = getattr(career, 'current_level_tuning', None)
        careers_out.append({
            'id': getattr(career, '__name__', type(career).__name__),
            'track_id': getattr(track, '__name__', None) if track is not None else None,
            'track_stbl': _string_hash(getattr(track, 'get_career_name', None), info) if track is not None else None,
            'title_stbl': _string_hash(getattr(level_tuning, 'get_title', None), info) if level_tuning is not None else None,
            'level': int(getattr(career, 'user_level', 0) or 0),
            'at_work': bool(getattr(career, 'currently_at_work', False)),
        })
    return careers_out[:3]


def _sim_skills(info):
    tracker = getattr(info, 'commodity_tracker', None)
    if tracker is None or not hasattr(tracker, 'get_all_commodities'):
        return []
    skills_out = []
    for stat in tracker.get_all_commodities():
        if not getattr(stat, 'is_skill', False):
            continue
        stat_cls = getattr(stat, 'stat_type', type(stat))
        user_val = int(stat.get_user_value() or 0)
        raw_val = round(float(stat.get_value() or 0.0), 1)
        if user_val >= 2 or raw_val >= 500.0:
            skills_out.append((-user_val, -raw_val, {
                'id': getattr(stat_cls, '__name__', type(stat).__name__),
                'stbl': _string_hash(getattr(stat_cls, 'stat_name', None), info),
                'level': user_val,
            }))
    skills_out.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in skills_out[:6]]


def _friendship_score(tracker, other_id):
    for attr in ('FRIENDSHIP_TRACK', 'SIM_TO_PET_FRIENDSHIP_TRACK', 'PET_TO_PET_FRIENDSHIP_TRACK'):
        track = getattr(RelationshipTrack, attr, None)
        if track is not None:
            val = float(tracker.get_relationship_score(other_id, track) or 0.0)
            if val:
                return round(val, 1)
    return 0.0


_STORY_REL_KEYWORDS = (
    'married', 'engaged', 'significant_other', 'soulmates', 'lovers', 'exes', 'broken_up', 'divorced',
    'unfaithful', 'fellinlove', 'havebeenromantic', 'sentimentbit_', 'family_', 'isdog', 'iscat',
    'neighbor', 'landlord', 'tenant', 'coworkers', 'partnersincrime', 'blinddate', 'hadlewddream',
    'hadsex', 'bff', 'good_friends', 'nemesis', 'despised', 'nolongerfriends',
)


def _scored_relations(info):
    tracker = getattr(info, 'relationship_tracker', None)
    if tracker is None or not hasattr(tracker, 'get_target_sim_infos'):
        return []
    out = []
    seen = {int(info.sim_id)}
    hh_id = getattr(info, 'household_id', None)
    partner_ids = (getattr(info, 'spouse_sim_id', None), getattr(info, 'fiance_sim_id', None))
    for other in list(tracker.get_target_sim_infos()):
        oid = int(getattr(other, 'sim_id', 0) or 0) if other is not None else 0
        name = _sim_name(other) if oid and oid not in seen else ''
        if not name or 'do_not_remove' in name.lower():
            continue
        seen.add(oid)
        bits = [b.__name__ for b in tracker.get_all_bits(oid)]
        ot = getattr(other, 'relationship_tracker', None)
        rev_bits = [b.__name__ for b in ot.get_all_bits(int(info.sim_id)) if b.__name__ not in bits] if ot is not None else []
        friendship = _friendship_score(tracker, oid)
        romance = round(float(tracker.get_relationship_score(oid, RelationshipTrack.ROMANCE_TRACK) or 0.0), 1)
        same_hh = bool(hh_id and getattr(other, 'household_id', None) == hh_id)
        is_partner = oid in partner_ids
        has_story = any(k in ' '.join(bits + rev_bits).lower() for k in _STORY_REL_KEYWORDS)
        rank = (-int(is_partner), -int(same_hh), -int(has_story), -(abs(romance) + abs(friendship)))
        out.append((rank, other, {
            'id': str(oid), 'name': name, 'same_household': same_hh,
            'friendship': friendship, 'romance': romance, 'bits': bits, 'reverse_bits': rev_bits,
        }))
    out.sort(key=lambda item: item[0])
    return out


def _sim_social_connections(info):
    return [
        entry for rank, _other, entry in _scored_relations(info)
        if rank[:3] != (0, 0, 0) or abs(entry['romance']) >= 15.0 or abs(entry['friendship']) >= 25.0
    ][:8]


def _sim_snapshot(sim_or_info):
    info = getattr(sim_or_info, 'sim_info', sim_or_info)
    sim = info.get_sim_instance()
    mood = info.get_mood()
    traits = list(info.trait_tracker.personality_traits)
    personality_names = {trait.__name__ for trait in traits}
    household = getattr(info, 'household', None)
    asp = getattr(info, 'primary_aspiration', None)
    buffs = [
        {
            'id': getattr(getattr(buff, 'buff_type', None), '__name__', None) or type(buff).__name__,
            'name_stbl': _string_hash(getattr(buff, 'buff_name', None), info),
            'reason_stbl': _string_hash(getattr(buff, 'buff_reason', None) or getattr(buff, 'default_buff_reason', None)),
        }
        for buff in (getattr(info, 'Buffs', None) or ()) if getattr(buff, 'visible', True)
    ]
    species_obj = getattr(info, 'extended_species', None) or getattr(info, 'species', None)
    species_name = getattr(species_obj, 'name', None) or _SPECIES_NAMES.get(species_obj, str(species_obj or 'HUMAN'))
    breed_name = getattr(info, '_breed_name', None) or getattr(info, 'breed_name', None) or None
    if callable(breed_name):
        breed_name = None
    outfit_pair = info.get_current_outfit() if hasattr(info, 'get_current_outfit') else None
    outfit_cat = outfit_pair[0] if isinstance(outfit_pair, tuple) and outfit_pair else None
    outfit_name = getattr(outfit_cat, 'name', None) or _OUTFIT_NAMES.get(outfit_cat)
    if outfit_name == 'EVERYDAY' or species_name != 'HUMAN':
        outfit_name = None
    pt = getattr(info, 'pregnancy_tracker', None)
    pregnant = None
    if pt is not None and getattr(pt, 'is_pregnant', False):
        p_partner = pt.get_partner() if hasattr(pt, 'get_partner') else None
        pregnant = f'with {_sim_name(p_partner)}' if p_partner is not None else True
    return {
        'id': str(info.sim_id),
        'name': _sim_name(info),
        'age': getattr(info.age, 'name', str(info.age)),
        'gender': getattr(info.gender, 'name', str(info.gender)),
        'species': species_name,
        'breed': str(breed_name) if breed_name else None,
        'breed_stbl': _string_hash(getattr(info, 'breed_name_key', None)),
        'outfit': outfit_name,
        'pregnant': pregnant,
        'is_outside': bool(getattr(sim, 'is_outside', False)),
        'traits': [trait.__name__ for trait in traits],
        'trait_stbls': [s for s in (_string_hash(getattr(t, 'display_name', None), info) for t in traits) if s],
        'extra_traits': [
            eq.__name__ for eq in getattr(info.trait_tracker, 'equipped_traits', ())
            if getattr(eq, '__name__', None) and eq.__name__ not in personality_names
        ],
        'aspiration': getattr(asp, '__name__', None) if asp is not None else None,
        'aspiration_stbl': _string_hash(getattr(asp, 'display_text', None), info) if asp is not None else None,
        'household_funds': int(household.funds.money) if household is not None and getattr(household, 'funds', None) is not None else None,
        'careers': _sim_careers(info),
        'skills': _sim_skills(info),
        'mood': mood.__name__ if mood else None,
        'buffs': buffs[:8],
        'activities': _sim_activities(sim, info),
        'situations': _sim_situations(sim, info),
        'social_connections': _sim_social_connections(info),
    }


def _lot_value(zone_id):
    lv = build_buy.get_lot_value(zone_id, True) if zone_id else 0
    return int(lv[0] if isinstance(lv, tuple) and lv else (lv or 0))


def _venue_snapshot(include_weather=False):
    zone = services.current_zone()
    weather = None
    if include_weather:
        ss = services.season_service() if hasattr(services, 'season_service') else None
        ws = services.weather_service() if hasattr(services, 'weather_service') else None
        s_raw = getattr(ss, 'season', None) if ss is not None else None
        s_name = getattr(s_raw, 'name', None) or _SEASON_NAMES.get(s_raw)
        w_ev = getattr(ws, '_current_event', None) if ws is not None else None
        w_name = getattr(w_ev, '__name__', None) if w_ev is not None else None
        if s_name or w_name:
            weather = f'{s_name}, {w_name}' if (s_name and w_name) else (s_name or w_name)
    venue_service = getattr(zone, 'venue_service', None) if zone is not None else None
    active_venue = getattr(venue_service, 'active_venue', None) if venue_service is not None else None
    lot = getattr(zone, 'lot', None) if zone is not None else None
    zm_service = services.get_zone_modifier_service()
    lot_traits = [
        getattr(zm, '__name__', type(zm).__name__)
        for zm in (zm_service.get_zone_modifiers(zone.id) if zm_service is not None and zone is not None else ())
        if 'mueventapm_test' not in getattr(zm, '__name__', type(zm).__name__).lower()
    ]
    persistence = services.get_persistence_service()
    z_proto = persistence.get_zone_proto_buff(zone.id) if (persistence is not None and zone is not None) else None
    lot_val = _lot_value(zone.id) if zone is not None else 0
    beds = int(getattr(z_proto, 'bedroom_count', 0) or 0) if z_proto is not None else 0
    baths = int(getattr(z_proto, 'bathroom_count', 0) or 0) if z_proto is not None else 0
    b_service = services.business_service()
    b_mgr = b_service.get_business_manager_for_zone(zone.id) if b_service is not None and zone is not None else None
    biz = None
    if b_mgr is not None:
        b_type = getattr(b_mgr, 'business_type', None)
        biz = {
            'type': getattr(b_type, 'name', str(b_type)),
            'is_open': bool(getattr(b_mgr, 'is_open', False)),
            'is_owned_by_active': bool(getattr(b_mgr, 'owner_household_id', None) == services.active_household_id()),
        }
        if getattr(getattr(b_mgr, 'tuning_data', None), 'min_and_max_star_rating', None) is not None and hasattr(b_mgr, 'get_star_rating'):
            stars = round(float(b_mgr.get_star_rating()), 1)
            if stars > 0.0:
                biz['star_rating'] = stars
        if getattr(b_mgr, 'rent', 0):
            biz['daily_rent'] = int(b_mgr.rent)
        owed = int(b_mgr.get_currently_owed_rent()) if hasattr(b_mgr, 'get_currently_owed_rent') else 0
        if owed > 0:
            biz['owed_rent'] = owed
    return {
        'id': getattr(active_venue, '__name__', type(active_venue).__name__) if active_venue is not None else None,
        'stbl': _string_hash(getattr(active_venue, 'display_name', None)) if active_venue is not None else None,
        'lot_name': (lot.get_lot_name() or None) if lot is not None and hasattr(lot, 'get_lot_name') else None,
        'lot_value': lot_val or None,
        'lot_rooms': f'{beds} bed / {baths} bath' if (beds or baths) else None,
        'weather': weather,
        'lot_traits': lot_traits[:6],
        'business': biz,
    }


def _relationship_snapshot(actor_info, target_info):
    bit_names = [b.__name__ for b in actor_info.relationship_tracker.get_all_bits(target_info.sim_id)]
    r_bits = [b.__name__ for b in target_info.relationship_tracker.get_all_bits(actor_info.sim_id) if b.__name__ not in bit_names]
    hh_id = getattr(actor_info, 'household_id', None)
    return {
        'same_household': bool(hh_id and hh_id == getattr(target_info, 'household_id', None)),
        'friendship': _friendship_score(actor_info.relationship_tracker, target_info.sim_id),
        'romance': round(actor_info.relationship_tracker.get_relationship_score(
            target_info.sim_id, RelationshipTrack.ROMANCE_TRACK), 2),
        'bits': bit_names,
        'reverse_bits': r_bits,
    }


def _social_participants(interaction):
    actor = interaction.sim
    if actor is None:
        return None, None, None
    target = interaction.get_participant(ParticipantType.TargetSim)
    is_soc = bool(getattr(interaction, 'is_social', False))
    hh_id = services.active_household_id()
    if is_soc and (target is None or not getattr(target, 'is_sim', False)):
        listeners = [s for s in interaction.get_participants(ParticipantType.Listeners)
                     if getattr(s, 'is_sim', False) and s.sim_info.sim_id != actor.sim_info.sim_id]
        if listeners:
            target = next((s for s in listeners if s.sim_info.household_id == hh_id), listeners[0])
    if not is_soc and target is not None and getattr(target, 'is_sim', False):
        iname = type(interaction).__name__.lower()
        is_soc = any(k in iname for k in ('petsocial', 'simtopet', 'talkto', 'praise', 'scold', 'lecture', 'calm', 'pamper'))
    if not is_soc or target is None or not getattr(target, 'is_sim', False):
        return None, None, None
    if actor.sim_info.sim_id == target.sim_info.sim_id:
        return None, None, None
    if actor.sim_info.household_id != hh_id and target.sim_info.household_id != hh_id:
        return None, None, None
    bystander = None
    group = getattr(interaction, 'social_group', None)
    if group is not None:
        pair_ids = {actor.sim_info.sim_id, target.sim_info.sim_id}
        others = [s for s in group if getattr(s, 'is_sim', False) and s.sim_info.sim_id not in pair_ids]
        if others:
            others.sort(key=lambda s: (
                0 if (s.sim_info.household_id == hh_id and not _is_human(s.sim_info)) else
                1 if s.sim_info.household_id == hh_id else 2
            ))
            bystander = others[0]
    return actor, target, bystander


def _nearby_sims(actor_or_info, *excluded):
    a_sim = getattr(actor_or_info, 'sim_info', actor_or_info).get_sim_instance()
    if a_sim is None:
        return []
    excl = {int(getattr(x, 'sim_info', x).sim_id) for x in (actor_or_info,) + excluded if x is not None}
    apos = a_sim.position
    alevel, aout = a_sim.level, bool(getattr(a_sim, 'is_outside', False))
    near = []
    for oinfo in services.sim_info_manager().values():
        if int(oinfo.sim_id) in excl:
            continue
        osim = oinfo.get_sim_instance()
        if osim is None or osim.level != alevel or bool(getattr(osim, 'is_outside', False)) != aout:
            continue
        opos = osim.position
        d2 = (apos.x - opos.x) ** 2 + (apos.z - opos.z) ** 2
        if d2 <= 100.0:
            sp_obj = getattr(oinfo, 'extended_species', None) or getattr(oinfo, 'species', None)
            sp_name = getattr(sp_obj, 'name', None) or _SPECIES_NAMES.get(sp_obj, 'HUMAN')
            act_stbl = None
            for si in (getattr(osim, 'si_state', None) or ()):
                if not getattr(si, 'is_social', False) and type(si).__name__ not in _IDLE_POSTURES:
                    act_stbl = _string_hash(getattr(si, 'display_name', None), osim, getattr(si, 'target', None))
                    if act_stbl:
                        break
            near.append((d2, {'name': _sim_name(oinfo), 'species': sp_name, 'dist_m': round(d2 ** 0.5, 1), 'activity_stbl': act_stbl}))
    near.sort(key=lambda item: item[0])
    return [item[1] for item in near[:4]]


def _make_event(event_type, id_prefix, actor, target, interaction_name, interaction_stbl, outcome, player_message=None, bystander=None):
    global _event_count
    _event_count += 1
    any_out = any(getattr(getattr(s, 'sim_info', s).get_sim_instance(), 'is_outside', False) for s in (actor, target, bystander) if s is not None)
    venue = _venue_snapshot(include_weather=any_out)
    nearby = _nearby_sims(actor, target, bystander)
    event = {
        'type': event_type, 'outcome': outcome,
        'event_id': f'{id_prefix}{int(time.time() * 1000)}-{_event_count}',
        'observed_at': time.time(),
        'interaction': interaction_name, 'interaction_stbl': interaction_stbl,
        'venue': venue['id'], 'venue_stbl': venue['stbl'],
        'lot_name': venue['lot_name'], 'lot_value': venue['lot_value'], 'lot_rooms': venue['lot_rooms'], 'weather': venue['weather'], 'lot_traits': venue['lot_traits'], 'business': venue['business'],
        'actor': _sim_snapshot(actor),
        'target': _sim_snapshot(target) if target is not None else None,
    }
    if nearby:
        event['nearby_sims'] = nearby
    if bystander is not None:
        event['bystander'] = _sim_snapshot(bystander)
    if target is not None:
        event['relationship'] = _relationship_snapshot(getattr(actor, 'sim_info', actor), getattr(target, 'sim_info', target))
    if player_message is not None:
        event['player_message'] = player_message
    return event


def _submit(event, *sims):
    global _pending
    _ensure_companion_running()
    _ensure_poller_alarm()
    with contextlib.suppress(OSError):
        os.remove(_reply_path)
    _pending = dict(event, zone_id=services.current_zone_id())
    _mute_replaced([getattr(sim, 'sim_info', sim) for sim in sims if sim is not None], _PENDING_TIMEOUT_SECONDS)
    _record(event)
    return event


def _observe(interaction, outcome_result):
    global _pending, _last_social, _last_partner_id
    if not _enabled:
        return
    interaction_name = type(interaction).__name__
    if interaction_name in _PASSIVE_CONTAINERS:
        return
    actor, target, bystander = _social_participants(interaction)
    if actor is None:
        return
    interaction_stbl = _string_hash(getattr(interaction, 'display_name', None), actor, target)
    if not interaction_stbl:
        return
    pair = frozenset((int(actor.sim_info.sim_id), int(target.sim_info.sim_id)))
    now = time.monotonic()
    if _last_social is not None and _last_social[0] == pair and _last_social[1] == interaction_name and now - _last_social[2] < 45.0:
        return
    if _pending is not None:
        _skip_counts['pending_in_flight'] = _skip_counts.get('pending_in_flight', 0) + 1
        return
    if now < _audio_until:
        _skip_counts['audio_playing'] = _skip_counts.get('audio_playing', 0) + 1
        return
    _last_social = (pair, interaction_name, now)
    hh_id = services.active_household_id()
    partner_sim = target if actor.sim_info.household_id == hh_id else actor
    if _is_human(partner_sim.sim_info):
        _last_partner_id = (int(partner_sim.sim_info.sim_id), now)
    _submit(_make_event('social', '', actor, target, interaction_name, interaction_stbl, outcome_result, bystander=bystander),
            actor, target, bystander)


def _check_drama_moment(now):
    global _drama_zone_id, _last_drama_check, _last_drama_at, _bb_prev_value
    zone = services.current_zone()
    if zone is not None and hasattr(build_buy, 'get_user_in_build_buy') and build_buy.get_user_in_build_buy(zone.id) is not None:
        if _bb_prev_value is None:
            _bb_prev_value = _lot_value(zone.id)
        return
    if not _enabled or _pending is not None or now < _audio_until or now - _last_drama_check < 4.0:
        return
    _last_drama_check = now
    if zone is None or not getattr(zone, 'is_zone_running', False):
        return
    hh = services.active_household()
    if hh is None:
        return
    if _bb_prev_value is not None:
        delta = _lot_value(zone.id) - _bb_prev_value
        _bb_prev_value = None
        if abs(delta) >= 500 and now - _last_drama_at >= 60.0:
            act = services.get_active_sim()
            if act is None or not _is_human(act.sim_info) or act.sim_info.household_id != hh.id:
                act = next((i.get_sim_instance() for i in hh if _is_human(i) and i.get_sim_instance() is not None), None)
            if act is not None:
                _last_drama_at = now
                ev = _make_event('drama_reaction', 'renov-', act, None, 'renovation_reaction', None, 'RENOVATION')
                ev['renovation_delta'] = delta
                _submit(ev, act)
                return
    seeding = _drama_zone_id != zone.id
    if seeding:
        _drama_zone_id = zone.id
    for info in hh:
        sim = info.get_sim_instance()
        if sim is None or not _is_human(info):
            continue
        for buff in (getattr(info, 'Buffs', None) or ()):
            if not getattr(buff, 'visible', True):
                continue
            bid = getattr(getattr(buff, 'buff_type', None), '__name__', None) or type(buff).__name__
            key = (int(info.sim_id), bid)
            if key in _seen_drama_buffs:
                continue
            _seen_drama_buffs.add(key)
            if not seeding and now - _last_drama_at >= 90.0 and any(k in bid.lower() for k in _DRAMA_BUFF_KEYWORDS):
                _last_drama_at = now
                sender_info = None
                low_bid = bid.lower()
                if _last_partner_id is not None and now - _last_partner_id[1] < 900.0 and 'sexsolo' not in low_bid and any(k in low_bid for k in _INTERPERSONAL_DRAMA_KEYWORDS):
                    mgr = services.sim_info_manager()
                    cand = mgr.get(_last_partner_id[0]) if mgr is not None else None
                    if cand is not None and _is_human(cand) and int(cand.sim_id) != int(info.sim_id) and (cand.household_id != hh.id or cand.get_sim_instance() is None):
                        sender_info = cand
                if sender_info is not None:
                    ev = _make_event('sim_text', 'text-', sender_info, sim, 'sim_text_message', None, 'SIM_TEXT')
                else:
                    ev = _make_event('drama_reaction', 'drama-', sim, None, 'drama_reaction', None, 'DRAMA_MOMENT')
                ev['drama_buff'] = {
                    'id': bid,
                    'name_stbl': _string_hash(getattr(buff, 'buff_name', None), info),
                    'reason_stbl': _string_hash(getattr(buff, 'buff_reason', None) or getattr(buff, 'default_buff_reason', None)),
                }
                _submit(ev)
                return


class _ReplyPoller:
    def poll(self, _timeline_handle):
        global _pending, _audio_until
        try:
            _restore_mutes()
            if _pending is not None and time.time() - float(_pending['observed_at']) > _PENDING_TIMEOUT_SECONDS:
                _pending = None
                _restore_mutes(force=True)
            _check_drama_moment(time.monotonic())
            if _pending is None or not os.path.exists(_reply_path):
                return
            with open(_reply_path, encoding='utf-8-sig') as stream:
                reply = json.load(stream)
            if reply.get('event_id') != _pending['event_id']:
                with contextlib.suppress(OSError):
                    os.remove(_reply_path)
                return
            with contextlib.suppress(OSError):
                os.remove(_reply_path)
            event = _pending
            _pending = None
            sim_ids = [int(event['actor']['id'])] + ([int(event['target']['id'])] if event.get('target') else [])
            if event.get('bystander'):
                sim_ids.append(int(event['bystander']['id']))
            if services.current_zone_id() != event['zone_id'] or 'error' in reply:
                _restore_mutes(force=True)
                if 'error' in reply:
                    _record(dict(reply, type='error', observed_at=time.time()))
                    if services.current_zone_id() == event['zone_id'] and event.get('type') != 'social':
                        _notify('Banter Lab', 'Could not generate reply ({}).'.format(reply['error']),
                                services.active_sim_info(), timeout_ms=5000)
                return
            manager = services.sim_info_manager()
            actor_info = manager.get(sim_ids[0])
            target_data = event.get('target')
            target_info = manager.get(sim_ids[1]) if target_data else None
            bystander_data = event.get('bystander')
            used_bystander = bool(bystander_data and int(reply.get('speaker_count') or 0) >= 3)
            etype = event.get('type')
            if etype == 'sim_text' and target_data:
                title = 'Text from {} → {}'.format(event['actor']['name'], target_data['name'])
            elif etype in ('inner_thought', 'drama_reaction'):
                suffix = 'Inner Thoughts' if etype == 'inner_thought' else ('New Decor!' if event.get('renovation_delta') else 'Big Moment!')
                title = '{} ({})'.format(event['actor']['name'], suffix)
                target_info = None
            else:
                title = '{} ↔ {}'.format(event['actor']['name'], target_data['name']) if target_data else event['actor']['name']
                if event.get('interaction') == 'player_phone_chat':
                    title = '{} (Phone)'.format(title)
                elif used_bystander:
                    title = '{} (+ {})'.format(title, bystander_data['name'])
            audio_dur = float((reply.get('tts') or {}).get('duration_seconds') or 0.0)
            now = time.monotonic()
            _audio_until = now + audio_dur
            active_muted = set(sim_ids if used_bystander else sim_ids[:2])
            for sim_id in sim_ids:
                if sim_id in _muted_until:
                    _muted_until[sim_id] = (now + audio_dur + 0.5) if (audio_dur > 0.0 and sim_id in active_muted) else 0.0
            _restore_mutes()
            shown_dur = audio_dur if audio_dur > 0.0 else max(2.0, len(reply.get('text', '')) / 18.0)
            timeout_ms = round((shown_dur + 2.0) * 1000)
            _notify(title, reply['text'], actor_info, target_info, timeout_ms=timeout_ms)
            _record(dict(reply, type='displayed', displayed_at=time.time(), timeout_duration_ms=timeout_ms))
        except Exception:
            _record_error()


_poller = _ReplyPoller()


def _ensure_poller_alarm():
    global _alarm
    if _alarm is None:
        _alarm = alarms.add_alarm_real_time(
            _poller, clock.interval_in_real_seconds(0.35), _poller.poll, repeating=True, cross_zone=True)


def _cancel_polling():
    global _alarm, _pending
    if _alarm is not None:
        alarms.cancel_alarm(_alarm)
        _alarm = None
    _pending = None


def _open_text_dialog(owner_info, title, prompt, secondary_info, on_text):
    def _on_response(dialog):
        try:
            text_val = dialog.text_input_responses.get('message', '').strip()
            if getattr(dialog, 'accepted', False) and text_val:
                on_text(text_val)
        except Exception:
            _record_error()

    dialog = _BanterInputDialog.TunableFactory().default(
        owner_info,
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(title),
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(prompt),
    )
    dialog.add_listener(_on_response)
    icons = {'icon_override': IconInfoData(obj_instance=owner_info)}
    if secondary_info is not None:
        icons['secondary_icon_override'] = IconInfoData(obj_instance=secondary_info)
    dialog.show_dialog(**icons)


def _on_pie_main(actor_sim, target_sim):
    global _enabled, _last_partner_id
    if actor_sim is None or target_sim is None:
        return
    if target_sim is actor_sim:
        if _enabled:
            stop()
            _notify('Banter Lab', 'English Banter turned off.', actor_sim.sim_info)
        else:
            _enabled = True
            _cancel_polling()
            _ensure_poller_alarm()
            _ensure_companion_running()
            _record({'type': 'started', 'observed_at': time.time()})
            _notify('Banter Lab', 'English Banter is on! Sims will now speak contextual English during socials.',
                    actor_sim.sim_info)
    elif getattr(target_sim, 'is_sim', False):
        a_info, t_info = actor_sim.sim_info, target_sim.sim_info
        if _is_human(t_info):
            _last_partner_id = (int(t_info.sim_id), time.monotonic())
        _open_text_dialog(
            a_info, f'{_sim_name(a_info)} → {_sim_name(t_info)}',
            f'What does {a_info.first_name} say to {t_info.first_name}?', t_info,
            lambda text: _submit(_make_event(
                'player_chat', 'chat-', actor_sim, target_sim, 'player_direct_chat', None,
                'PLAYER_INITIATED', player_message=text), actor_sim, target_sim))


def _on_pie_ask_self(actor_sim, _target_sim):
    if actor_sim is not None:
        a_info = actor_sim.sim_info
        _open_text_dialog(
            a_info, f'Ask {_sim_name(a_info)}',
            f'Ask {a_info.first_name} a question in English (or Hebrew / Russian):', None,
            lambda text: _submit(_make_event(
                'player_ask_self', 'ask-', actor_sim, None, 'player_ask_active_sim', None,
                'PLAYER_INITIATED', player_message=text), actor_sim))


def _on_pie_call_someone(actor_sim, _target_sim):
    global _last_partner_id
    if actor_sim is None:
        return
    a_info = actor_sim.sim_info
    contacts = [
        other for _rank, other, _entry in _scored_relations(a_info)
        if _is_human(other) and (not getattr(other, 'is_ghost', False) or getattr(other, 'is_selectable', False))
    ]
    if not contacts:
        _notify('Banter Lab', f'{a_info.first_name} has not met anyone to call or text yet!', a_info, timeout_ms=4500)
        return
    picker = UiSimPicker.TunableFactory().default(
        a_info,
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(f'Call / Text from {_sim_name(a_info)}'),
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text('Choose someone to call or text:'),
    )
    for other in contacts[:24]:
        picker.add_row(SimPickerRow(other.sim_id, tag=other))

    def _on_picked(dialog):
        global _last_partner_id
        try:
            if not getattr(dialog, 'accepted', False):
                return
            t_info = dialog.get_single_result_tag()
            if t_info is None:
                return
            _last_partner_id = (int(t_info.sim_id), time.monotonic())
            t_target = t_info.get_sim_instance() or t_info
            _open_text_dialog(
                a_info, f'{_sim_name(a_info)} → {_sim_name(t_info)} (Phone)',
                f'What does {a_info.first_name} say or text to {t_info.first_name}?', t_info,
                lambda text: _submit(_make_event(
                    'player_chat', 'phone-', actor_sim, t_target, 'player_phone_chat', None,
                    'PLAYER_INITIATED', player_message=text), actor_sim, t_target))
        except Exception:
            _record_error()

    picker.show_dialog(on_response=_on_picked)


def _on_pie_thoughts(actor_sim, target_sim):
    thinker = target_sim if (target_sim is not None and getattr(target_sim, 'is_sim', False)) else actor_sim
    if thinker is not None:
        observer = actor_sim if (actor_sim is not None and actor_sim is not thinker) else None
        _submit(_make_event('inner_thought', 'thought-', thinker, observer, 'player_read_thoughts', None, 'PLAYER_INITIATED'))


def _make_pie_cls(base_cls, affordance_mgr, guid, priority, self_only, label_fn, run_fn):
    class _PieInteraction(base_cls):
        guid64 = guid
        cheat = False
        debug = False
        simless = False
        allow_user_directed = True
        category = None
        pie_menu_priority = priority

        @classmethod
        def _tunable_tests_enabled(cls):
            return False

        @flexmethod
        def test(cls, inst, *args, target=DEFAULT, context=DEFAULT, **kwargs):
            target_obj = inst.target if inst is not None else target
            ctx = inst.context if inst is not None else context
            actor_sim = getattr(ctx, 'sim', None) or services.get_active_sim()
            ok = (target_obj is not None and target_obj is actor_sim) if self_only else getattr(target_obj, 'is_sim', False)
            return TestResult.TRUE if ok else TestResult(False, 'Invalid target.')

        @flexmethod
        def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
            target_obj = inst.target if inst is not None else target
            ctx = inst.context if inst is not None else context
            actor_sim = getattr(ctx, 'sim', None) or services.get_active_sim()
            first_name = getattr(getattr(target_obj, 'sim_info', target_obj), 'first_name', 'Sim')
            return LocalizationHelperTuning.get_raw_text(label_fn(actor_sim, target_obj, first_name))

        def _run_interaction_gen(self, timeline):
            if False:
                yield None
            try:
                run_fn(self.sim or services.get_active_sim(), self.target)
            except Exception:
                _record_error()
            return True

    if hasattr(affordance_mgr, '_tuned_classes'):
        affordance_mgr._tuned_classes[guid] = _PieInteraction
    return _PieInteraction


def _install_pie_menu_interaction():
    global _pie_classes
    affordance_mgr = services.affordance_manager()
    base_cls = affordance_mgr.get(13142) if affordance_mgr is not None else None
    if base_cls is None:
        return 0
    if not _pie_classes:
        _pie_classes = (
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000004, 30, True,
                          lambda _actor, _target, _fname: 'Call / Text Someone (English)...', _on_pie_call_someone),
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000002, 29, True,
                          lambda _actor, _target, fname: f'Ask {fname} a Question (English)...', _on_pie_ask_self),
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000003, 28, False,
                          lambda _actor, target, fname: f"{'Hear' if _is_human(getattr(target, 'sim_info', target)) else 'Translate'} {fname}'s Thoughts (English)", _on_pie_thoughts),
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000001, 27, False,
                          lambda actor, target, fname: ('Disable English Banter' if _enabled else 'Enable English Banter')
                          if target is actor else f'Speak to {fname} (English)...', _on_pie_main),
        )
    guids = {c.guid64 for c in _pie_classes}
    count = 0
    seen_types = set()
    for info in services.sim_info_manager().values():
        sim = info.get_sim_instance()
        if sim is None:
            continue
        if '_super_affordances' in getattr(sim, '__dict__', ()):
            del sim._super_affordances
        cls = type(sim)
        if cls not in seen_types and hasattr(cls, '_super_affordances'):
            seen_types.add(cls)
            cls._super_affordances = tuple(sa for sa in cls._super_affordances if getattr(sa, 'guid64', None) not in guids) + _pie_classes
        count += 1
    return count


_original_store_outcome = getattr(Interaction, '_banter_orig_outcome', Interaction.store_result_for_outcome)
_original_zone_loaded = getattr(Zone, '_banter_orig_zone_loaded', Zone.on_loading_screen_animation_finished)

Interaction._banter_orig_outcome = _original_store_outcome
Zone._banter_orig_zone_loaded = _original_zone_loaded


@functools.wraps(_original_store_outcome)
def _on_store_outcome(self, outcome, result, *args, **kwargs):
    ret = _original_store_outcome(self, outcome, result, *args, **kwargs)
    try:
        _observe(self, getattr(result, 'name', str(result)))
    except Exception:
        _record_error()
    return ret


@functools.wraps(_original_zone_loaded)
def _on_zone_loaded(self, *args, **kwargs):
    ret = _original_zone_loaded(self, *args, **kwargs)
    try:
        count = _install_pie_menu_interaction()
        if _enabled:
            _ensure_companion_running()
        restored = _restore_mutes(force=True)
        _cancel_polling()
        _ensure_poller_alarm()
        _record({'type': 'pie_menu_installed', 'sims': count, 'restored_voices': restored,
                 'enabled': _enabled, 'observed_at': time.time()})
    except Exception:
        _record_error()
    return ret


Interaction.store_result_for_outcome = _on_store_outcome
Zone.on_loading_screen_animation_finished = _on_zone_loaded


@sims4.commands.Command('banter.stop', command_type=sims4.commands.CommandType.Live)
def stop(_connection=None):
    global _enabled, _pending, _audio_until, _last_social
    _enabled = False
    _pending = None
    _audio_until = 0.0
    _last_social = None
    _restore_mutes(force=True)
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)('Banter Lab stopped and Simlish voices restored.')


@sims4.commands.Command('banter.logs', command_type=sims4.commands.CommandType.Live)
def logs_command(_connection=None):
    if _connection is None:
        return
    out = sims4.commands.CheatOutput(_connection)
    log_path = os.path.join(_data_directory, 'companion.stdout.log')
    if not os.path.exists(log_path):
        out('No companion logs recorded yet.')
        return
    with open(log_path, encoding='utf-8-sig') as stream:
        for line in [ln for ln in stream.read().splitlines() if ln.strip()][-10:]:
            out(f'[Companion] {line}')


@sims4.commands.Command('banter.status', command_type=sims4.commands.CommandType.Live)
def status(_connection=None):
    cost_path = os.path.join(_data_directory, 'cost_summary.json')
    cost = {}
    if os.path.exists(cost_path):
        with open(cost_path, encoding='utf-8-sig') as stream:
            cost = json.load(stream)
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)(
            'Banter Lab: enabled={}, companion_alive={}, observed={}, skipped={}, cost(session=${:.4f}, total=${:.4f})'.format(
                _enabled, _companion_alive(), _event_count, _skip_counts,
                cost.get('session_usd', 0.0), cost.get('total_usd', 0.0)))


@sims4.commands.Command('banter.reload', command_type=sims4.commands.CommandType.Live)
def reload_command(_connection=None):
    try:
        _cancel_polling()
        zipimport._zip_directory_cache.clear()
        sys.path_importer_cache.clear()
        mod = importlib.reload(sys.modules[__name__])
        count = mod._install_pie_menu_interaction()
        if _connection is not None:
            sims4.commands.CheatOutput(_connection)(f'Banter Lab hot-reloaded ({count} Sims).')
    except Exception as exc:
        if _connection is not None:
            sims4.commands.CheatOutput(_connection)(f'Reload failed: {exc}')
        _record_error()


if services.current_zone() is not None:
    _install_pie_menu_interaction()
    if _enabled:
        _ensure_companion_running()
    _restore_mutes(force=True)
    _ensure_poller_alarm()

_ev_file = os.path.join(_data_directory, 'events.jsonl')
if os.path.exists(_ev_file) and os.path.getsize(_ev_file) > 2097152:
    with open(_ev_file, 'rb') as _ef:
        _ef.seek(-262144, os.SEEK_END)
        _tail = _ef.read()
    _nl = _tail.find(b'\n')
    with open(_ev_file, 'wb') as _ef:
        _ef.write(_tail[_nl + 1:] if _nl >= 0 else _tail)

_record({'type': 'loaded', 'observed_at': time.time(), 'enabled': _enabled})
