"""Observe actual socials and solo vocalizations, support player-to-Sim and Ask-Self chat, and display contextual dialogue.

Dormant until enabled via Pie Menu or console (`banter.ai`, `banter.start`, `banter.talk`, `banter.say`, `banter.ask`, `banter.solo`).
Model calls, cost tracking, and OpenRouter gpt-audio-mini speech synthesis run in the external Python 3.15 companion.
"""

import functools
import importlib
import json
import os
import sys
import time
import traceback
import zipimport

import alarms
import clock
from distributor.ops import SetVoiceActor
from distributor.shared_messages import IconInfoData
from distributor.system import Distributor
import services
import sims4.commands
from audio.primitive import PlaySound
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.interaction import Interaction
from interactions.base.super_interaction import SuperInteraction
from sims4.utils import flexmethod
from singletons import DEFAULT
from zone import Zone
from relationships.relationship_track import RelationshipTrack
from sims.sim_spawner import SimSpawner
from sims4.localization import LocalizationHelperTuning
from ui.ui_dialog_generic import UiDialogTextInputOkCancel
from ui.ui_dialog_notification import UiDialogNotification


_enabled = False
_trace = False
_mute_simlish = False
_original_voice_actors = {}
_last_shown = 0.0
_last_solo_shown = 0.0
_event_count = 0
_mode = 'fixed'
_trigger_on = 'outcome'
_pending = None
_alarm = None
_reply_path = None
_audio_probe = None
_pie_interaction_cls = None
_pie_ask_self_cls = None
_MUTE_VOICE_ACTOR = 0x7FFFFFFF
_COOLDOWN_SECONDS = 3.0
_PASSIVE_CONTAINERS = ('sim_Chat', 'sim_BeAffectionate')
_UNLABELLED_WAVES = ('socialMixer_Greetings_Wave', 'nonTouching_Unpaired_Greeting_Wave')
_IDLE_POSTURES = ('sim-stand', 'sim_Stand_Exclusive', 'sim-sit')
_SOLO_VOCAL_STBLS = (4013856058, 961384365, 3515527490, 2952163771)
_SOLO_VOCAL_SUBSTRINGS = (
    'forbiddenwords',
    'shoutforbidden',
    'practicespeech',
    'practiceacting',
    'practiceroutine',
    'sing',
    'karaoke',
    'microphone',
    'complain',
    'talktoself',
    'talk_to_self',
    'tantrum',
    'cryitout',
    'yellat',
)
_skip_counts = {}
_vox_stats = {'total': 0, 'covered_by_english': 0, 'unreplaced': 0}
_last_english_by_sim = {}
# Zip-imported modules have a path inside the .ts4script archive.
_data_directory = os.path.join(os.path.dirname(__file__.split('.ts4script', 1)[0]), 'BanterLabData')


class _BanterInputDialog(UiDialogTextInputOkCancel):
    """In-game modal text input dialog for speaking directly to a Sim."""

    def __init__(self, owner, *args, **kwargs):
        super().__init__(owner, *args, **kwargs)
        self.text_input_responses = {}

    def on_text_input(self, text_input_name='', text_input=''):
        self.text_input_responses[text_input_name] = text_input
        return False

    def build_msg(self, text_input_overrides=None, additional_tokens=(), **kwargs):
        msg = super().build_msg(additional_tokens=(), **kwargs)
        text_input_msg = msg.text_input.add()
        text_input_msg.text_input_name = 'message'
        return msg


