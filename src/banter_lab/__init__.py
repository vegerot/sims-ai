"""Observe actual socials and solo vocalizations, support player-to-Sim and Ask-Self chat, and display contextual dialogue.

Enabled from the Sim Pie Menu (or `banter.ai` / `banter.stop` in the console).
Model calls and OpenRouter gpt-audio-mini speech synthesis run in the external Python 3.15 companion,
which this module starts automatically.
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
import services
import sims4.commands
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.base.interaction import Interaction
from sims4.utils import flexmethod
from singletons import DEFAULT
from zone import Zone
from relationships.relationship_track import RelationshipTrack
from sims4.localization import LocalizationHelperTuning
from ui.ui_dialog_generic import UiDialogTextInputOkCancel
from ui.ui_dialog_notification import UiDialogNotification


_enabled = True
_mute_simlish = True
_original_voice_actors = {}
_event_count = 0
_pending = None
_alarm = None
_reply_path = None
_pie_interaction_cls = None
_pie_ask_self_cls = None
# importlib.reload re-executes this module in the same namespace, so keep the running companion handle.
_companion_proc = globals().get('_companion_proc')
_last_companion_spawn = 0.0
_seen_errors = set()
_MUTE_VOICE_ACTOR = 0x7FFFFFFF
_PENDING_TIMEOUT_SECONDS = 25.0
_PASSIVE_CONTAINERS = ('sim_Chat', 'sim_BeAffectionate')
_UNLABELLED_WAVES = ('socialMixer_Greetings_Wave', 'nonTouching_Unpaired_Greeting_Wave')
_IDLE_POSTURES = ('sim-stand', 'sim_Stand_Exclusive', 'sim-sit')
# STBL keys of the "Shout Forbidden Words" variants. Add other solo vocal actions only after observing them live.
_SOLO_VOCAL_STBLS = (4013856058, 961384365, 3515527490, 2952163771)
_skip_counts = {}
_console_logging = True
_console_log_offset = None
_last_connection = None
# Zip-imported modules have a path inside the .ts4script archive.
_mod_directory = os.path.dirname(__file__.split('.ts4script', 1)[0])
_data_directory = os.path.join(_mod_directory, 'BanterLabData')
_COMPANION_PATH = r'C:\Users\Max\workspace\github.com\vegerot\ai-conversations\gaming\sims-ai\companion.py'
# Controlled Folder Access allows this interpreter to write to Documents.
_PYTHON = r'C:\Users\Max\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\python.exe'


class _BanterInputDialog(UiDialogTextInputOkCancel):
    """In-game modal text input dialog for speaking directly to a Sim."""

    def __init__(self, owner, *args, **kwargs):
        super().__init__(owner, *args, **kwargs)
        self.text_input_responses = {}

    def on_text_input(self, text_input_name='', text_input=''):
        self.text_input_responses[text_input_name] = text_input
        return True

    def build_msg(self, text_input_overrides=None, additional_tokens=(), **kwargs):
        msg = super().build_msg(additional_tokens=(), **kwargs)
        text_input_msg = msg.text_input.add()
        text_input_msg.text_input_name = 'message'
        return msg


def _record(record):
    os.makedirs(_data_directory, exist_ok=True)
    with open(os.path.join(_data_directory, 'events.jsonl'), 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def _record_error():
    """Log a traceback once per session so a wrong game-API guess is visible instead of silently empty."""
    tb = traceback.format_exc()
    if tb in _seen_errors:
        return
    _seen_errors.add(tb)
    _record({'type': 'error', 'observed_at': time.time(), 'traceback': tb})


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


def _sim_name(sim_or_info):
    info = getattr(sim_or_info, 'sim_info', sim_or_info)
    return '{} {}'.format(info.first_name, info.last_name).strip()


def _settings_path():
    return os.path.join(_data_directory, 'settings.json')


def _save_settings():
    os.makedirs(_data_directory, exist_ok=True)
    payload = {
        'enabled': bool(_enabled),
        'mute_simlish': bool(_mute_simlish),
        'console_logging': bool(_console_logging),
        'updated_at': time.time(),
    }
    tmp_path = _settings_path() + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2)
    os.replace(tmp_path, _settings_path())


def _load_settings():
    global _enabled, _mute_simlish, _console_logging
    if not os.path.exists(_settings_path()):
        _save_settings()
        return
    with open(_settings_path(), encoding='utf-8-sig') as stream:
        data = json.load(stream)
    _enabled = bool(data.get('enabled', True))
    _mute_simlish = bool(data.get('mute_simlish', True))
    _console_logging = bool(data.get('console_logging', True))


def _load_original_voice_actors():
    path = os.path.join(_data_directory, 'original_voice_actors.json')
    if not os.path.exists(path):
        return
    with open(path, encoding='utf-8-sig') as stream:
        raw = json.load(stream)
    for k, v in raw.items():
        iv = int(v)
        if iv and iv != _MUTE_VOICE_ACTOR:
            _original_voice_actors[int(k)] = iv


def _save_original_voice_actors():
    os.makedirs(_data_directory, exist_ok=True)
    path = os.path.join(_data_directory, 'original_voice_actors.json')
    payload = {str(k): int(v) for k, v in _original_voice_actors.items() if v and v != _MUTE_VOICE_ACTOR}
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2)


def _true_voice_actor(info):
    if info is None:
        return 0
    sim_id = int(info.sim_id)
    if sim_id in _original_voice_actors:
        return _original_voice_actors[sim_id]
    current = int(getattr(info, 'voice_actor', 0))
    if current != _MUTE_VOICE_ACTOR and current != 0:
        _original_voice_actors[sim_id] = current
        _save_original_voice_actors()
        return current
    gender = getattr(getattr(info, 'gender', None), 'name', '')
    return 1802970394 if str(gender).upper() == 'FEMALE' else 1685527063


def _distribute_voice_actor(info, actor_hash):
    info.voice_actor = actor_hash
    sim = info.get_sim_instance()
    if sim is not None:
        Distributor.instance().add_op(sim, SetVoiceActor(actor_hash))


def _apply_mute_to_info(info):
    if info is None:
        return
    sim_id = int(info.sim_id)
    current = int(getattr(info, 'voice_actor', 0))
    if sim_id not in _original_voice_actors and current != _MUTE_VOICE_ACTOR and current != 0:
        _original_voice_actors[sim_id] = current
        _save_original_voice_actors()
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
        for info in manager.values():
            if info.get_sim_instance() is not None or int(getattr(info, 'voice_actor', 0)) == _MUTE_VOICE_ACTOR:
                orig_actor = _true_voice_actor(info)
                if orig_actor and orig_actor != _MUTE_VOICE_ACTOR:
                    _distribute_voice_actor(info, orig_actor)
                    count += 1
    return count


def _console_print(text, _connection=None):
    global _last_connection
    if _connection is not None:
        _last_connection = _connection
    conn = _connection if _connection is not None else _last_connection
    if conn is None:
        cm = services.client_manager()
        if cm is not None:
            conn = cm.get_first_client_id()
    if conn is None:
        return False
    sims4.commands.CheatOutput(conn)(str(text))
    return True


def _companion_alive():
    return _companion_proc is not None and _companion_proc.poll() is None


def _ensure_companion_running():
    """Start companion.py once per game process; it exits when the game exits."""
    global _companion_proc, _last_companion_spawn
    if _companion_alive():
        return
    now = time.monotonic()
    if now - _last_companion_spawn < 10.0:
        return
    _last_companion_spawn = now
    os.makedirs(_data_directory, exist_ok=True)
    stdout_stream = open(os.path.join(_data_directory, 'companion.stdout.log'), 'a', encoding='utf-8')
    stderr_stream = open(os.path.join(_data_directory, 'companion.stderr.log'), 'a', encoding='utf-8')
    cmd = [_PYTHON, _COMPANION_PATH, '--data-directory', _data_directory, '--parent-pid', str(os.getpid())]
    _companion_proc = subprocess.Popen(
        cmd,
        cwd=os.path.dirname(_COMPANION_PATH),
        stdout=stdout_stream,
        stderr=stderr_stream,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _record({'type': 'companion_spawned', 'pid': _companion_proc.pid, 'observed_at': time.time()})
    _console_print('[Banter Lab] Started companion.py (pid={}).'.format(_companion_proc.pid))


def _print_console_line(raw_line, _connection=None):
    rec = json.loads(raw_line)
    return _console_print('[Companion] {}'.format(rec.get('text', '')), _connection=_connection)


def _drain_companion_console(force_tail=0, _connection=None):
    """Mirror new companion log lines into the cheat console (or print the last `force_tail` lines)."""
    global _console_log_offset
    log_path = os.path.join(_data_directory, 'companion_console.jsonl')
    if not os.path.exists(log_path):
        return 0
    printed = 0
    if force_tail > 0 or _console_log_offset is None:
        with open(log_path, encoding='utf-8-sig') as stream:
            lines = [ln for ln in stream.read().splitlines() if ln.strip()]
            _console_log_offset = stream.tell()
        for raw_line in (lines[-force_tail:] if force_tail > 0 else []):
            printed += int(bool(_print_console_line(raw_line, _connection=_connection)))
        return printed
    with open(log_path, encoding='utf-8-sig') as stream:
        stream.seek(_console_log_offset)
        while True:
            pos = stream.tell()
            line = stream.readline()
            if not line or not line.endswith('\n'):
                stream.seek(pos)
                break
            _console_log_offset = stream.tell()
            if _console_logging:
                printed += int(bool(_print_console_line(line, _connection=_connection)))
    return printed


def _notify(title, text, owner=None, secondary_owner=None, timeout_ms=None):
    factory_kwargs = {
        'title': lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(title),
        'text': lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(text),
        'expand_behavior': UiDialogNotification.UiDialogNotificationExpandBehavior.FORCE_EXPAND,
        'visual_type': UiDialogNotification.UiDialogNotificationVisualType.SPEECH,
        'information_level': UiDialogNotification.UiDialogNotificationLevel.SIM,
    }
    if timeout_ms is not None and int(timeout_ms) > 0:
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
    if crafting is None or not hasattr(crafting, 'get_recipe'):
        return None, None
    recipe = crafting.get_recipe()
    if recipe is None:
        return None, None
    return getattr(recipe, '__name__', type(recipe).__name__), _string_hash(getattr(recipe, 'get_recipe_name', None))


def _sim_activities(sim):
    activities = []
    si_state = getattr(sim, 'si_state', None)
    if si_state is None:
        return activities
    try:
        for si in si_state:
            if getattr(si, 'is_social', False):
                continue
            si_name = type(si).__name__
            if si_name in _IDLE_POSTURES:
                continue
            target_obj = getattr(si, 'target', None)
            recipe_name, recipe_stbl = _crafted_recipe(target_obj) if target_obj is not None else (None, None)
            activities.append({
                'id': si_name,
                'stbl': _string_hash(getattr(si, 'display_name', None), sim, target_obj),
                'target': type(target_obj).__name__ if target_obj is not None else None,
                'target_stbl': _string_hash(getattr(target_obj, 'catalog_name', None)) if target_obj is not None else None,
                'recipe': recipe_name,
                'recipe_stbl': recipe_stbl,
            })
        posture_state = getattr(sim, 'posture_state', None)
        for carried in (getattr(posture_state, 'carry_targets', ()) if posture_state is not None else ()):
            if carried is None or getattr(carried, 'is_sim', False):
                continue
            recipe_name, recipe_stbl = _crafted_recipe(carried)
            activities.append({
                'id': 'carrying',
                'stbl': None,
                'target': type(carried).__name__,
                'target_stbl': _string_hash(getattr(carried, 'catalog_name', None)),
                'recipe': recipe_name,
                'recipe_stbl': recipe_stbl,
            })
    except Exception:
        _record_error()
    return activities[:4]


def _sim_careers(info):
    careers_out = []
    tracker = getattr(info, 'career_tracker', None)
    if tracker is None:
        return careers_out
    try:
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
    except Exception:
        _record_error()
    return careers_out[:3]


def _sim_skills(info):
    skills_out = []
    tracker = getattr(info, 'commodity_tracker', None)
    if tracker is None or not hasattr(tracker, 'get_all_commodities'):
        return skills_out
    try:
        for stat in tracker.get_all_commodities():
            if not getattr(stat, 'is_skill', False):
                continue
            stat_cls = getattr(stat, 'stat_type', type(stat))
            user_val = int(stat.get_user_value() or 0)
            raw_val = round(float(stat.get_value() or 0.0), 1)
            if user_val < 2 and raw_val < 500.0:
                continue
            skills_out.append((-user_val, -raw_val, {
                'id': getattr(stat_cls, '__name__', type(stat).__name__),
                'stbl': _string_hash(getattr(stat_cls, 'stat_name', None), info),
                'level': user_val,
                'points': raw_val,
            }))
    except Exception:
        _record_error()
    skills_out.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in skills_out[:6]]


def _sim_snapshot(sim):
    info = sim.sim_info
    mood = info.get_mood()
    traits = list(info.trait_tracker.personality_traits)
    trait_stbls = [s for s in (_string_hash(getattr(t, 'display_name', None), info) for t in traits) if s]
    personality_names = {trait.__name__ for trait in traits}
    extra_traits = []
    funds = None
    try:
        for eq_trait in getattr(info.trait_tracker, 'equipped_traits', ()):
            tname = getattr(eq_trait, '__name__', None)
            if tname and tname not in personality_names:
                extra_traits.append(tname)
        household = getattr(info, 'household', None)
        if household is not None and getattr(household, 'funds', None) is not None:
            funds = int(household.funds.money)
    except Exception:
        _record_error()
    asp = getattr(info, 'primary_aspiration', None)
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
    species_obj = getattr(info, 'extended_species', None) or getattr(info, 'species', None)
    breed_name = getattr(info, '_breed_name', None) or getattr(info, 'breed_name', None) or None
    if callable(breed_name):
        breed_name = None
    return {
        'id': str(info.sim_id),
        'name': _sim_name(info),
        'age': getattr(info.age, 'name', str(info.age)),
        'gender': getattr(info.gender, 'name', str(info.gender)),
        'species': getattr(species_obj, 'name', str(species_obj)) if species_obj is not None else 'HUMAN',
        'breed': str(breed_name) if breed_name else None,
        'breed_stbl': _string_hash(getattr(info, 'breed_name_key', None)),
        'voice_actor': _true_voice_actor(info),
        'voice_pitch': round(float(getattr(info, 'voice_pitch', 0.0)), 4),
        'traits': [trait.__name__ for trait in traits],
        'trait_stbls': trait_stbls,
        'extra_traits': extra_traits,
        'aspiration': getattr(asp, '__name__', None) if asp is not None else None,
        'aspiration_stbl': _string_hash(getattr(asp, 'display_name', None), info) if asp is not None else None,
        'household_funds': funds,
        'careers': _sim_careers(info),
        'skills': _sim_skills(info),
        'mood': mood.__name__ if mood else None,
        'mood_intensity': info.get_mood_intensity(),
        'buffs': buffs[:5],
        'activities': _sim_activities(sim),
        'social_connections': _sim_social_connections(info),
    }


_CONNECTION_PRIORITIES = (
    (100, ('married', 'engaged', 'significant_other', 'soulmates', 'sweethearts', 'lovebirds', 'lovers',
           'havebeenexes', 'broken_up', 'divorced', 'hasbeenunfaithful')),
    (80, ('sentimentbit_', 'nolongerfriends', 'fellinlove', 'havebeenromantic', 'itsveryawkward', 'badromance',
          'fear_beingcheatedon')),
    (70, ('family_target_', 'familytrope_', 'romancetrope_', 'isdog', 'iscat', 'partnersincrime',
          'wentonblinddatewith', 'hadsex_7days', 'hadlewddreamabout')),
    (40, ('friendship-bff', 'friendship-good_friends', 'friendship-friend', 'friendship-disliked',
          'friendship-despised', 'friendship-nemesis')),
)


def _sim_social_connections(info):
    """The Sim's most dramatic third-party relationships (spouses, exes, sentiments, family, pets)."""
    tracker = getattr(info, 'relationship_tracker', None)
    if tracker is None or not hasattr(tracker, 'get_target_sim_infos'):
        return []
    scored = []
    sim_id = int(info.sim_id)
    hh_id = getattr(info, 'household_id', None)
    partner_ids = (getattr(info, 'spouse_sim_id', None), getattr(info, 'fiance_sim_id', None))
    try:
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
            friendship = round(float(tracker.get_relationship_score(other_id, RelationshipTrack.FRIENDSHIP_TRACK)), 1)
            romance = round(float(tracker.get_relationship_score(other_id, RelationshipTrack.ROMANCE_TRACK)), 1)
            same_hh = bool(hh_id and getattr(other, 'household_id', None) == hh_id)
            all_lower = ' '.join(bits + rev_bits).lower()
            priority = 100 if other_id in partner_ids else 0
            for weight, keys in _CONNECTION_PRIORITIES:
                if any(k in all_lower for k in keys):
                    priority += weight
            if same_hh:
                priority += 70
            if abs(romance) >= 20.0 or abs(friendship) >= 35.0:
                priority += 40
            if priority <= 0:
                continue
            scored.append((-priority, -(abs(romance) + abs(friendship)), {
                'id': str(other_id),
                'name': other_name,
                'same_household': same_hh,
                'friendship': friendship,
                'romance': romance,
                'bits': bits,
                'reverse_bits': rev_bits,
            }))
    except Exception:
        _record_error()
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored[:8]]


