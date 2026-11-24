"""Observe socials, drama, and WickedWhims scenes; support player chat, Ask-Self, thoughts, and calls; display spoken banter.

Controlled from Page 1 of the Sim Pie Menu (or `banter.stop` / `banter.status` / `banter.logs` / `banter.reload`).
Model calls and speech synthesis run in the external Python 3.15 companion (companion.py),
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
_last_partner_by_sim = globals().get('_last_partner_by_sim', {})
_event_count = globals().get('_event_count', 0)
_pending = None
_alarm = None
_pie_classes = ()
_companion_proc = globals().get('_companion_proc')
_last_companion_spawn = 0.0
_seen_errors = set()
_skip_counts = globals().get('_skip_counts', {})
_drama_zone_id = globals().get('_drama_zone_id')
_active_drama_buffs = globals().get('_active_drama_buffs', set())
_last_drama_check = 0.0
_last_drama_at = 0.0
_bb_prev_value = None
_last_displayed = globals().get('_last_displayed')  # (event_id, text) of the newest shown line, for ratings.
_sex_state = {}  # WickedWhims sex instance id -> (last voiced animation id, monotonic time, climax voiced)
_last_sex_check = 0.0
_sex_check_broken = False
_ADULT_AGE_NAMES = ('YOUNGADULT', 'ADULT', 'ELDER')

_MUTE_VOICE_ACTOR = 0x7FFFFFFF
_PENDING_TIMEOUT_SECONDS = 25.0
_PASSIVE_CONTAINERS = (
    'sim_Chat', 'sim_BeAffectionate', 'SimToPet_Socials', 'simToPet_Socials_Converse',
    'petSocial_DogToDog_SocialGroup', 'petSocial_PetToPet_SocialGroup',
)
_IDLE_POSTURES = ('sim-stand', 'sim_stand_exclusive', 'sim-sit')
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
# Exclude EVERYDAY (0) and engine-internal SITUATION (7) / SPECIAL (8, WickedWhims) / BATUU (12).
_OUTFIT_NAMES = {
    1: 'FORMAL', 2: 'ATHLETIC', 3: 'SLEEP', 4: 'PARTY', 5: 'BATHING',
    6: 'CAREER', 9: 'SWIMWEAR', 10: 'HOTWEATHER', 11: 'COLDWEATHER',
}

_PROJECT_ROOT = r'C:\Users\Max\workspace\github.com\vegerot\sims-ai'
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
    # Both Sim and SimInfo expose .sim_info -> SimInfo in Sims 4.
    info = sim_or_info.sim_info
    return f'{info.first_name} {info.last_name}'.strip()


def _species_name(info):
    sp = info.extended_species or info.species
    return getattr(sp, 'name', None) or _SPECIES_NAMES.get(sp, 'HUMAN')


def _is_human(info):
    return _species_name(info) == 'HUMAN'


def _is_idle_posture(si):
    name = type(si).__name__.lower()
    return name in _IDLE_POSTURES or name.startswith('seating_sit')


def _note_partner(info_a, info_b, now):
    if _is_human(info_a) and _is_human(info_b) and int(info_a.sim_id) != int(info_b.sim_id):
        _last_partner_by_sim[int(info_a.sim_id)] = (int(info_b.sim_id), now)
        _last_partner_by_sim[int(info_b.sim_id)] = (int(info_a.sim_id), now)


def _true_voice_actor(info):
    sim_id = int(info.sim_id)
    if sim_id in _original_voice_actors:
        return _original_voice_actors[sim_id]
    current = int(info.voice_actor or 0)
    if current and current != _MUTE_VOICE_ACTOR:
        _original_voice_actors[sim_id] = current
        return current
    if not _is_human(info):
        return current
    return 1802970394 if info.gender.name == 'FEMALE' else 1685527063


def _set_voice_actor(info, actor_hash):
    if actor_hash and int(info.voice_actor or 0) != actor_hash:
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
            if info.get_sim_instance() is not None and int(info.voice_actor or 0) == _MUTE_VOICE_ACTOR:
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
        'recipe': recipe.__name__,
        'recipe_stbl': _string_hash(getattr(recipe, 'get_recipe_name', None)),
    }
    crafter_id = int(getattr(crafting, 'crafter_sim_id', 0) or 0)
    if crafter_id:
        crafter = services.sim_info_manager().get(crafter_id)
        if crafter is not None:
            out['cooked_by'] = _sim_name(crafter)
    if hasattr(obj, 'has_state'):
        q_state = CraftingTuning.QUALITY_STATE
        if q_state is not None and obj.has_state(q_state):
            q_val = obj.get_state(q_state)
            if q_val is not None:
                out['quality'] = q_val.__name__
                out['quality_stbl'] = _string_hash(getattr(q_val, 'display_name', None))
        f_state = CraftingTuning.FRESHNESS_STATE
        if f_state is not None and obj.has_state(f_state) and obj.get_state(f_state) is CraftingTuning.SPOILED_STATE_VALUE:
            out['spoiled'] = True
        m_state = CraftingTuning.MASTERWORK_STATE
        if m_state is not None and obj.has_state(m_state) and obj.get_state(m_state) is CraftingTuning.MASTERWORK_STATE_VALUE:
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


def _sim_activities(sim, info):
    if sim is None:
        return []
    activities = []
    seen_targets = set()
    for si in (sim.si_state or ()):
        if getattr(si, 'is_social', False) or _is_idle_posture(si):
            continue
        target_obj = si.target
        stbl = _string_hash(getattr(si, 'display_name', None), sim, target_obj)
        if not stbl and target_obj is None:
            continue
        if target_obj is not None:
            seen_targets.add(id(target_obj))
        activities.append(_activity_entry(type(si).__name__, stbl, target_obj))
    for aspect in (sim.posture_state.carry_aspects if sim.posture_state is not None else ()):
        carried = aspect.target if aspect is not None else None
        if carried is not None and id(carried) not in seen_targets:
            seen_targets.add(id(carried))
            activities.append(_activity_entry('carrying', None, carried))
    vs = services.venue_service()
    zd = vs.get_zone_director() if vs is not None else None
    if zd is not None and hasattr(zd, 'get_active_group_order_for_sim'):
        grp = zd.get_active_group_order_for_sim(int(info.sim_id))
        so = grp.get_sim_order(int(info.sim_id)) if grp is not None else None
        rmgr = services.get_instance_manager(sims4.resources.Types.RECIPE) if so is not None else None
        if so is not None and rmgr is not None:
            comped = bool(getattr(grp, 'is_complimentary', False))
            for rid in (so.food_recipe_id, so.drink_recipe_id):
                rec = rmgr.get(rid) if rid else None
                if rec is not None:
                    entry = {
                        'id': 'restaurant_order', 'stbl': None, 'target': None, 'target_stbl': None,
                        'recipe': rec.__name__,
                        'recipe_stbl': _string_hash(getattr(rec, 'get_recipe_name', None)),
                    }
                    if comped:
                        entry['comped'] = True
                    activities.append(entry)
    return activities[:6]


def _sim_situations(sim, info):
    if sim is None:
        return []
    sit_mgr = services.get_zone_situation_manager()
    if sit_mgr is None:
        return []
    out = []
    for sit in (sit_mgr.get_situations_sim_is_in(sim) or ()):
        sit_name = type(sit).__name__
        low = sit_name.lower()
        if any(k in low for k in ('walkby', 'single_job', 'leave', 'ungreeted', 'player_visiting', 'pivotalmoment', 'holidaysituation', '_sub_')):
            continue
        job = sit.get_current_job_for_sim(sim)
        job_stbl = _string_hash(getattr(job, 'tooltip_name', None) or getattr(job, 'display_name', None), info) if job is not None else None
        sit_stbl = _string_hash(getattr(sit, '_display_name', None))
        if bool(getattr(sit, 'is_user_facing', False)) or job_stbl or any(k in low for k in ('date', 'restaurant', 'diner', 'party', 'wedding', 'hangout', 'business')):
            out.append({
                'id': sit_name, 'stbl': sit_stbl,
                'role': job.__name__ if job is not None else None,
                'role_stbl': job_stbl,
            })
    return out[:3]


def _sim_careers(info):
    tracker = info.career_tracker
    if tracker is None:
        return []
    careers_out = []
    for career in tracker.careers.values():
        track = career.current_track_tuning
        level_tuning = career.current_level_tuning
        careers_out.append({
            'id': type(career).__name__,
            'track_id': track.__name__ if track is not None else None,
            'track_stbl': _string_hash(getattr(track, 'get_career_name', None), info) if track is not None else None,
            'title_stbl': _string_hash(getattr(level_tuning, 'get_title', None), info) if level_tuning is not None else None,
            'level': int(career.user_level or 0),
            'at_work': bool(career.currently_at_work),
        })
    return careers_out[:3]


def _sim_skills(info):
    tracker = info.commodity_tracker
    if tracker is None:
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
                'id': stat_cls.__name__,
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
    'landlord', 'tenant', 'partnersincrime', 'blinddate', 'hadlewddream',
    'hadsex', 'bff', 'good_friends', 'nemesis', 'despised', 'nolongerfriends',
)


def _scored_relations(info):
    tracker = info.relationship_tracker
    if tracker is None:
        return []
    out = []
    seen = {int(info.sim_id)}
    hh_id = info.household_id
    partner_ids = (info.spouse_sim_id, info.fiance_sim_id)
    for other in list(tracker.get_target_sim_infos()):
        if other is None:
            continue
        oid = int(other.sim_id)
        name = _sim_name(other) if oid and oid not in seen else ''
        if not name or 'do_not_remove' in name.lower():
            continue
        seen.add(oid)
        bits = [b.__name__ for b in tracker.get_all_bits(oid)]
        ot = other.relationship_tracker
        rev_bits = [b.__name__ for b in ot.get_all_bits(int(info.sim_id)) if b.__name__ not in bits] if ot is not None else []
        friendship = _friendship_score(tracker, oid)
        romance = round(float(tracker.get_relationship_score(oid, RelationshipTrack.ROMANCE_TRACK) or 0.0), 1)
        same_hh = bool(hh_id and other.household_id == hh_id)
        is_partner = oid in partner_ids
        has_story = any(k in ' '.join(bits + rev_bits).lower() for k in _STORY_REL_KEYWORDS)
        rank = (-int(is_partner), -int(same_hh), -int(has_story), -(abs(romance) + abs(friendship)))
        out.append((rank, other, {
            'id': str(oid), 'name': name, 'gender': other.gender.name, 'age': other.age.name,
            'same_household': same_hh, 'friendship': friendship, 'romance': romance,
            'bits': bits, 'reverse_bits': rev_bits,
        }))
    out.sort(key=lambda item: item[0])
    return out


def _sim_social_connections(info):
    return [
        entry for rank, _other, entry in _scored_relations(info)
        if rank[:3] != (0, 0, 0) or abs(entry['romance']) >= 15.0 or abs(entry['friendship']) >= 25.0
    ][:8]


def _sim_snapshot(sim_or_info):
    info = sim_or_info.sim_info
    # Invariant: every Sim and SimInfo exposes a concrete SimInfo via .sim_info.
    assert info is not None, 'Expected non-null SimInfo'
    sim = info.get_sim_instance()
    mood = info.get_mood()
    traits = list(info.trait_tracker.personality_traits)
    personality_names = {trait.__name__ for trait in traits}
    household = info.household
    asp = info.primary_aspiration
    buffs = [
        {
            'id': getattr(buff.buff_type, '__name__', None) or type(buff).__name__,
            'name_stbl': _string_hash(getattr(buff, 'buff_name', None), info),
            'reason_stbl': _string_hash(getattr(buff, 'buff_reason', None) or getattr(buff, 'default_buff_reason', None), info),
        }
        for buff in (info.Buffs or ()) if getattr(buff, 'visible', True)
    ]
    species_name = _species_name(info)
    breed_name = getattr(info, '_breed_name', None) or info.breed_name or None
    if callable(breed_name):
        breed_name = None
    outfit_pair = info.get_current_outfit()
    outfit_cat = int(outfit_pair[0]) if outfit_pair else None
    outfit_name = _OUTFIT_NAMES.get(outfit_cat) if species_name == 'HUMAN' else None
    pt = info.pregnancy_tracker
    pregnant = None
    if pt is not None and pt.is_pregnant:
        p_partner = pt.get_partner()
        pregnant = f'with {_sim_name(p_partner)}' if p_partner is not None else True
    return {
        'id': str(info.sim_id),
        'name': _sim_name(info),
        'age': info.age.name,
        'gender': info.gender.name,
        'species': species_name,
        'breed': str(breed_name) if breed_name else None,
        'breed_stbl': _string_hash(info.breed_name_key),
        'outfit': outfit_name,
        'pregnant': pregnant,
        'is_outside': bool(sim.is_outside) if sim is not None else False,
        'traits': [trait.__name__ for trait in traits],
        'trait_stbls': [s for s in (_string_hash(getattr(t, 'display_name', None), info) for t in traits) if s],
        'extra_traits': [
            eq.__name__ for eq in info.trait_tracker.equipped_traits
            if getattr(eq, '__name__', None) and eq.__name__ not in personality_names
        ],
        'aspiration': asp.__name__ if asp is not None else None,
        'aspiration_stbl': _string_hash(getattr(asp, 'display_text', None), info) if asp is not None else None,
        'household_funds': int(household.funds.money) if household is not None and household.funds is not None else None,
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
    assert zone is not None, 'Expected active Zone during live event capture'
    weather = None
    if include_weather:
        ss = services.season_service()
        ws = services.weather_service()
        s_raw = ss.season if ss is not None else None
        s_name = getattr(s_raw, 'name', None) or _SEASON_NAMES.get(s_raw)
        w_ev = getattr(ws, '_current_event', None) if ws is not None else None
        w_name = w_ev.__name__ if w_ev is not None else None
        if s_name or w_name:
            weather = f'{s_name}, {w_name}' if (s_name and w_name) else (s_name or w_name)
    active_venue = zone.venue_service.active_venue if zone.venue_service is not None else None
    zm_service = services.get_zone_modifier_service()
    lot_traits = [
        zm.__name__
        for zm in (zm_service.get_zone_modifiers(zone.id) if zm_service is not None else ())
        if 'mueventapm_test' not in zm.__name__.lower()
    ]
    z_proto = services.get_persistence_service().get_zone_proto_buff(zone.id)
    lot_val = _lot_value(zone.id)
    beds = int(z_proto.bedroom_count or 0) if z_proto is not None else 0
    baths = int(z_proto.bathroom_count or 0) if z_proto is not None else 0
    b_service = services.business_service()
    b_mgr = b_service.get_business_manager_for_zone(zone.id) if b_service is not None else None
    biz = None
    if b_mgr is not None:
        biz = {
            'type': getattr(b_mgr.business_type, 'name', str(b_mgr.business_type)),
            'is_open': bool(b_mgr.is_open),
            'is_owned_by_active': bool(b_mgr.owner_household_id == services.active_household_id()),
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
        'lot_name': (zone.lot.get_lot_name() or None) if zone.lot is not None else None,
        'lot_value': lot_val or None,
        'lot_rooms': f'{beds} bed / {baths} bath' if (beds or baths) else None,
        'weather': weather,
        'lot_traits': lot_traits[:6],
        'business': biz,
    }


def _relationship_snapshot(actor_info, target_info):
    bit_names = [b.__name__ for b in actor_info.relationship_tracker.get_all_bits(target_info.sim_id)]
    r_bits = [b.__name__ for b in target_info.relationship_tracker.get_all_bits(actor_info.sim_id) if b.__name__ not in bit_names]
    hh_id = actor_info.household_id
    return {
        'same_household': bool(hh_id and hh_id == target_info.household_id),
        'friendship': _friendship_score(actor_info.relationship_tracker, target_info.sim_id),
        'romance': round(actor_info.relationship_tracker.get_relationship_score(
            target_info.sim_id, RelationshipTrack.ROMANCE_TRACK), 2),
        'bits': bit_names,
        'reverse_bits': r_bits,
    }


def _social_participants(interaction):
    actor = interaction.sim
    if actor is None:
        return None, None
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
        return None, None
    if actor.sim_info.sim_id == target.sim_info.sim_id:
        return None, None
    if actor.sim_info.household_id != hh_id and target.sim_info.household_id != hh_id:
        return None, None
    return actor, target


def _nearby_sims(actor_or_info, *excluded):
    a_sim = actor_or_info.sim_info.get_sim_instance()
    if a_sim is None:
        return []
    excl = {int(x.sim_info.sim_id) for x in (actor_or_info,) + excluded if x is not None}
    apos = a_sim.position
    alevel, aout = a_sim.level, bool(a_sim.is_outside)
    near = []
    for oinfo in services.sim_info_manager().values():
        if int(oinfo.sim_id) in excl:
            continue
        osim = oinfo.get_sim_instance()
        if osim is None or osim.level != alevel or bool(osim.is_outside) != aout:
            continue
        opos = osim.position
        d2 = (apos.x - opos.x) ** 2 + (apos.z - opos.z) ** 2
        if d2 <= 100.0:
            act_stbl = None
            for si in (osim.si_state or ()):
                if not getattr(si, 'is_social', False) and not _is_idle_posture(si):
                    act_stbl = _string_hash(getattr(si, 'display_name', None), osim, si.target)
                    if act_stbl:
                        break
            near.append((d2, {
                'name': _sim_name(oinfo), 'species': _species_name(oinfo),
                'dist_m': round(d2 ** 0.5, 1), 'activity_stbl': act_stbl,
            }))
    near.sort(key=lambda item: item[0])
    return [item[1] for item in near[:4]]


def _make_event(event_type, id_prefix, actor, target, interaction_name, interaction_stbl, outcome, player_message=None):
    global _event_count
    _event_count += 1
    any_out = any(
        bool(s.sim_info.get_sim_instance().is_outside)
        for s in (actor, target) if s is not None and s.sim_info.get_sim_instance() is not None
    )
    venue = _venue_snapshot(include_weather=any_out)
    nearby = _nearby_sims(actor, target)
    event = {
        'type': event_type, 'outcome': outcome,
        'event_id': f'{id_prefix}{int(time.time() * 1000)}-{_event_count}',
        'observed_at': time.time(),
        'interaction': interaction_name, 'interaction_stbl': interaction_stbl,
        'venue': venue['id'], 'venue_stbl': venue['stbl'],
        'lot_name': venue['lot_name'], 'lot_value': venue['lot_value'], 'lot_rooms': venue['lot_rooms'],
        'weather': venue['weather'], 'lot_traits': venue['lot_traits'], 'business': venue['business'],
        'actor': _sim_snapshot(actor),
        'target': _sim_snapshot(target) if target is not None else None,
    }
    if nearby:
        event['nearby_sims'] = nearby
    if target is not None:
        event['relationship'] = _relationship_snapshot(actor.sim_info, target.sim_info)
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
    _mute_replaced([sim.sim_info for sim in sims if sim is not None], _PENDING_TIMEOUT_SECONDS)
    _record(event)
    return event


def _observe(interaction, outcome_result):
    global _last_social
    if not _enabled:
        return
    interaction_name = type(interaction).__name__
    if interaction_name in _PASSIVE_CONTAINERS:
        return
    actor, target = _social_participants(interaction)
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
    _note_partner(actor.sim_info, target.sim_info, now)
    _submit(_make_event('social', '', actor, target, interaction_name, interaction_stbl, outcome_result), actor, target)


def _check_drama_moment(now):
    global _drama_zone_id, _active_drama_buffs, _last_drama_check, _last_drama_at, _bb_prev_value
    zone = services.current_zone()
    if zone is not None and build_buy.get_user_in_build_buy(zone.id) is not None:
        if _bb_prev_value is None:
            _bb_prev_value = _lot_value(zone.id)
        return
    if not _enabled or _pending is not None or now < _audio_until or now - _last_drama_check < 4.0:
        return
    _last_drama_check = now
    if zone is None or not zone.is_zone_running:
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
                ev = _make_event('renovation_reaction', 'renov-', act, None, 'renovation_reaction', None, 'RENOVATION')
                ev['renovation_delta'] = delta
                _submit(ev, act)
                return
    seeding = _drama_zone_id != zone.id
    if seeding:
        _drama_zone_id = zone.id
    current_buffs = set()
    triggered = None
    for info in hh:
        if not _is_human(info):
            continue
        sim = info.get_sim_instance()
        sim_id = int(info.sim_id)
        if sim is None and not seeding:
            current_buffs.update(k for k in _active_drama_buffs if k[0] == sim_id)
            continue
        for buff in (info.Buffs or ()):
            if not getattr(buff, 'visible', True):
                continue
            bid = getattr(buff.buff_type, '__name__', None) or type(buff).__name__
            key = (sim_id, bid)
            current_buffs.add(key)
            if not seeding and sim is not None and triggered is None and key not in _active_drama_buffs and now - _last_drama_at >= 90.0:
                if any(k in bid.lower() for k in _DRAMA_BUFF_KEYWORDS):
                    triggered = (info, sim, buff, bid)
    _active_drama_buffs = current_buffs
    if triggered is None:
        return
    info, sim, buff, bid = triggered
    _last_drama_at = now
    low_bid = bid.lower()
    partner_rec = _last_partner_by_sim.get(int(info.sim_id))
    ev = None
    muted_sims = (sim,)
    if partner_rec is not None and now - partner_rec[1] < 900.0 and 'sexsolo' not in low_bid and any(k in low_bid for k in _INTERPERSONAL_DRAMA_KEYWORDS):
        cand = services.sim_info_manager().get(partner_rec[0])
        if cand is not None and _is_human(cand) and int(cand.sim_id) != int(info.sim_id):
            cand_sim = cand.get_sim_instance()
            if cand_sim is None:
                ev = _make_event('sim_text', 'text-', cand, sim, 'sim_text_message', None, 'SIM_TEXT')
                muted_sims = ()
            elif cand_sim.level == sim.level and (cand_sim.position.x - sim.position.x) ** 2 + (cand_sim.position.z - sim.position.z) ** 2 <= 225.0:
                ev = _make_event('drama_reaction', 'drama-', sim, cand_sim, 'drama_reaction', None, 'DRAMA_MOMENT')
                muted_sims = (sim, cand_sim)
    if ev is None:
        ev = _make_event('drama_reaction', 'drama-', sim, None, 'drama_reaction', None, 'DRAMA_MOMENT')
    ev['drama_buff'] = {
        'id': bid,
        'name_stbl': _string_hash(getattr(buff, 'buff_name', None), info),
        'reason_stbl': _string_hash(getattr(buff, 'buff_reason', None) or getattr(buff, 'default_buff_reason', None), info),
    }
    _submit(ev, *muted_sims)


def _sex_roles(inst, anim, infos):
    """{'giver', 'receiver'} when the animation acts in one direction only, so the model doesn't swap them (Grok 4.3 did).

    WickedWhims has no giver flag: each actor lists actions toward others, and its ROLE_* actor tags are unused by the
    preview animations. Live (2026-11-12): "Passionate Cunnilingus" listed only him -> her, but "Passionate Blowjob" and
    vaginal positions list both directions, so those return None and the model infers it from the animation name.
    These names come from WickedWhims' bytecode, so a mismatch records one traceback and the scene is voiced without roles.
    """
    try:
        name_by_actor = {inst.get_actor_id_with_sim_id(info.sim_id): _sim_name(info) for info in infos}
        directions = {
            (name, name_by_actor.get(action.get_receiving_actor_id()))
            for actor_id, name in name_by_actor.items() for action in anim.get_actor(actor_id).get_actor_actions()
        }
        directions = {(g, r) for g, r in directions if r is not None and r != g}
        if len(directions) != 1:
            return None
        ((giver, receiver),) = directions
        return {'giver': giver, 'receiver': receiver}
    except Exception:
        _record_error()
        return None


def _check_sex_scene(now):
    """Voice WickedWhims sex: on start, on each animation change (>= 25 s apart), and once at climax."""
    global _sex_state, _last_sex_check, _sex_check_broken
    if _sex_check_broken or not _enabled or _pending is not None or now < _audio_until or now - _last_sex_check < 2.0:
        return
    _last_sex_check = now
    try:
        from wickedwhims.sex.integral.sex_handlers.active_sex.active_sex_handlers import get_active_sex_instances
    except ImportError:  # WickedWhims isn't installed.
        _sex_check_broken = True
        return
    try:
        hh_id = services.active_household_id()
        manager = services.sim_info_manager()
        live = {}
        fire = None
        for inst in get_active_sex_instances():
            anim = inst.get_animation_instance()
            if anim is None:
                continue
            inst_id = inst.get_identifier()
            infos = [manager.get(int(sid)) for sid in inst.get_actors_as_sim_id()]
            if len(infos) < 2 or any(i is None or not _is_human(i) or i.age.name not in _ADULT_AGE_NAMES for i in infos):
                continue  # Solo, pet, or non-adult: never voiced.
            infos.sort(key=lambda i: i.household_id != hh_id)
            if infos[0].household_id != hh_id:
                continue
            anim_id = anim.get_identifier()
            category = anim.get_sex_category().name
            last_anim, last_at, climaxed = _sex_state.get(inst_id, (None, -1e9, False))
            live[inst_id] = (last_anim, last_at, climaxed)
            if fire is not None:
                continue
            if category == 'CLIMAX' and not climaxed and now - last_at >= 8.0:
                fire = (inst_id, infos, anim, anim_id, category, 'climax')
            elif anim_id != last_anim and now - last_at >= 25.0 and category != 'CLIMAX':
                fire = (inst_id, infos, anim, anim_id, category, 'start' if last_anim is None else 'change')
        _sex_state = live
        if fire is None:
            return
        inst_id, infos, anim, anim_id, category, stage = fire
        actor, target = (i.get_sim_instance() for i in infos[:2])
        if actor is None or target is None:
            return
        _sex_state[inst_id] = (anim_id, now, stage == 'climax' or _sex_state[inst_id][2])
        ev = _make_event('sex_scene', 'sex-', actor, target, 'sex_scene', None, 'SEX')
        ev['sex_stage'] = stage
        # WickedWhims' display_name is plain text for its preview animations but a LocalizedString for many pack
        # animations (e.g. Anarcis); the companion resolves its hash from the pack's own string table.
        display_name = (anim.get_original_instance() or anim).display_name
        ev['sex_animation'] = {'name': display_name if isinstance(display_name, str) else '',
                               'name_stbl': None if isinstance(display_name, str) else _string_hash(display_name),
                               'category': category, 'author': str(anim.get_author() or '')}
        ev['sex_roles'] = _sex_roles(inst, anim, infos[:2])
        _note_partner(actor.sim_info, target.sim_info, now)
        _submit(ev, actor, target)
    except Exception:
        _sex_check_broken = True  # One traceback in events.jsonl instead of one every 2 s.
        _record_error()


class _ReplyPoller:
    def poll(self, _timeline_handle):
        global _pending, _audio_until, _last_displayed
        try:
            _restore_mutes()
            if _pending is not None and time.time() - float(_pending['observed_at']) > _PENDING_TIMEOUT_SECONDS:
                _pending = None
                _restore_mutes(force=True)
            _check_drama_moment(time.monotonic())
            _check_sex_scene(time.monotonic())
            if _pending is None or not os.path.exists(_reply_path):
                return
            with open(_reply_path, encoding='utf-8-sig') as stream:
                reply = json.load(stream)
            if reply.get('event_id') != _pending['event_id']:
                return
            with contextlib.suppress(OSError):
                os.remove(_reply_path)
            event = _pending
            _pending = None
            sim_ids = [int(event['actor']['id'])] + ([int(event['target']['id'])] if event.get('target') else [])
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
            actor_name = event['actor']['name']
            etype = event.get('type')
            if etype == 'sim_text' and target_data:
                title = f"Text from {actor_name} → {target_data['name']}"
            elif etype in ('inner_thought', 'renovation_reaction'):
                suffix = 'Inner Thoughts' if etype == 'inner_thought' else 'New Decor!'
                title = f'{actor_name} ({suffix})'
                target_info = None
            elif etype == 'drama_reaction':
                title = f"{actor_name} ↔ {target_data['name']} (Big Moment!)" if target_data else f'{actor_name} (Big Moment!)'
            else:
                title = f"{actor_name} ↔ {target_data['name']}" if target_data else actor_name
                if event.get('interaction') == 'player_phone_chat':
                    title = f'{title} (Phone)'
            audio_dur = float((reply.get('tts') or {}).get('duration_seconds') or 0.0)
            now = time.monotonic()
            _audio_until = now + audio_dur
            active_muted = set(sim_ids[:int(reply.get('speaker_count') or 1)])
            for sim_id in sim_ids:
                if sim_id in _muted_until:
                    _muted_until[sim_id] = (now + audio_dur + 0.5) if (audio_dur > 0.0 and sim_id in active_muted) else 0.0
            _restore_mutes()
            shown_dur = audio_dur if audio_dur > 0.0 else max(2.0, len(reply.get('text', '')) / 18.0)
            timeout_ms = round((shown_dur + 2.0) * 1000)
            _notify(title, reply['text'], actor_info, target_info, timeout_ms=timeout_ms)
            _record(dict(reply, type='displayed', displayed_at=time.time(), timeout_duration_ms=timeout_ms))
            _last_displayed = (reply['event_id'], reply['text'])
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
    global _enabled
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
        _note_partner(a_info, t_info, time.monotonic())
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
    if actor_sim is None:
        return
    a_info = actor_sim.sim_info
    contacts = [
        other for _rank, other, entry in _scored_relations(a_info)
        if _is_human(other)
        and (not other.is_ghost or other.is_selectable)
        and (
            entry['same_household']
            or entry['friendship']
            or entry['romance']
            or any(k in ' '.join(entry['bits']).lower() for k in ('has_met', 'landlord', 'blinddate'))
        )
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
        try:
            if not getattr(dialog, 'accepted', False):
                return
            t_info = dialog.get_single_result_tag()
            if t_info is None:
                return
            _note_partner(a_info, t_info, time.monotonic())
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
        _submit(_make_event('inner_thought', 'thought-', thinker, observer, 'player_read_thoughts', None, 'PLAYER_INITIATED'), thinker)


def _rate_last_line(rating, actor_sim):
    if _last_displayed is None:
        _notify('Banter Lab', 'No line to rate yet.', actor_sim.sim_info, timeout_ms=3000)
        return
    _record({'type': 'rating', 'event_id': _last_displayed[0], 'rating': rating, 'observed_at': time.time()})
    _notify('Banter Lab', ('Loved: ' if rating > 0 else 'Bad: ') + _last_displayed[1], actor_sim.sim_info, timeout_ms=3000)


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
            if not _enabled:
                ok = guid == 0xBA47E21AB0000001 and target_obj is not None and target_obj is actor_sim
                return TestResult.TRUE if ok else TestResult(False, 'Banter disabled.')
            ok = (target_obj is not None and target_obj is actor_sim) if self_only else getattr(target_obj, 'is_sim', False)
            return TestResult.TRUE if ok else TestResult(False, 'Invalid target.')

        @flexmethod
        def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
            target_obj = inst.target if inst is not None else target
            ctx = inst.context if inst is not None else context
            actor_sim = getattr(ctx, 'sim', None) or services.get_active_sim()
            t_info = getattr(target_obj, 'sim_info', None)
            first_name = t_info.first_name if t_info is not None else 'Sim'
            return LocalizationHelperTuning.get_raw_text(label_fn(actor_sim, target_obj, first_name))

        def _run_interaction_gen(self, timeline):
            if False:
                yield None
            try:
                run_fn(self.sim or services.get_active_sim(), self.target)
            except Exception:
                _record_error()
            return True

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
                          lambda _actor, target, fname: f"{'Hear' if _is_human(target.sim_info) else 'Translate'} {fname}'s Thoughts (English)", _on_pie_thoughts),
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000001, 27, False,
                          lambda actor, target, fname: ('Disable English Banter' if _enabled else 'Enable English Banter')
                          if target is actor else f'Speak to {fname} (English)...', _on_pie_main),
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000005, 26, False,
                          lambda _actor, _target, _fname: 'Loved That Line', lambda a, _t: _rate_last_line(1, a)),
            _make_pie_cls(base_cls, affordance_mgr, 0xBA47E21AB0000006, 25, False,
                          lambda _actor, _target, _fname: 'Bad Line', lambda a, _t: _rate_last_line(-1, a)),
        )
    guids = {c.guid64 for c in _pie_classes}
    count = 0
    seen_types = set()
    for info in services.sim_info_manager().values():
        sim = info.get_sim_instance()
        if sim is None:
            continue
        if '_super_affordances' in sim.__dict__:
            del sim._super_affordances
        cls = type(sim)
        if cls not in seen_types:
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
    # Pairs with 'started', so a quiet stretch in events.jsonl can be told apart from banter being off.
    _record({'type': 'stopped', 'via': 'pie_menu' if _connection is None else 'console', 'observed_at': time.time()})
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

_record({'type': 'loaded', 'observed_at': time.time(), 'enabled': _enabled})