def _record(record):
    os.makedirs(_data_directory, exist_ok=True)
    with open(os.path.join(_data_directory, 'events.jsonl'), 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def _string_hash(value, *tokens):
    if value is None:
        return None
    if isinstance(value, int) and value:
        return value
    string_id = getattr(value, '_string_id', None)
    if isinstance(string_id, int) and string_id:
        return string_id
    hash_val = getattr(value, 'hash', None)
    if isinstance(hash_val, int) and hash_val:
        return hash_val
    if callable(value):
        try:
            loc = value(*tokens) if tokens else value()
            hash_val = getattr(loc, 'hash', None) or getattr(loc, '_string_id', None)
            if isinstance(hash_val, int) and hash_val:
                return hash_val
        except Exception:
            pass
    return None


def _true_voice_actor(info):
    if info.sim_id in _original_voice_actors:
        return _original_voice_actors[info.sim_id]
    return int(getattr(info, 'voice_actor', 0))


def _distribute_voice_actor(info, actor_hash):
    info.voice_actor = actor_hash
    sim = info.get_sim_instance()
    if sim is not None:
        Distributor.instance().add_op(sim, SetVoiceActor(actor_hash))


def _apply_mute_to_info(info):
    if info is None:
        return
    current = int(getattr(info, 'voice_actor', 0))
    if info.sim_id not in _original_voice_actors and current != _MUTE_VOICE_ACTOR:
        _original_voice_actors[info.sim_id] = current
    if current != _MUTE_VOICE_ACTOR:
        _distribute_voice_actor(info, _MUTE_VOICE_ACTOR)


def _sync_zone_mute():
    manager = services.sim_info_manager()
    if manager is None:
        return 0
    count = 0
    if _mute_simlish:
        for info in manager.values():
            if info.get_sim_instance() is not None:
                _apply_mute_to_info(info)
                count += 1
    else:
        for sim_id, orig_actor in list(_original_voice_actors.items()):
            info = manager.get(sim_id)
            if info is not None:
                _distribute_voice_actor(info, orig_actor)
                count += 1
            _original_voice_actors.pop(sim_id, None)
    return count


def _notify(title, text, owner=None, secondary_owner=None):
    dialog = UiDialogNotification.TunableFactory().default(
        owner,
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(title),
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(text),
        expand_behavior=UiDialogNotification.UiDialogNotificationExpandBehavior.FORCE_EXPAND,
        visual_type=UiDialogNotification.UiDialogNotificationVisualType.SPEECH,
        information_level=UiDialogNotification.UiDialogNotificationLevel.SIM,
    )
    kwargs = {}
    if owner is not None:
        kwargs['icon_override'] = IconInfoData(obj_instance=owner)
    if secondary_owner is not None:
        kwargs['secondary_icon_override'] = IconInfoData(obj_instance=secondary_owner)
    dialog.show_dialog(**kwargs)


def _sim_activities(sim):
    activities = []
    si_state = getattr(sim, 'si_state', None)
    if si_state is None:
        return activities
    for si in si_state:
        if getattr(si, 'is_social', False):
            continue
        si_name = type(si).__name__
        if si_name in _IDLE_POSTURES:
            continue
        target_obj = getattr(si, 'target', None)
        target_stbl = _string_hash(getattr(target_obj, 'catalog_name', None)) if target_obj is not None else None
        recipe_name = None
        recipe_stbl = None
        crafting = getattr(target_obj, 'crafting_component', None) if target_obj is not None else None
        if crafting is not None and hasattr(crafting, 'get_recipe'):
            try:
                recipe = crafting.get_recipe()
                if recipe is not None:
                    recipe_name = getattr(recipe, '__name__', type(recipe).__name__)
                    recipe_stbl = _string_hash(getattr(recipe, 'get_recipe_name', None))
            except Exception:
                pass
        activities.append({
            'id': si_name,
            'stbl': _string_hash(getattr(si, 'display_name', None), sim, target_obj),
            'target': type(target_obj).__name__ if target_obj is not None else None,
            'target_stbl': target_stbl,
            'recipe': recipe_name,
            'recipe_stbl': recipe_stbl,
        })
    posture_state = getattr(sim, 'posture_state', None)
    for carried in (getattr(posture_state, 'carry_targets', ()) if posture_state is not None else ()):
        if carried is None or getattr(carried, 'is_sim', False):
            continue
        recipe_name = None
        recipe_stbl = None
        crafting = getattr(carried, 'crafting_component', None)
        if crafting is not None and hasattr(crafting, 'get_recipe'):
            try:
                recipe = crafting.get_recipe()
                if recipe is not None:
                    recipe_name = getattr(recipe, '__name__', type(recipe).__name__)
                    recipe_stbl = _string_hash(getattr(recipe, 'get_recipe_name', None))
            except Exception:
                pass
        activities.append({
            'id': 'carrying',
            'stbl': None,
            'target': type(carried).__name__,
            'target_stbl': _string_hash(getattr(carried, 'catalog_name', None)),
            'recipe': recipe_name,
            'recipe_stbl': recipe_stbl,
        })
    return activities[:4]


def _sim_snapshot(sim):
    info = sim.sim_info
    mood = info.get_mood()
    traits = list(info.trait_tracker.personality_traits)
    trait_stbls = []
    for trait in traits:
        stbl = _string_hash(getattr(trait, 'display_name', None), info)
        if stbl:
            trait_stbls.append(stbl)
    buffs = []
    buff_component = getattr(info, 'Buffs', None)
    if buff_component is not None:
        for buff in buff_component:
            if not getattr(buff, 'visible', True):
                continue
            buffs.append({
                'id': getattr(getattr(buff, 'buff_type', buff), '__name__', type(buff).__name__),
                'name_stbl': _string_hash(getattr(buff, 'buff_name', None), info),
                'reason_stbl': _string_hash(
                    getattr(buff, 'buff_reason', None) or getattr(buff, 'default_buff_reason', None)),
            })
    return {
        'id': str(info.sim_id),
        'name': '{} {}'.format(info.first_name, info.last_name).strip(),
        'age': getattr(info.age, 'name', str(info.age)),
        'gender': getattr(info.gender, 'name', str(info.gender)),
        'voice_actor': _true_voice_actor(info),
        'voice_actor_muted': int(getattr(info, 'voice_actor', 0)) == _MUTE_VOICE_ACTOR,
        'voice_pitch': round(float(getattr(info, 'voice_pitch', 0.0)), 4),
        'traits': [trait.__name__ for trait in traits],
        'trait_stbls': trait_stbls,
        'mood': mood.__name__ if mood else None,
        'mood_intensity': info.get_mood_intensity(),
        'buffs': buffs[:5],
        'activities': _sim_activities(sim),
    }


def _venue_snapshot():
    zone = services.current_zone()
    venue_service = getattr(zone, 'venue_service', None) if zone is not None else None
    active_venue = getattr(venue_service, 'active_venue', None) if venue_service is not None else None
    if active_venue is None:
        return {'id': None, 'stbl': None}
    return {
        'id': getattr(active_venue, '__name__', type(active_venue).__name__),
        'stbl': _string_hash(getattr(active_venue, 'display_name', None)),
    }


def _relationship_snapshot(actor_info, target_info):
    bits = list(actor_info.relationship_tracker.get_all_bits(target_info.sim_id))
    bit_stbls = []
    for bit in bits:
        stbl = _string_hash(getattr(bit, 'display_name', None), actor_info, target_info)
        if stbl:
            bit_stbls.append(stbl)
    return {
        'friendship': round(actor_info.relationship_tracker.get_relationship_score(
            target_info.sim_id, RelationshipTrack.FRIENDSHIP_TRACK), 2),
        'romance': round(actor_info.relationship_tracker.get_relationship_score(
            target_info.sim_id, RelationshipTrack.ROMANCE_TRACK), 2),
        'bits': [bit.__name__ for bit in bits],
        'bit_stbls': bit_stbls,
    }


def _mark_english_for_sims(*sims):
    now = time.monotonic()
    for sim in sims:
        if sim is not None and getattr(sim, 'sim_info', None) is not None:
            _last_english_by_sim[sim.sim_info.sim_id] = now


def _record_skip(reason, interaction, actor=None, target=None, extra=None, log_to_file=True):
    _skip_counts[reason] = _skip_counts.get(reason, 0) + 1
    if not log_to_file and not _trace:
        return
    actor_name = None
    if actor is not None and getattr(actor, 'sim_info', None) is not None:
        actor_name = '{} {}'.format(actor.sim_info.first_name, actor.sim_info.last_name).strip()
    target_name = None
    if target is not None and getattr(target, 'sim_info', None) is not None:
        target_name = '{} {}'.format(target.sim_info.first_name, target.sim_info.last_name).strip()
    rec = {
        'type': 'skipped',
        'skip_reason': reason,
        'observed_at': time.time(),
        'interaction': type(interaction).__name__,
        'interaction_stbl': _string_hash(getattr(interaction, 'display_name', None), actor, target),
        'is_social': bool(getattr(interaction, 'is_social', False)),
        'is_super': bool(getattr(interaction, 'is_super', False)),
        'actor_name': actor_name,
        'target_name': target_name,
    }
    if extra:
        rec.update(extra)
    _record(rec)


def _social_participants(interaction):
    if not getattr(interaction, 'is_social', False):
        return None, None
    actor = interaction.sim
    target = interaction.get_participant(ParticipantType.TargetSim)
    if actor is None or target is None or not getattr(target, 'is_sim', False):
        return None, None
    if actor.sim_info.sim_id == target.sim_info.sim_id:
        return None, None
    household_id = services.active_household_id()
    if actor.sim_info.household_id != household_id and target.sim_info.household_id != household_id:
        return None, None
    return actor, target


def _solo_vocal_actor(interaction):
    """Identify solo/self vocal interactions (such as Shout Forbidden Words) by the active household."""
    actor = getattr(interaction, 'sim', None)
    if actor is None or getattr(actor, 'sim_info', None) is None:
        return None
    if actor.sim_info.household_id != services.active_household_id():
        return None
    target = interaction.get_participant(ParticipantType.TargetSim)
    if target is not None and getattr(target, 'is_sim', False) and target.sim_info.sim_id != actor.sim_info.sim_id:
        return None
    name_low = type(interaction).__name__.lower()
    if name_low in _IDLE_POSTURES:
        return None
    stbl_hash = _string_hash(getattr(interaction, 'display_name', None), actor)
    if stbl_hash in _SOLO_VOCAL_STBLS:
        return actor
    for sub in _SOLO_VOCAL_SUBSTRINGS:
        if sub in name_low:
            return actor
    return None


def _trace_lifecycle(interaction, stage, extra=None):
    if not _trace:
        return
    actor, target = _social_participants(interaction)
    if actor is None:
        actor = _solo_vocal_actor(interaction)
    if actor is None:
        return
    target_name = None
    if target is not None:
        target_name = '{} {}'.format(target.sim_info.first_name, target.sim_info.last_name).strip()
    record = {
        'type': 'trace',
        'stage': stage,
        'observed_at': time.time(),
        'interaction': type(interaction).__name__,
        'interaction_stbl': _string_hash(getattr(interaction, 'display_name', None), actor, target),
        'is_super': bool(getattr(interaction, 'is_super', False)),
        'actor_name': '{} {}'.format(actor.sim_info.first_name, actor.sim_info.last_name).strip(),
        'target_name': target_name,
    }
    if extra:
        record.update(extra)
    _record(record)


def _observe_solo_vocal(interaction, actor, hook_stage='start', outcome_result=None):
    global _last_shown, _last_solo_shown, _event_count, _pending
    if _mute_simlish:
        _apply_mute_to_info(actor.sim_info)
    if not _enabled:
        return
    if hook_stage != 'start':
        return
    now = time.monotonic()
    if now - _last_solo_shown < 2.0:
        return
    if _pending is not None:
        _record_skip('pending_in_flight', interaction, actor, None,
                     {'pending_event_id': _pending.get('event_id')})
        return
    _last_solo_shown = now
    _last_shown = now
    _event_count += 1
    _mark_english_for_sims(actor)
    venue = _venue_snapshot()
    interaction_name = type(interaction).__name__
    stbl_val = _string_hash(getattr(interaction, 'display_name', None), actor)
    if not stbl_val and 'forbidden' in interaction_name.lower():
        stbl_val = 4013856058
    event = {
        'type': 'solo_vocal',
        'mode': _mode,
        'hook_stage': hook_stage,
        'outcome': outcome_result or 'SUCCESS',
        'event_id': 'solo-{}-{}'.format(int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': interaction_name,
        'interaction_stbl': stbl_val,
        'is_super': bool(getattr(interaction, 'is_super', False)),
        'venue': venue['id'],
        'venue_stbl': venue['stbl'],
        'actor': _sim_snapshot(actor),
        'target': None,
    }
    if _mode == 'ai':
        _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    if _mode == 'fixed':
        actor_name = event['actor']['name']
        line = '{}: [Banter Lab solo] ({})!'.format(actor_name, interaction_name)
        _notify(actor_name, line, actor.sim_info, None)
        _record({'type': 'displayed', 'mode': 'fixed', 'event_id': event['event_id'], 'text': line})


def _observe(interaction, hook_stage='start', outcome_result=None):
    global _last_shown, _event_count, _pending
    actor, target = _social_participants(interaction)
    if actor is None:
        solo_actor = _solo_vocal_actor(interaction)
        if solo_actor is not None:
            _observe_solo_vocal(interaction, solo_actor, hook_stage=hook_stage, outcome_result=outcome_result)
        return
    if _mute_simlish:
        _apply_mute_to_info(actor.sim_info)
        _apply_mute_to_info(target.sim_info)
    if not _enabled:
        return
    if hook_stage != _trigger_on:
        return
    interaction_name = type(interaction).__name__
    if interaction_name in _PASSIVE_CONTAINERS:
        _record_skip('passive_container', interaction, actor, target)
        return
    interaction_stbl = _string_hash(getattr(interaction, 'display_name', None), actor, target)
    if interaction_name in _UNLABELLED_WAVES and not interaction_stbl:
        _record_skip('unlabelled_wave', interaction, actor, target)
        return
    if _pending is not None:
        _record_skip('pending_in_flight', interaction, actor, target,
                     {'pending_event_id': _pending.get('event_id')})
        return
    now = time.monotonic()
    elapsed = now - _last_shown
    if elapsed < _COOLDOWN_SECONDS:
        _record_skip('cooldown', interaction, actor, target,
                     {'cooldown_remaining_s': round(_COOLDOWN_SECONDS - elapsed, 2)})
        return
    _last_shown = now
    _event_count += 1
    _mark_english_for_sims(actor, target)
    venue = _venue_snapshot()
    event = {
        'type': 'social',
        'mode': _mode,
        'hook_stage': hook_stage,
        'outcome': outcome_result,
        'event_id': '{}-{}'.format(int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': interaction_name,
        'interaction_stbl': interaction_stbl,
        'is_super': bool(getattr(interaction, 'is_super', False)),
        'venue': venue['id'],
        'venue_stbl': venue['stbl'],
        'actor': _sim_snapshot(actor),
        'target': _sim_snapshot(target),
        'relationship': _relationship_snapshot(actor.sim_info, target.sim_info),
    }
    if _mode == 'ai':
        _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    if _mode == 'fixed':
        actor_name = event['actor']['name']
        target_name = event['target']['name']
        line = '{} to {}: [Banter Lab test] Lovely weather for a {} ({}).'.format(
            actor_name, target_name, interaction_name, outcome_result or hook_stage)
        _notify('Banter Lab', line, actor.sim_info, target.sim_info)
        _record({'type': 'displayed', 'mode': 'fixed', 'event_id': event['event_id'], 'text': line})


class _ReplyPoller:
    def poll(self, _timeline_handle):
        global _enabled, _pending
        if _pending is None or _reply_path is None or not os.path.exists(_reply_path):
            return
        try:
            with open(_reply_path, encoding='utf-8-sig') as stream:
                reply = json.load(stream)
            if reply.get('event_id') != _pending['event_id']:
                return
            event = _pending
            _pending = None
            if services.current_zone_id() != event['zone_id']:
                return
            if 'error' in reply:
                _enabled = False
                _notify('Banter Lab', 'Generation stopped: {}. Check the companion.'.format(reply['error']),
                        services.active_sim_info())
            else:
                manager = services.sim_info_manager()
                actor_info = manager.get(int(event['actor']['id'])) if manager is not None else None
                target_data = event.get('target')
                target_info = None
                if isinstance(target_data, dict) and target_data.get('id') and manager is not None:
                    target_info = manager.get(int(target_data['id']))
                if target_data and target_data.get('name'):
                    title = '{} ↔ {}'.format(event['actor']['name'], target_data['name'])
                else:
                    title = event['actor']['name']
                if actor_info is not None and actor_info.get_sim_instance() is not None:
                    _mark_english_for_sims(actor_info.get_sim_instance())
                if target_info is not None and target_info.get_sim_instance() is not None:
                    _mark_english_for_sims(target_info.get_sim_instance())
                _notify(title, reply['text'], actor_info, target_info)
                _record(dict(reply, type='displayed', displayed_at=time.time()))
        except Exception:
            _record({'type': 'error', 'traceback': traceback.format_exc()})


_poller = _ReplyPoller()


def _ensure_poller_alarm():
    global _alarm, _reply_path
    if _reply_path is None:
        bridge_config = os.path.join(_data_directory, 'bridge.json')
        if os.path.exists(bridge_config):
            with open(bridge_config, encoding='utf-8-sig') as stream:
                _reply_path = json.load(stream)['reply_file']
        else:
            _reply_path = os.path.join(_data_directory, 'reply.json')
    if _alarm is None:
        _alarm = alarms.add_alarm_real_time(
            _poller, clock.interval_in_real_seconds(0.35), _poller.poll, repeating=True)


def _cancel_polling():
    global _alarm, _pending
    if _alarm is not None:
        alarms.cancel_alarm(_alarm)
        _alarm = None
    _pending = None


def _resolve_chat_partner(first_name=None, last_name=None):
    active_sim = services.get_active_sim()
    if active_sim is None:
        return None, None
    manager = services.sim_info_manager()
    if first_name and last_name and manager is not None:
        info = manager.get_sim_info_by_name(first_name, last_name)
        if info is not None and info.get_sim_instance() is not None:
            return active_sim, info.get_sim_instance()
    si_state = getattr(active_sim, 'si_state', None)
    if si_state is not None:
        for si in si_state:
            if getattr(si, 'is_social', False):
                target = si.get_participant(ParticipantType.TargetSim)
                if target is not None and getattr(target, 'is_sim', False) and target is not active_sim:
                    return active_sim, target
    best_sim = None
    best_dist = None
    active_pos = getattr(active_sim, 'position', None)
    for info in manager.values():
        sim = info.get_sim_instance()
        if sim is None or sim is active_sim:
            continue
        pos = getattr(sim, 'position', None)
        if active_pos is not None and pos is not None:
            delta = active_pos - pos
            dist = delta.x * delta.x + delta.y * delta.y + delta.z * delta.z
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_sim = sim
        elif best_sim is None:
            best_sim = sim
    return active_sim, best_sim


def _open_talk_dialog(actor_sim, target_sim):
    actor_info = actor_sim.sim_info
    target_info = target_sim.sim_info

    def _on_response(dialog):
        try:
            text_val = dialog.text_input_responses.get('message', '').strip()
            if not getattr(dialog, 'accepted', False) or not text_val:
                _record({'type': 'talk_dialog_cancelled', 'observed_at': time.time()})
                return
            _submit_player_chat(actor_sim, target_sim, text_val)
        except Exception:
            _record({'type': 'error', 'traceback': traceback.format_exc()})

    dialog = _BanterInputDialog.TunableFactory().default(
        actor_info,
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(
            '{} {} → {} {}'.format(
                actor_info.first_name, actor_info.last_name,
                target_info.first_name, target_info.last_name)),
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(
            'What does {} say to {}?'.format(actor_info.first_name, target_info.first_name)),
    )
    dialog.add_listener(_on_response)
    dialog.show_dialog(
        icon_override=IconInfoData(obj_instance=actor_info),
        secondary_icon_override=IconInfoData(obj_instance=target_info),
    )
    _record({
        'type': 'talk_dialog_opened',
        'observed_at': time.time(),
        'actor': '{} {}'.format(actor_info.first_name, actor_info.last_name).strip(),
        'target': '{} {}'.format(target_info.first_name, target_info.last_name).strip(),
    })


def _open_ask_self_dialog(actor_sim):
    actor_info = actor_sim.sim_info

    def _on_response(dialog):
        try:
            text_val = dialog.text_input_responses.get('message', '').strip()
            if not getattr(dialog, 'accepted', False) or not text_val:
                _record({'type': 'ask_self_dialog_cancelled', 'observed_at': time.time()})
                return
            _submit_player_ask_self(actor_sim, text_val)
        except Exception:
            _record({'type': 'error', 'traceback': traceback.format_exc()})

    dialog = _BanterInputDialog.TunableFactory().default(
        actor_info,
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(
            'Ask {} {}'.format(actor_info.first_name, actor_info.last_name)),
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(
            'Ask {} a question in English (or Hebrew / Russian):'.format(actor_info.first_name)),
    )
    dialog.add_listener(_on_response)
    dialog.show_dialog(
        icon_override=IconInfoData(obj_instance=actor_info),
    )
    _record({
        'type': 'ask_self_dialog_opened',
        'observed_at': time.time(),
        'actor': '{} {}'.format(actor_info.first_name, actor_info.last_name).strip(),
    })


def _install_pie_menu_interaction():
    global _pie_interaction_cls, _pie_ask_self_cls
    affordance_mgr = services.affordance_manager()
    if affordance_mgr is None:
        return 0
    base_cls = affordance_mgr.get(13142)
    if base_cls is None:
        return 0

    if _pie_interaction_cls is None:
        class BanterPieMenuInteraction(base_cls):
            guid64 = 0xBA47E21AB0000001
            cheat = False
            debug = False
            simless = False
            allow_user_directed = True
            category = None
            pie_menu_priority = 30

            @classmethod
            def _tunable_tests_enabled(cls):
                return False

            @flexmethod
            def test(cls, inst, *args, target=DEFAULT, context=DEFAULT, **kwargs):
                target_obj = inst.target if inst is not None else target
                if target_obj is None or not getattr(target_obj, 'is_sim', False):
                    return TestResult(False, 'Target must be a Sim.')
                return TestResult.TRUE

            @flexmethod
            def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
                target_obj = inst.target if inst is not None else target
                ctx = inst.context if inst is not None else context
                actor_sim = getattr(ctx, 'sim', None) or services.get_active_sim()
                if target_obj is actor_sim:
                    label = 'Disable English Banter' if _enabled else 'Enable English Banter'
                    return LocalizationHelperTuning.get_raw_text(label)
                first_name = getattr(getattr(target_obj, 'sim_info', target_obj), 'first_name', 'Sim')
                return LocalizationHelperTuning.get_raw_text('Speak to {} (English)...'.format(first_name))

            def _run_interaction_gen(self, timeline):
                if False:
                    yield None
                try:
                    target_sim = self.target
                    actor_sim = self.sim or services.get_active_sim()
                    if target_sim is actor_sim:
                        if _enabled:
                            stop()
                            _notify('Banter Lab', 'English Banter turned off.', actor_sim.sim_info)
                        else:
                            start_ai('outcome')
                            _notify('Banter Lab',
                                    'English Banter is on! Sims will now speak contextual English during socials and solo vocalizations.',
                                    actor_sim.sim_info)
                    elif actor_sim is not None and target_sim is not None and getattr(target_sim, 'is_sim', False):
                        _open_talk_dialog(actor_sim, target_sim)
                except Exception:
                    _record({'type': 'error', 'traceback': traceback.format_exc()})
                return True

        _pie_interaction_cls = BanterPieMenuInteraction
        if hasattr(affordance_mgr, '_tuned_classes'):
            affordance_mgr._tuned_classes[_pie_interaction_cls.guid64] = _pie_interaction_cls

    if _pie_ask_self_cls is None:
        class BanterAskSelfPieMenuInteraction(base_cls):
            guid64 = 0xBA47E21AB0000002
            cheat = False
            debug = False
            simless = False
            allow_user_directed = True
            category = None
            pie_menu_priority = 29

            @classmethod
            def _tunable_tests_enabled(cls):
                return False

            @flexmethod
            def test(cls, inst, *args, target=DEFAULT, context=DEFAULT, **kwargs):
                target_obj = inst.target if inst is not None else target
                ctx = inst.context if inst is not None else context
                actor_sim = getattr(ctx, 'sim', None) or services.get_active_sim()
                if target_obj is None or target_obj is not actor_sim:
                    return TestResult(False, 'Only shown on the Active Sim.')
                return TestResult.TRUE

            @flexmethod
            def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
                target_obj = inst.target if inst is not None else target
                first_name = getattr(getattr(target_obj, 'sim_info', target_obj), 'first_name', 'Sim')
                return LocalizationHelperTuning.get_raw_text('Ask {} a Question (English)...'.format(first_name))

            def _run_interaction_gen(self, timeline):
                if False:
                    yield None
                try:
                    actor_sim = self.sim or services.get_active_sim()
                    if actor_sim is not None:
                        _open_ask_self_dialog(actor_sim)
                except Exception:
                    _record({'type': 'error', 'traceback': traceback.format_exc()})
                return True

        _pie_ask_self_cls = BanterAskSelfPieMenuInteraction
        if hasattr(affordance_mgr, '_tuned_classes'):
            affordance_mgr._tuned_classes[_pie_ask_self_cls.guid64] = _pie_ask_self_cls

    count = 0
    sim_info_mgr = services.sim_info_manager()
    if sim_info_mgr is None:
        return 0
    for info in sim_info_mgr.values():
        sim = info.get_sim_instance()
        if sim is None:
            continue
        sim_cls = type(sim)
        for cls_to_add in (_pie_interaction_cls, _pie_ask_self_cls):
            if hasattr(sim_cls, '_super_affordances') and cls_to_add not in sim_cls._super_affordances:
                sim_cls._super_affordances = sim_cls._super_affordances + (cls_to_add,)
            if hasattr(sim, '_super_affordances') and cls_to_add not in sim._super_affordances:
                sim._super_affordances = sim._super_affordances + (cls_to_add,)
        count += 1
    return count


def _submit_player_chat(actor_sim, target_sim, message_text):
    global _event_count, _pending
    _ensure_poller_alarm()
    _event_count += 1
    _mark_english_for_sims(actor_sim, target_sim)
    venue = _venue_snapshot()
    event = {
        'type': 'player_chat',
        'mode': 'ai',
        'hook_stage': 'player',
        'outcome': 'PLAYER_INITIATED',
        'player_message': message_text,
        'event_id': 'chat-{}-{}'.format(int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': 'player_direct_chat',
        'interaction_stbl': None,
        'is_super': False,
        'venue': venue['id'],
        'venue_stbl': venue['stbl'],
        'actor': _sim_snapshot(actor_sim),
        'target': _sim_snapshot(target_sim),
        'relationship': _relationship_snapshot(actor_sim.sim_info, target_sim.sim_info),
    }
    _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    return event


def _submit_player_ask_self(actor_sim, question_text):
    global _event_count, _pending
    _ensure_poller_alarm()
    _event_count += 1
    _mark_english_for_sims(actor_sim)
    venue = _venue_snapshot()
    event = {
        'type': 'player_ask_self',
        'mode': 'ai',
        'hook_stage': 'player',
        'outcome': 'PLAYER_INITIATED',
        'player_message': question_text,
        'event_id': 'ask-{}-{}'.format(int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': 'player_ask_active_sim',
        'interaction_stbl': None,
        'is_super': False,
        'venue': venue['id'],
        'venue_stbl': venue['stbl'],
        'actor': _sim_snapshot(actor_sim),
        'target': None,
    }
    _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    return event


_original_start = getattr(Interaction, '_banter_orig_start', Interaction._trigger_interaction_start_event)
_original_store_outcome = getattr(Interaction, '_banter_orig_outcome', Interaction.store_result_for_outcome)
_original_complete = getattr(Interaction, '_banter_orig_complete', Interaction._trigger_interaction_complete_test_event)
_original_cancel = getattr(Interaction, '_banter_orig_cancel', Interaction.cancel)
_original_zone_loaded = getattr(Zone, '_banter_orig_zone_loaded', Zone.on_loading_screen_animation_finished)
_original_playsound_start = getattr(PlaySound, '_banter_orig_start', PlaySound.start)

Interaction._banter_orig_start = _original_start
Interaction._banter_orig_outcome = _original_store_outcome
Interaction._banter_orig_complete = _original_complete
Interaction._banter_orig_cancel = _original_cancel
Zone._banter_orig_zone_loaded = _original_zone_loaded
PlaySound._banter_orig_start = _original_playsound_start


@functools.wraps(_original_playsound_start)
def _on_playsound_start(self, *args, **kwargs):
    ret = _original_playsound_start(self, *args, **kwargs)
    try:
        if getattr(self, '_is_vox', False) and (_enabled or _trace):
            target_obj = getattr(self, 'target', None)
            sim_info = getattr(target_obj, 'sim_info', None)
            if sim_info is not None and sim_info.household_id == services.active_household_id():
                _vox_stats['total'] = _vox_stats.get('total', 0) + 1
                now = time.monotonic()
                recent_en = (now - _last_english_by_sim.get(sim_info.sim_id, 0.0)) < 8.0
                pending_match = (
                    _pending is not None and (
                        str(sim_info.sim_id) == str((_pending.get('actor') or {}).get('id'))
                        or str(sim_info.sim_id) == str((_pending.get('target') or {}).get('id'))
                    )
                )
                covered = bool(recent_en or pending_match)
                if covered:
                    _vox_stats['covered_by_english'] = _vox_stats.get('covered_by_english', 0) + 1
                else:
                    _vox_stats['unreplaced'] = _vox_stats.get('unreplaced', 0) + 1
                _record({
                    'type': 'vox_attempt',
                    'observed_at': time.time(),
                    'sim_name': '{} {}'.format(sim_info.first_name, sim_info.last_name).strip(),
                    'sound_name': getattr(self, '_sound_name', None),
                    'sound_id': getattr(self, '_sound_id', None),
                    'covered_by_english': covered,
                    'mute_simlish': _mute_simlish,
                })
    except Exception:
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return ret


@functools.wraps(_original_start)
def _on_interaction_start(self, *args, **kwargs):
    result = _original_start(self, *args, **kwargs)
    try:
        _trace_lifecycle(self, 'start')
        _observe(self, hook_stage='start')
    except Exception:
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return result


@functools.wraps(_original_store_outcome)
def _on_store_outcome(self, outcome, result, *args, **kwargs):
    ret = _original_store_outcome(self, outcome, result, *args, **kwargs)
    try:
        outcome_name = getattr(result, 'name', str(result))
        _trace_lifecycle(self, 'outcome', {'outcome': outcome_name, 'outcome_type': type(outcome).__name__})
        _observe(self, hook_stage='outcome', outcome_result=outcome_name)
    except Exception:
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return ret


@functools.wraps(_original_complete)
def _on_interaction_complete(self, *args, **kwargs):
    ret = _original_complete(self, *args, **kwargs)
    try:
        outcome_val = getattr(self, 'global_outcome_result', None)
        _trace_lifecycle(self, 'complete', {
            'global_outcome_result': getattr(outcome_val, 'name', str(outcome_val)) if outcome_val is not None else None,
        })
    except Exception:
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return ret


@functools.wraps(_original_cancel)
def _on_interaction_cancel(self, finishing_type, cancel_reason_msg=None, ignore_must_run=False, *args, **kwargs):
    ret = _original_cancel(
        self, finishing_type, cancel_reason_msg=cancel_reason_msg,
        ignore_must_run=ignore_must_run, *args, **kwargs)
    try:
        if ret:
            _trace_lifecycle(self, 'cancel', {
                'finishing_type': getattr(finishing_type, 'name', str(finishing_type)),
            })
    except Exception:
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return ret


Interaction._trigger_interaction_start_event = _on_interaction_start
Interaction.store_result_for_outcome = _on_store_outcome
Interaction._trigger_interaction_complete_test_event = _on_interaction_complete
Interaction.cancel = _on_interaction_cancel
PlaySound.start = _on_playsound_start


@functools.wraps(_original_zone_loaded)
def _on_zone_loaded(self, *args, **kwargs):
    ret = _original_zone_loaded(self, *args, **kwargs)
    try:
        count = _install_pie_menu_interaction()
        _record({'type': 'pie_menu_installed', 'sims': count, 'observed_at': time.time()})
    except Exception:
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return ret


Zone.on_loading_screen_animation_finished = _on_zone_loaded


def _read_cost_summary():
    cost_path = os.path.join(_data_directory, 'cost_summary.json')
    if not os.path.exists(cost_path):
        return None
    try:
        with open(cost_path, encoding='utf-8-sig') as stream:
            return json.load(stream)
    except Exception:
        return None


@sims4.commands.Command('banter.start', command_type=sims4.commands.CommandType.Live)
def start(trigger: str = 'start', _connection=None):
    global _enabled, _last_shown, _mode, _trigger_on
    _cancel_polling()
    _enabled = True
    _mode = 'fixed'
    _trigger_on = 'outcome' if trigger == 'outcome' else 'start'
    _last_shown = 0
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)(
            'Banter Lab observing social interactions (trigger={}).'.format(_trigger_on))
    _notify('Banter Lab',
            'Social observation is on (trigger={}). Use banter.stop to turn it off.'.format(_trigger_on),
            services.active_sim_info())
    _record({'type': 'started', 'mode': _mode, 'trigger_on': _trigger_on,
             'observed_at': time.time(), 'active_sim': _sim_snapshot(services.get_active_sim())})


@sims4.commands.Command('banter.ai', command_type=sims4.commands.CommandType.Live)
def start_ai(trigger: str = 'outcome', _connection=None):
    global _enabled, _last_shown, _mode, _trigger_on, _reply_path
    _reply_path = None
    _cancel_polling()
    _ensure_poller_alarm()
    _enabled = True
    _mode = 'ai'
    _trigger_on = 'start' if trigger == 'start' else 'outcome'
    _last_shown = 0
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)(
            'Banter Lab: generated mode (trigger={}); start the companion first.'.format(_trigger_on))
    _record({'type': 'started', 'mode': _mode, 'trigger_on': _trigger_on,
             'observed_at': time.time(), 'active_sim': _sim_snapshot(services.get_active_sim()),
             'reply_file': _reply_path})


@sims4.commands.Command('banter.say', command_type=sims4.commands.CommandType.Live)
def say_command(*words, _connection=None):
    """Send a direct player-authored line from the active Sim to the nearest or conversing Sim."""
    output = sims4.commands.CheatOutput(_connection)
    message_text = ' '.join(words).strip()
    if not message_text:
        output('Usage: banter.say <what your Sim says>')
        return
    actor_sim, target_sim = _resolve_chat_partner()
    if actor_sim is None or target_sim is None:
        output('No nearby Sim found to talk to.')
        return
    event = _submit_player_chat(actor_sim, target_sim, message_text)
    output('Sent to {} {}: "{}" (event={})'.format(
        target_sim.sim_info.first_name, target_sim.sim_info.last_name,
        message_text, event['event_id']))


@sims4.commands.Command('banter.ask', command_type=sims4.commands.CommandType.Live)
def ask_self_command(*words, _connection=None):
    """Ask the active Sim a direct question in English (or open the Ask Self modal if no question given)."""
    output = sims4.commands.CheatOutput(_connection)
    active_sim = services.get_active_sim()
    if active_sim is None:
        output('No active Sim found.')
        return
    question_text = ' '.join(words).strip()
    if not question_text:
        _open_ask_self_dialog(active_sim)
        output('Opened Ask Self dialog for {} {}.'.format(
            active_sim.sim_info.first_name, active_sim.sim_info.last_name))
        return
    event = _submit_player_ask_self(active_sim, question_text)
    output('Asked {} {}: "{}" (event={})'.format(
        active_sim.sim_info.first_name, active_sim.sim_info.last_name,
        question_text, event['event_id']))


@sims4.commands.Command('banter.solo', command_type=sims4.commands.CommandType.Live)
def solo_vocal_command(*words, _connection=None):
    """Trigger a solo vocal outburst (defaults to Shout Forbidden Words) on the active Sim."""
    global _event_count, _pending
    output = sims4.commands.CheatOutput(_connection)
    active_sim = services.get_active_sim()
    if active_sim is None:
        output('No active Sim found.')
        return
    _ensure_poller_alarm()
    _event_count += 1
    _mark_english_for_sims(active_sim)
    action_name = ' '.join(words).strip() or 'si_Trait_Manners_ShoutForbiddenWords'
    stbl_val = 4013856058 if 'forbidden' in action_name.lower() else None
    venue = _venue_snapshot()
    event = {
        'type': 'solo_vocal',
        'mode': 'ai',
        'hook_stage': 'start',
        'outcome': 'SUCCESS',
        'event_id': 'solo-{}-{}'.format(int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': action_name,
        'interaction_stbl': stbl_val,
        'is_super': True,
        'venue': venue['id'],
        'venue_stbl': venue['stbl'],
        'actor': _sim_snapshot(active_sim),
        'target': None,
    }
    _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    output('Triggered solo vocal {} for {} {} (event={})'.format(
        action_name, active_sim.sim_info.first_name, active_sim.sim_info.last_name, event['event_id']))


@sims4.commands.Command('banter.talk', command_type=sims4.commands.CommandType.Live)
def talk_dialog_command(first_name: str = '', last_name: str = '', _connection=None):
    """Open an in-game text input modal to speak to a nearby or named Sim."""
    output = sims4.commands.CheatOutput(_connection)
    actor_sim, target_sim = _resolve_chat_partner(first_name or None, last_name or None)
    if actor_sim is None or target_sim is None:
        output('No nearby Sim found to talk to.')
        return
    _open_talk_dialog(actor_sim, target_sim)
    output('Opened talk dialog for {} → {}.'.format(
        actor_sim.sim_info.first_name, target_sim.sim_info.first_name))


@sims4.commands.Command('banter.menu', command_type=sims4.commands.CommandType.Live)
def menu_command(_connection=None):
    """Ensure the Banter Lab pie-menu interactions are attached to instanced Sims."""
    count = _install_pie_menu_interaction()
    _record({'type': 'pie_menu_installed', 'sims': count, 'observed_at': time.time()})
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)('Banter Lab pie-menu interactions installed on {} Sims.'.format(count))


@sims4.commands.Command('banter.mute', command_type=sims4.commands.CommandType.Live)
def mute_command(state: str = 'on', _connection=None):
    """Dynamically silence or restore Simlish voice_actor on instanced Sims in the zone."""
    global _mute_simlish
    _mute_simlish = state.lower() not in ('off', '0', 'false', 'stop')
    count = _sync_zone_mute()
    active_info = services.active_sim_info()
    _record({
        'type': 'mute_state',
        'mute_simlish': _mute_simlish,
        'affected_sims': count,
        'active_sim_voice_actor_raw': int(getattr(active_info, 'voice_actor', 0)) if active_info else None,
        'active_sim_voice_actor_preserved': _true_voice_actor(active_info) if active_info else None,
        'observed_at': time.time(),
    })
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)(
            'Banter Lab Simlish mute={} (updated {} Sims).'.format(_mute_simlish, count))


@sims4.commands.Command('banter.trace', command_type=sims4.commands.CommandType.Live)
def trace_command(state: str = 'on', _connection=None):
    global _trace
    _trace = state.lower() not in ('off', '0', 'false', 'stop')
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)('Banter Lab lifecycle trace={}.'.format(_trace))
    _record({'type': 'trace_state', 'enabled': _trace, 'observed_at': time.time()})


@sims4.commands.Command('banter.stop', command_type=sims4.commands.CommandType.Live)
def stop(_connection=None):
    global _enabled, _trace, _mute_simlish
    _enabled = False
    _trace = False
    if _mute_simlish or _original_voice_actors:
        _mute_simlish = False
        _sync_zone_mute()
    _cancel_polling()
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)('Banter Lab stopped and Simlish voices restored.')