def _venue_snapshot():
    zone = services.current_zone()
    venue_service = getattr(zone, 'venue_service', None) if zone is not None else None
    active_venue = getattr(venue_service, 'active_venue', None) if venue_service is not None else None
    lot_name = None
    lot_traits = []
    business_info = None
    try:
        lot = getattr(zone, 'lot', None) if zone is not None else None
        if lot is not None and hasattr(lot, 'get_lot_name'):
            lot_name = lot.get_lot_name() or None
        zm_service = services.get_zone_modifier_service()
        if zm_service is not None and zone is not None:
            for zm in zm_service.get_zone_modifiers(zone.id):
                zname = getattr(zm, '__name__', type(zm).__name__)
                if zname and 'mueventapm_test' not in zname.lower():
                    lot_traits.append(zname)
        b_service = services.business_service()
        if b_service is not None and zone is not None:
            b_mgr = b_service.get_business_manager_for_zone(zone.id)
            if b_mgr is not None:
                b_type = getattr(b_mgr, 'business_type', None)
                business_info = {
                    'type': getattr(b_type, 'name', str(b_type)),
                    'is_open': bool(getattr(b_mgr, 'is_open', False)),
                    'is_owned_by_active': bool(getattr(b_mgr, 'owner_household_id', None) == services.active_household_id()),
                }
    except Exception:
        _record_error()
    return {
        'id': getattr(active_venue, '__name__', type(active_venue).__name__) if active_venue is not None else None,
        'stbl': _string_hash(getattr(active_venue, 'display_name', None)) if active_venue is not None else None,
        'lot_name': lot_name,
        'lot_traits': lot_traits[:6],
        'business': business_info,
    }


