"""Observe socials, support player-to-Sim and Ask-Self chat, and display spoken banter.

Controlled from Page 1 of the Sim Pie Menu (or `banter.stop` / `banter.status` / `banter.logs` / `banter.reload`).
Model calls and OpenRouter gpt-audio-mini speech synthesis run in the external Python 3.15 companion,
which this module starts automatically with `--parent-pid`.
"""

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
import clock
from distributor.ops import SetVoiceActor
from distributor.shared_messages import IconInfoData
from distributor.system import Distributor
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.interaction import Interaction
from relationships.relationship_track import RelationshipTrack
import services
import sims4.commands
from sims4.localization import LocalizationHelperTuning
from sims4.utils import flexmethod
from singletons import DEFAULT
from ui.ui_dialog_generic import UiDialogTextInputOkCancel
from ui.ui_dialog_notification import UiDialogNotification
from zone import Zone


_enabled = True
_original_voice_actors = globals().get('_original_voice_actors', {})
_muted_until = {}
_audio_until = 0.0
_last_social = None
_event_count = 0
_pending = None
_alarm = None
_pie_interaction_cls = None
_pie_ask_self_cls = None
_companion_proc = globals().get('_companion_proc')
_last_companion_spawn = 0.0
_seen_errors = set()
_skip_counts = {}

_MUTE_VOICE_ACTOR = 0x7FFFFFFF
_PENDING_TIMEOUT_SECONDS = 25.0
_PASSIVE_CONTAINERS = ('sim_Chat', 'sim_BeAffectionate', 'SimToPet_Socials', 'simToPet_Socials_Converse', 'petSocial_DogToDog_SocialGroup', 'petSocial_PetToPet_SocialGroup')
_IDLE_POSTURES = ('sim-stand', 'sim_Stand_Exclusive', 'sim-sit', 'dog_Stand', 'cat_Stand', 'dog_Sit', 'cat_Sit')
_SPECIES_NAMES = {1: 'HUMAN', 2: 'DOG', 3: 'CAT', 4: 'SMALLDOG', 5: 'FOX', 6: 'HORSE'}

_mod_directory = os.path.dirname(__file__.split('.ts4script', 1)[0])
_data_directory = os.path.join(_mod_directory, 'BanterLabData')
_reply_path = os.path.join(_data_directory, 'reply.json')
_COMPANION_PATH = r'C:\Users\Max\workspace\github.com\vegerot\ai-conversations\gaming\sims-ai\companion.py'
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
    return '{} {}'.format(info.first_name, info.last_name).strip()


def _true_voice_actor(info):
    sim_id = int(info.sim_id)
    if sim_id in _original_voice_actors:
        return _original_voice_actors[sim_id]
    current = int(getattr(info, 'voice_actor', 0))
    if current and current != _MUTE_VOICE_ACTOR:
        _original_voice_actors[sim_id] = current
        return current
    gender = str(getattr(getattr(info, 'gender', None), 'name', '')).upper()
    return 1802970394 if gender == 'FEMALE' else 1685527063


def _set_voice_actor(info, actor_hash):
    if int(getattr(info, 'voice_actor', 0)) != actor_hash:
        info.voice_actor = actor_hash
        sim = info.get_sim_instance()
        if sim is not None:
            Distributor.instance().add_op(sim, SetVoiceActor(actor_hash))


def _mute_replaced(infos, seconds):
    deadline = time.monotonic() + seconds
    for info in infos:
        if info is not None:
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


def _crafted_recipe(obj):
    crafting = getattr(obj, 'crafting_component', None)
    recipe = crafting.get_recipe() if crafting is not None and hasattr(crafting, 'get_recipe') else None
    if recipe is None:
        return None, None
    return getattr(recipe, '__name__', type(recipe).__name__), _string_hash(getattr(recipe, 'get_recipe_name', None))