@sims4.commands.Command('banter.status', command_type=sims4.commands.CommandType.Live)
def status(_connection=None):
    cost = _read_cost_summary() or {}
    sess_usd = (cost.get('session') or {}).get('total_usd', 0.0)
    cum_usd = (cost.get('cumulative') or {}).get('total_usd', 0.0)
    vox_total = _vox_stats.get('total', 0)
    vox_cov = _vox_stats.get('covered_by_english', 0)
    vox_pct = round(100.0 * vox_cov / vox_total, 1) if vox_total else 100.0
    if _connection is not None:
        sims4.commands.CheatOutput(_connection)(
            'Banter Lab: enabled={}, mute={}, observed={}, vox_covered={}/{} ({}%), skipped={}, cost(session=${:.4f}, total=${:.4f})'.format(
                _enabled, _mute_simlish, _event_count, vox_cov, vox_total, vox_pct, _skip_counts, sess_usd, cum_usd))
    nearby = []
    for info in services.sim_info_manager().values():
        sim = info.get_sim_instance()
        if sim is not None:
            nearby.append({'id': str(info.sim_id), 'name': '{} {}'.format(info.first_name, info.last_name)})
    _record({
        'type': 'status',
        'enabled': _enabled,
        'trace': _trace,
        'mute_simlish': _mute_simlish,
        'mode': _mode,
        'trigger_on': _trigger_on,
        'observed_count': _event_count,
        'skip_counts': dict(_skip_counts),
        'vox_stats': dict(_vox_stats),
        'cost_summary': cost,
        'venue': _venue_snapshot(),
        'active_sim': _sim_snapshot(services.get_active_sim()) if services.get_active_sim() else None,
        'nearby': nearby,
    })