def _relationship_snapshot(actor_info, target_info):
    bits = list(actor_info.relationship_tracker.get_all_bits(target_info.sim_id))
    bit_names = [bit.__name__ for bit in bits]
    bit_stbls = [s for s in (_string_hash(getattr(b, 'display_name', None), actor_info, target_info) for b in bits) if s]
    reverse_bits = []
    reverse_bit_stbls = []
    for rbit in target_info.relationship_tracker.get_all_bits(actor_info.sim_id):
        if rbit.__name__ in bit_names:
            continue
        reverse_bits.append(rbit.__name__)
        rstbl = _string_hash(getattr(rbit, 'display_name', None), target_info, actor_info)
        if rstbl:
            reverse_bit_stbls.append(rstbl)
    return {
        'friendship': round(actor_info.relationship_tracker.get_relationship_score(
            target_info.sim_id, RelationshipTrack.FRIENDSHIP_TRACK), 2),
        'romance': round(actor_info.relationship_tracker.get_relationship_score(
            target_info.sim_id, RelationshipTrack.ROMANCE_TRACK), 2),
        'bits': bit_names,
        'bit_stbls': bit_stbls,
        'reverse_bits': reverse_bits,
        'reverse_bit_stbls': reverse_bit_stbls,
    }


def _record_skip(reason, interaction, actor=None, target=None, extra=None):
    _skip_counts[reason] = _skip_counts.get(reason, 0) + 1
    rec = {
        'type': 'skipped',
        'skip_reason': reason,
        'observed_at': time.time(),
        'interaction': type(interaction).__name__,
        'interaction_stbl': _string_hash(getattr(interaction, 'display_name', None), actor, target),
        'actor_name': _sim_name(actor) if actor is not None else None,
        'target_name': _sim_name(target) if target is not None else None,
    }
    if extra:
        rec.update(extra)
    _record(rec)