def _sim_activities(sim):
    activities = []
    for si in (getattr(sim, 'si_state', None) or ()):
        if getattr(si, 'is_social', False) or type(si).__name__ in _IDLE_POSTURES:
            continue
        target_obj = getattr(si, 'target', None)
        recipe_name, recipe_stbl = _crafted_recipe(target_obj) if target_obj is not None else (None, None)
        activities.append({
            'id': type(si).__name__,
            'stbl': _string_hash(getattr(si, 'display_name', None), sim, target_obj),
            'target': type(target_obj).__name__ if target_obj is not None else None,
            'target_stbl': _string_hash(getattr(target_obj, 'catalog_name', None)) if target_obj is not None else None,
            'recipe': recipe_name,
            'recipe_stbl': recipe_stbl,
        })
    return activities[:4]


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


def _sim_social_connections(info):
    tracker = getattr(info, 'relationship_tracker', None)
    if tracker is None or not hasattr(tracker, 'get_target_sim_infos'):
        return []
    scored = []
    sim_id = int(info.sim_id)
    hh_id = getattr(info, 'household_id', None)
    partner_ids = (getattr(info, 'spouse_sim_id', None), getattr(info, 'fiance_sim_id', None))
    for other in list(tracker.get_target_sim_infos()):
        other_id = int(getattr(other, 'sim_id', 0) or 0) if other is not None else 0
        if not other_id or other_id == sim_id:
            continue
        other_name = _sim_name(other)
        if not other_name or 'do_not_remove' in other_name.lower():
            continue
        bits = [b.__name__ for b in tracker.get_all_bits(other_id)]
        other_tracker = getattr(other, 'relationship_tracker', None)
        rev_bits = [b.__name__ for b in other_tracker.get_all_bits(sim_id)
                    if b.__name__ not in bits] if other_tracker is not None else []
        friendship = _friendship_score(tracker, other_id)
        romance = round(float(tracker.get_relationship_score(other_id, RelationshipTrack.ROMANCE_TRACK)), 1)
        same_hh = bool(hh_id and getattr(other, 'household_id', None) == hh_id)
        is_partner = other_id in partner_ids
        all_lower = ' '.join(bits + rev_bits).lower()
        has_story = any(k in all_lower for k in (
            'married', 'engaged', 'significant_other', 'soulmates', 'lovers', 'exes', 'broken_up', 'divorced',
            'unfaithful', 'fellinlove', 'havebeenromantic', 'sentimentbit_', 'family_', 'isdog', 'iscat',
            'neighbor', 'landlord', 'tenant', 'coworkers', 'partnersincrime', 'blinddate', 'hadlewddream',
            'hadsex', 'bff', 'good_friends', 'nemesis', 'despised', 'nolongerfriends',
        ))
        if is_partner or same_hh or has_story or abs(romance) >= 15.0 or abs(friendship) >= 25.0:
            scored.append((-int(is_partner), -int(same_hh), -int(has_story), -(abs(romance) + abs(friendship)), {
                'id': str(other_id), 'name': other_name, 'same_household': same_hh,
                'friendship': friendship, 'romance': romance, 'bits': bits, 'reverse_bits': rev_bits,
            }))
    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored[:8]]