@sims4.commands.Command('banter.reload', command_type=sims4.commands.CommandType.Live)
def reload_command(_connection=None):
    """Hot-reload banter_lab from BanterLab.ts4script without restarting The Sims 4."""
    output = sims4.commands.CheatOutput(_connection)
    try:
        _cancel_polling()
        zipimport._zip_directory_cache.clear()
        mod = importlib.reload(sys.modules[__name__])
        count = mod._install_pie_menu_interaction()
        output('Banter Lab hot-reloaded cleanly (pie menu attached to {} Sims).'.format(count))
    except Exception as exc:
        output('Reload failed: {}'.format(exc))
        _record({'type': 'error', 'traceback': traceback.format_exc()})


@sims4.commands.Command('banter.summon', command_type=sims4.commands.CommandType.Live)
def summon(first_name: str, last_name: str, _connection=None):
    """Test-save setup only; wait for the NPC before requesting a social."""
    info = services.sim_info_manager().get_sim_info_by_name(first_name, last_name)
    if info is None:
        sims4.commands.CheatOutput(_connection)('No Sim found with that name.')
        return
    SimSpawner.load_sim(info.sim_id)
    _record({'type': 'summon_requested', 'id': str(info.sim_id),
             'name': '{} {}'.format(info.first_name, info.last_name)})
    sims4.commands.CheatOutput(_connection)('Requested {} {}. Use banter.status to inspect arrivals.'.format(
        info.first_name, info.last_name))