def _social_participants(interaction):
    actor = interaction.sim
    target = interaction.get_participant(ParticipantType.TargetSim)
    is_soc = bool(getattr(interaction, 'is_social', False))
    if not is_soc and target is not None and getattr(target, 'is_sim', False):
        iname = type(interaction).__name__.lower()
        if any(k in iname for k in ('petsocial', 'simtopet', 'talkto', 'praise', 'scold', 'lecture', 'calm', 'pamper')):
            is_soc = True
    if not is_soc:
        return None, None
    if actor is None or target is None or not getattr(target, 'is_sim', False):
        return None, None
    if actor.sim_info.sim_id == target.sim_info.sim_id:
        return None, None
    household_id = services.active_household_id()
    if actor.sim_info.household_id != household_id and target.sim_info.household_id != household_id:
        return None, None
    return actor, target


def _solo_vocal_actor(interaction):
    """Identify Shout Forbidden Words performed alone by an active-household Sim."""
    actor = getattr(interaction, 'sim', None)
    if actor is None or getattr(actor, 'sim_info', None) is None:
        return None
    if actor.sim_info.household_id != services.active_household_id():
        return None
    target = interaction.get_participant(ParticipantType.TargetSim)
    if target is not None and getattr(target, 'is_sim', False) and target.sim_info.sim_id != actor.sim_info.sim_id:
        return None
    if _string_hash(getattr(interaction, 'display_name', None), actor) in _SOLO_VOCAL_STBLS:
        return actor
    return None