def _sim_snapshot(sim):
    info = sim.sim_info
    mood = info.get_mood()
    traits = list(info.trait_tracker.personality_traits)
    personality_names = {trait.__name__ for trait in traits}
    household = getattr(info, 'household', None)
    asp = getattr(info, 'primary_aspiration', None)
    buffs = [
        {
            'id': getattr(getattr(buff, 'buff_type', buff), '__name__', type(buff).__name__),
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
    return {
        'id': str(info.sim_id),
        'name': _sim_name(info),
        'age': getattr(info.age, 'name', str(info.age)),
        'gender': getattr(info.gender, 'name', str(info.gender)),
        'species': species_name,
        'breed': str(breed_name) if breed_name else None,
        'breed_stbl': _string_hash(getattr(info, 'breed_name_key', None)),
        'traits': [trait.__name__ for trait in traits],
        'trait_stbls': [s for s in (_string_hash(getattr(t, 'display_name', None), info) for t in traits) if s],
        'extra_traits': [
            eq.__name__ for eq in getattr(info.trait_tracker, 'equipped_traits', ())
            if getattr(eq, '__name__', None) and eq.__name__ not in personality_names
        ],
        'aspiration': getattr(asp, '__name__', None) if asp is not None else None,
        'household_funds': int(household.funds.money) if household is not None and getattr(household, 'funds', None) is not None else None,
        'careers': _sim_careers(info),
        'skills': _sim_skills(info),
        'mood': mood.__name__ if mood else None,
        'buffs': buffs[:8],
        'activities': _sim_activities(sim),
        'social_connections': _sim_social_connections(info),
    }


def _venue_snapshot():
    zone = services.current_zone()
    venue_service = getattr(zone, 'venue_service', None) if zone is not None else None
    active_venue = getattr(venue_service, 'active_venue', None) if venue_service is not None else None
    lot = getattr(zone, 'lot', None) if zone is not None else None
    zm_service = services.get_zone_modifier_service()
    lot_traits = [
        getattr(zm, '__name__', type(zm).__name__)
        for zm in (zm_service.get_zone_modifiers(zone.id) if zm_service is not None and zone is not None else ())
        if 'mueventapm_test' not in getattr(zm, '__name__', type(zm).__name__).lower()
    ]
    b_service = services.business_service()
    b_mgr = b_service.get_business_manager_for_zone(zone.id) if b_service is not None and zone is not None else None
    b_type = getattr(b_mgr, 'business_type', None) if b_mgr is not None else None
    return {
        'id': getattr(active_venue, '__name__', type(active_venue).__name__) if active_venue is not None else None,
        'stbl': _string_hash(getattr(active_venue, 'display_name', None)) if active_venue is not None else None,
        'lot_name': (lot.get_lot_name() or None) if lot is not None and hasattr(lot, 'get_lot_name') else None,
        'lot_traits': lot_traits[:6],
        'business': {
            'type': getattr(b_type, 'name', str(b_type)),
            'is_open': bool(getattr(b_mgr, 'is_open', False)),
            'is_owned_by_active': bool(getattr(b_mgr, 'owner_household_id', None) == services.active_household_id()),
        } if b_mgr is not None else None,
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


def _record_skip(reason, interaction_name, interaction_stbl, actor, target):
    _skip_counts[reason] = _skip_counts.get(reason, 0) + 1
    _record({
        'type': 'skipped', 'skip_reason': reason, 'observed_at': time.time(),
        'interaction': interaction_name, 'interaction_stbl': interaction_stbl,
        'actor_name': _sim_name(actor), 'target_name': _sim_name(target),
    })


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


def _make_event(event_type, id_prefix, actor, target, interaction_name, interaction_stbl, outcome, player_message=None):
    global _event_count
    _event_count += 1
    venue = _venue_snapshot()
    event = {
        'type': event_type, 'outcome': outcome,
        'event_id': '{}{}-{}'.format(id_prefix, int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': interaction_name, 'interaction_stbl': interaction_stbl,
        'venue': venue['id'], 'venue_stbl': venue['stbl'],
        'lot_name': venue['lot_name'], 'lot_traits': venue['lot_traits'], 'business': venue['business'],
        'actor': _sim_snapshot(actor),
        'target': _sim_snapshot(target) if target is not None else None,
    }
    if target is not None:
        event['relationship'] = _relationship_snapshot(actor.sim_info, target.sim_info)
    if player_message is not None:
        event['player_message'] = player_message
    return event


def _submit(event, *sims):
    global _pending
    _ensure_companion_running()
    _ensure_poller_alarm()
    if os.path.exists(_reply_path):
        try:
            os.remove(_reply_path)
        except OSError:
            pass
    _pending = dict(event, zone_id=services.current_zone_id())
    _mute_replaced([sim.sim_info for sim in sims], _PENDING_TIMEOUT_SECONDS)
    _record(event)
    return event


def _observe(interaction, outcome_result):
    global _pending, _last_social
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
    if _pending is not None and time.time() - float(_pending['observed_at']) > _PENDING_TIMEOUT_SECONDS:
        _pending = None
    if _pending is not None:
        _record_skip('pending_in_flight', interaction_name, interaction_stbl, actor, target)
        return
    if now < _audio_until:
        _record_skip('audio_playing', interaction_name, interaction_stbl, actor, target)
        return
    _last_social = (pair, interaction_name, now)
    _submit(_make_event('social', '', actor, target, interaction_name, interaction_stbl, outcome_result), actor, target)


class _ReplyPoller:
    def poll(self, _timeline_handle):
        global _enabled, _pending, _audio_until
        try:
            _restore_mutes()
            if _pending is None or not os.path.exists(_reply_path):
                return
            with open(_reply_path, encoding='utf-8-sig') as stream:
                reply = json.load(stream)
            if reply.get('event_id') != _pending['event_id']:
                return
            try:
                os.remove(_reply_path)
            except OSError:
                pass
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
            title = '{} ↔ {}'.format(event['actor']['name'], target_data['name']) if target_data else event['actor']['name']
            audio_dur = float((reply.get('tts') or {}).get('duration_seconds') or 0.0)
            now = time.monotonic()
            _audio_until = now + audio_dur
            for sim_id in sim_ids:
                if sim_id in _muted_until:
                    _muted_until[sim_id] = now + audio_dur + 0.5 if audio_dur > 0.0 else 0.0
            _restore_mutes()
            shown_dur = audio_dur if audio_dur > 0.0 else max(2.0, len(reply.get('text', '')) / 18.0)
            timeout_ms = int(round((shown_dur + 2.0) * 1000))
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
        _open_text_dialog(
            a_info, '{} → {}'.format(_sim_name(a_info), _sim_name(t_info)),
            'What does {} say to {}?'.format(a_info.first_name, t_info.first_name), t_info,
            lambda text: _submit(_make_event(
                'player_chat', 'chat-', actor_sim, target_sim, 'player_direct_chat', None,
                'PLAYER_INITIATED', player_message=text), actor_sim, target_sim))


def _on_pie_ask_self(actor_sim, _target_sim):
    if actor_sim is not None:
        a_info = actor_sim.sim_info
        _open_text_dialog(
            a_info, 'Ask {}'.format(_sim_name(a_info)),
            'Ask {} a question in English (or Hebrew / Russian):'.format(a_info.first_name), None,
            lambda text: _submit(_make_event(
                'player_ask_self', 'ask-', actor_sim, None, 'player_ask_active_sim', None,
                'PLAYER_INITIATED', player_message=text), actor_sim))


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
    global _pie_interaction_cls, _pie_ask_self_cls
    affordance_mgr = services.affordance_manager()
    base_cls = affordance_mgr.get(13142) if affordance_mgr is not None else None
    if base_cls is None:
        return 0
    if _pie_interaction_cls is None:
        _pie_interaction_cls = _make_pie_cls(
            base_cls, affordance_mgr, 0xBA47E21AB0000001, 30, False,
            lambda actor, target, fname: ('Disable English Banter' if _enabled else 'Enable English Banter')
            if target is actor else 'Speak to {} (English)...'.format(fname),
            _on_pie_main)
    if _pie_ask_self_cls is None:
        _pie_ask_self_cls = _make_pie_cls(
            base_cls, affordance_mgr, 0xBA47E21AB0000002, 29, True,
            lambda _actor, _target, fname: 'Ask {} a Question (English)...'.format(fname),
            _on_pie_ask_self)
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
            cleaned = tuple(
                sa for sa in cls._super_affordances
                if getattr(sa, 'guid64', None) not in (0xBA47E21AB0000001, 0xBA47E21AB0000002)
            )
            cls._super_affordances = cleaned + (_pie_interaction_cls, _pie_ask_self_cls)
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
            out('[Companion] {}'.format(line))


@sims4.commands.Command('banter.status', command_type=sims4.commands.CommandType.Live)
def status(_connection=None):
    cost_path = os.path.join(_data_directory, 'cost_summary.json')
    cost = json.load(open(cost_path, encoding='utf-8-sig')) if os.path.exists(cost_path) else {}
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
            sims4.commands.CheatOutput(_connection)('Banter Lab hot-reloaded ({} Sims).'.format(count))
    except Exception as exc:
        if _connection is not None:
            sims4.commands.CheatOutput(_connection)('Reload failed: {}'.format(exc))
        _record_error()


if services.current_zone() is not None:
    _install_pie_menu_interaction()
    if _enabled:
        _ensure_companion_running()
    _restore_mutes(force=True)
    _ensure_poller_alarm()

_record({'type': 'loaded', 'observed_at': time.time(), 'enabled': _enabled})