@sims4.commands.Command('banter.test', command_type=sims4.commands.CommandType.Live)
def test_notification(_connection=None):
    active_info = services.active_sim_info()
    partner_info = None
    for info in services.sim_info_manager().values():
        if info.get_sim_instance() is not None and info is not active_info:
            partner_info = info
            break
    title = 'Banter Lab'
    if active_info is not None and partner_info is not None:
        title = '{} {} ↔ {} {}'.format(
            active_info.first_name, active_info.last_name,
            partner_info.first_name, partner_info.last_name)
    _notify(title,
            'Alex: Did you just check whether the silverware is real silver?\n'
            'Partner: I call it appreciating the table setting.',
            active_info, partner_info)
    _record({'type': 'test_notification_sent', 'observed_at': time.time(),
             'has_secondary_icon': partner_info is not None})
    sims4.commands.CheatOutput(_connection)('Speech notification sent.')


@sims4.commands.Command('banter.audio', command_type=sims4.commands.CommandType.Live)
def test_audio(mode: str = 'hello', _connection=None):
    """Manual fixed-resource or vox experiment; neither generates speech nor chooses a social."""
    global _audio_probe
    output = sims4.commands.CheatOutput(_connection)
    if mode not in ('hello', 'control', 'vox', 'stop'):
        output('Use banter.audio hello, control, vox, or stop.')
        return
    if _audio_probe is not None:
        _audio_probe.stop()
        _audio_probe = None
    if mode == 'stop':
        output('Audio probe stopped.')
        return
    active_sim = services.get_active_sim()
    if mode == 'vox':
        _audio_probe = PlaySound(
            active_sim, sound_id=0, sound_name='vo_expr_greet_angry_25f',
            is_vox=True, joint_name_hash=None, play_on_active_sim_only=False, immediate=True)
        _audio_probe.start()
        _record({
            'type': 'audio_probe_requested',
            'mode': 'vox',
            'sound_name': 'vo_expr_greet_angry_25f',
            'is_vox': True,
            'mute_simlish': _mute_simlish,
            'voice_actor_raw': int(getattr(active_sim.sim_info, 'voice_actor', 0)),
            'observed_at': time.time(),
        })
        output('Requested vox audio probe (mute_simlish={}).'.format(_mute_simlish))
        return
    sound_id = 0xAE9960DCFFD5C32E if mode == 'hello' else 0x04A64CD44542ACEC
    _audio_probe = PlaySound(
        active_sim, sound_id=sound_id, sound_name=None, is_vox=False,
        joint_name_hash=None, play_on_active_sim_only=False, immediate=True)
    _audio_probe.start()
    _record({'type': 'audio_probe_requested', 'mode': mode,
             'sound_id': '{:016X}'.format(sound_id), 'observed_at': time.time()})
    output('Requested {} audio probe; audible playback still needs verification.'.format(mode))


try:
    if services.current_zone() is not None:
        _install_pie_menu_interaction()
except Exception:
    pass

_record({'type': 'loaded', 'observed_at': time.time(), 'enabled': _enabled})