def _busy(interaction, actor, target=None):
    """One exchange at a time: skip while a reply is still generating."""
    global _pending
    if _pending is not None and time.time() - float(_pending['observed_at']) > _PENDING_TIMEOUT_SECONDS:
        _pending = None
    if _pending is None:
        return False
    _record_skip('pending_in_flight', interaction, actor, target, {'pending_event_id': _pending['event_id']})
    return True


def _make_event(event_type, id_prefix, actor, target, interaction_name, interaction_stbl, outcome,
                player_message=None):
    global _event_count
    _event_count += 1
    venue = _venue_snapshot()
    event = {
        'type': event_type,
        'outcome': outcome,
        'event_id': '{}{}-{}'.format(id_prefix, int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': interaction_name,
        'interaction_stbl': interaction_stbl,
        'venue': venue['id'],
        'venue_stbl': venue['stbl'],
        'lot_name': venue['lot_name'],
        'lot_traits': venue['lot_traits'],
        'business': venue['business'],
        'actor': _sim_snapshot(actor),
        'target': _sim_snapshot(target) if target is not None else None,
    }
    if target is not None:
        event['relationship'] = _relationship_snapshot(actor.sim_info, target.sim_info)
    if player_message is not None:
        event['player_message'] = player_message
    return event


def _submit(event):
    global _pending
    _ensure_poller_alarm()
    _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    return event


def _observe(interaction, hook_stage, outcome_result=None):
    actor, target = _social_participants(interaction)
    if actor is None:
        solo_actor = _solo_vocal_actor(interaction)
        if solo_actor is not None and _enabled and hook_stage == 'start':
            if _mute_simlish:
                _apply_mute_to_info(solo_actor.sim_info)
            if not _busy(interaction, solo_actor):
                _submit(_make_event(
                    'solo_vocal', 'solo-', solo_actor, None, type(interaction).__name__,
                    _string_hash(getattr(interaction, 'display_name', None), solo_actor), 'SUCCESS'))
        return
    if _mute_simlish:
        _apply_mute_to_info(actor.sim_info)
        _apply_mute_to_info(target.sim_info)
    if not _enabled or hook_stage != 'outcome':
        return
    interaction_name = type(interaction).__name__
    if interaction_name in _PASSIVE_CONTAINERS:
        _record_skip('passive_container', interaction, actor, target)
        return
    interaction_stbl = _string_hash(getattr(interaction, 'display_name', None), actor, target)
    if interaction_name in _UNLABELLED_WAVES and not interaction_stbl:
        _record_skip('unlabelled_wave', interaction, actor, target)
        return
    if _busy(interaction, actor, target):
        return
    _submit(_make_event('social', '', actor, target, interaction_name, interaction_stbl, outcome_result))


class _ReplyPoller:
    def poll(self, _timeline_handle):
        global _enabled, _pending
        try:
            _drain_companion_console()
            if _enabled or _pending is not None:
                _ensure_companion_running()
            if _pending is None or _reply_path is None or not os.path.exists(_reply_path):
                return
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
                return
            manager = services.sim_info_manager()
            actor_info = manager.get(int(event['actor']['id']))
            target_data = event.get('target')
            target_info = manager.get(int(target_data['id'])) if target_data else None
            title = '{} ↔ {}'.format(event['actor']['name'], target_data['name']) if target_data else event['actor']['name']
            audio_dur = float((reply.get('tts') or {}).get('duration_seconds') or 0.0)
            if audio_dur <= 0.0:
                audio_dur = max(2.0, len(reply.get('text', '')) / 18.0)
            timeout_ms = int(round((audio_dur + 2.0) * 1000))
            _notify(title, reply['text'], actor_info, target_info, timeout_ms=timeout_ms)
            _record(dict(reply, type='displayed', displayed_at=time.time(), timeout_duration_ms=timeout_ms))
        except Exception:
            _record_error()


_poller = _ReplyPoller()


def _ensure_poller_alarm():
    global _alarm, _reply_path
    _reply_path = os.path.join(_data_directory, 'reply.json')
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


def _open_talk_dialog(actor_sim, target_sim):
    actor_info = actor_sim.sim_info
    target_info = target_sim.sim_info
    _open_text_dialog(
        actor_info,
        '{} → {}'.format(_sim_name(actor_info), _sim_name(target_info)),
        'What does {} say to {}?'.format(actor_info.first_name, target_info.first_name),
        target_info,
        lambda text: _submit_player_chat(actor_sim, target_sim, text),
    )


def _open_ask_self_dialog(actor_sim):
    actor_info = actor_sim.sim_info
    _open_text_dialog(
        actor_info,
        'Ask {}'.format(_sim_name(actor_info)),
        'Ask {} a question in English (or Hebrew / Russian):'.format(actor_info.first_name),
        None,
        lambda text: _submit_player_ask_self(actor_sim, text),
    )


def _submit_player_chat(actor_sim, target_sim, message_text):
    if _mute_simlish:
        _apply_mute_to_info(actor_sim.sim_info)
        _apply_mute_to_info(target_sim.sim_info)
    return _submit(_make_event('player_chat', 'chat-', actor_sim, target_sim, 'player_direct_chat', None,
                               'PLAYER_INITIATED', player_message=message_text))


def _submit_player_ask_self(actor_sim, question_text):
    if _mute_simlish:
        _apply_mute_to_info(actor_sim.sim_info)
    return _submit(_make_event('player_ask_self', 'ask-', actor_sim, None, 'player_ask_active_sim', None,
                               'PLAYER_INITIATED', player_message=question_text))


def _install_pie_menu_interaction():
    global _pie_interaction_cls, _pie_ask_self_cls
    affordance_mgr = services.affordance_manager()
    base_cls = affordance_mgr.get(13142) if affordance_mgr is not None else None
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
                            mute_command('on')
                            start_ai()
                            _notify('Banter Lab',
                                    'English Banter is on! Sims will now speak contextual English during socials.',
                                    actor_sim.sim_info)
                    elif actor_sim is not None and target_sim is not None and getattr(target_sim, 'is_sim', False):
                        _open_talk_dialog(actor_sim, target_sim)
                except Exception:
                    _record_error()
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
                    _record_error()
                return True

        _pie_ask_self_cls = BanterAskSelfPieMenuInteraction
        if hasattr(affordance_mgr, '_tuned_classes'):
            affordance_mgr._tuned_classes[_pie_ask_self_cls.guid64] = _pie_ask_self_cls

    count = 0
    for info in services.sim_info_manager().values():
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


_original_start = getattr(Interaction, '_banter_orig_start', Interaction._trigger_interaction_start_event)
_original_store_outcome = getattr(Interaction, '_banter_orig_outcome', Interaction.store_result_for_outcome)
_original_zone_loaded = getattr(Zone, '_banter_orig_zone_loaded', Zone.on_loading_screen_animation_finished)

Interaction._banter_orig_start = _original_start
Interaction._banter_orig_outcome = _original_store_outcome
Zone._banter_orig_zone_loaded = _original_zone_loaded


@functools.wraps(_original_start)
def _on_interaction_start(self, *args, **kwargs):
    result = _original_start(self, *args, **kwargs)
    try:
        _observe(self, 'start')
    except Exception:
        _record_error()
    return result


@functools.wraps(_original_store_outcome)
def _on_store_outcome(self, outcome, result, *args, **kwargs):
    ret = _original_store_outcome(self, outcome, result, *args, **kwargs)
    try:
        _observe(self, 'outcome', outcome_result=getattr(result, 'name', str(result)))
    except Exception:
        _record_error()
    return ret


Interaction._trigger_interaction_start_event = _on_interaction_start
Interaction.store_result_for_outcome = _on_store_outcome


@functools.wraps(_original_zone_loaded)
def _on_zone_loaded(self, *args, **kwargs):
    ret = _original_zone_loaded(self, *args, **kwargs)
    try:
        _load_settings()
        count = _install_pie_menu_interaction()
        if _enabled:
            _ensure_companion_running()
        if _mute_simlish:
            _sync_zone_mute()
        _cancel_polling()
        _ensure_poller_alarm()
        _drain_companion_console()
        _record({
            'type': 'pie_menu_installed',
            'sims': count,
            'enabled': _enabled,
            'mute_simlish': _mute_simlish,
            'observed_at': time.time(),
        })
    except Exception:
        _record_error()
    return ret


Zone.on_loading_screen_animation_finished = _on_zone_loaded


@sims4.commands.Command('banter.ai', command_type=sims4.commands.CommandType.Live)
def start_ai(_connection=None):
    global _enabled
    _cancel_polling()
    _ensure_poller_alarm()
    _enabled = True
    _save_settings()
    _ensure_companion_running()
    _console_print('Banter Lab on (companion pid={}).'.format(
        _companion_proc.pid if _companion_alive() else None), _connection=_connection)
    _record({'type': 'started', 'observed_at': time.time()})


@sims4.commands.Command('banter.talk', command_type=sims4.commands.CommandType.Live)
def talk_dialog_command(first_name: str = '', last_name: str = '', _connection=None):
    """Open the text-input modal to speak as the active Sim to a named Sim."""
    active_sim = services.get_active_sim()
    info = services.sim_info_manager().get_sim_info_by_name(first_name, last_name) if first_name else None
    target_sim = info.get_sim_instance() if info is not None else None
    if active_sim is None or target_sim is None:
        _console_print('Usage: banter.talk <first> <last> (the Sim must be on this lot).', _connection=_connection)
        return
    _open_talk_dialog(active_sim, target_sim)


@sims4.commands.Command('banter.ask', command_type=sims4.commands.CommandType.Live)
def ask_self_command(*words, _connection=None):
    """Ask the active Sim a question (or open the Ask modal if no question is given)."""
    active_sim = services.get_active_sim()
    if active_sim is None:
        _console_print('No active Sim found.', _connection=_connection)
        return
    question_text = ' '.join(words).strip()
    if not question_text:
        _open_ask_self_dialog(active_sim)
        return
    event = _submit_player_ask_self(active_sim, question_text)
    _console_print('Asked {}: "{}" (event={})'.format(_sim_name(active_sim), question_text, event['event_id']),
                   _connection=_connection)


@sims4.commands.Command('banter.mute', command_type=sims4.commands.CommandType.Live)
def mute_command(state: str = 'on', _connection=None):
    """Silence or restore Simlish voice_actor on instanced Sims in the zone."""
    global _mute_simlish
    _mute_simlish = state.lower() not in ('off', '0', 'false', 'stop')
    _save_settings()
    count = _sync_zone_mute()
    _record({'type': 'mute_state', 'mute_simlish': _mute_simlish, 'affected_sims': count, 'observed_at': time.time()})
    _console_print('Banter Lab Simlish mute={} (updated {} Sims).'.format(_mute_simlish, count), _connection=_connection)


@sims4.commands.Command('banter.stop', command_type=sims4.commands.CommandType.Live)
def stop(_connection=None):
    global _enabled, _mute_simlish, _pending
    _enabled = False
    _pending = None
    if _mute_simlish:
        _mute_simlish = False
        _sync_zone_mute()
    _save_settings()
    _console_print('Banter Lab stopped and Simlish voices restored.', _connection=_connection)


@sims4.commands.Command('banter.logs', command_type=sims4.commands.CommandType.Live)
def logs_command(mode: str = 'tail', _connection=None):
    """Stream companion logs to the cheat console (`on`/`off`) or print recent lines (`tail`)."""
    global _console_logging
    m = (mode or 'tail').lower().strip()
    if m in ('on', '1', 'true', 'off', '0', 'false'):
        _console_logging = m in ('on', '1', 'true')
        _save_settings()
        _console_print('Banter Lab console log streaming={}.'.format(_console_logging), _connection=_connection)
        return
    if _drain_companion_console(force_tail=10, _connection=_connection) == 0:
        _console_print('No companion console logs recorded yet.', _connection=_connection)


@sims4.commands.Command('banter.status', command_type=sims4.commands.CommandType.Live)
def status(_connection=None):
    cost_path = os.path.join(_data_directory, 'cost_summary.json')
    cost = {}
    if os.path.exists(cost_path):
        with open(cost_path, encoding='utf-8-sig') as stream:
            cost = json.load(stream)
    _console_print(
        'Banter Lab: enabled={}, mute={}, companion_alive={}, observed={}, skipped={}, '
        'cost(session=${:.4f}, total=${:.4f})'.format(
            _enabled, _mute_simlish, _companion_alive(), _event_count, _skip_counts,
            cost.get('session_usd', 0.0), cost.get('total_usd', 0.0)),
        _connection=_connection)
    active_sim = services.get_active_sim()
    _record({
        'type': 'status',
        'enabled': _enabled,
        'mute_simlish': _mute_simlish,
        'companion_alive': _companion_alive(),
        'observed_count': _event_count,
        'skip_counts': dict(_skip_counts),
        'cost_summary': cost,
        'venue': _venue_snapshot(),
        'active_sim': _sim_snapshot(active_sim) if active_sim is not None else None,
        'nearby': [_sim_name(info) for info in services.sim_info_manager().values()
                   if info.get_sim_instance() is not None],
    })


@sims4.commands.Command('banter.reload', command_type=sims4.commands.CommandType.Live)
def reload_command(_connection=None):
    """Hot-reload banter_lab from BanterLab.ts4script without restarting The Sims 4."""
    try:
        _cancel_polling()
        zipimport._zip_directory_cache.clear()
        mod = importlib.reload(sys.modules[__name__])
        count = mod._install_pie_menu_interaction()
        _console_print('Banter Lab hot-reloaded (pie menu attached to {} Sims).'.format(count), _connection=_connection)
    except Exception as exc:
        _console_print('Reload failed: {}'.format(exc), _connection=_connection)
        _record_error()


_load_settings()
_load_original_voice_actors()

if services.current_zone() is not None:
    _install_pie_menu_interaction()
    if _enabled:
        _ensure_companion_running()
    if _mute_simlish:
        _sync_zone_mute()
    _ensure_poller_alarm()

_record({'type': 'loaded', 'observed_at': time.time(), 'enabled': _enabled})
