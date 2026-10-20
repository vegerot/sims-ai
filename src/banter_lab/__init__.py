"""Observe actual socials and display contextual dialogue without choosing actions.

Dormant until `banter.start` or `banter.ai`. Model calls run in the companion.
"""

import functools
import json
import os
import time
import traceback

import alarms
import clock
import services
import sims4.commands
from interactions import ParticipantType
from interactions.base.interaction import Interaction
from relationships.relationship_track import RelationshipTrack
from sims.sim_spawner import SimSpawner
from sims4.localization import LocalizationHelperTuning
from ui.ui_dialog_notification import UiDialogNotification


_enabled = False
_last_shown = 0.0
_event_count = 0
_mode = 'fixed'
_pending = None
_alarm = None
_reply_path = None
# Zip-imported modules have a path inside the .ts4script archive.
_data_directory = os.path.join(os.path.dirname(__file__.split('.ts4script', 1)[0]), 'BanterLabData')


def _record(record):
    os.makedirs(_data_directory, exist_ok=True)
    with open(os.path.join(_data_directory, 'events.jsonl'), 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def _notify(title, text, owner=None):
    dialog = UiDialogNotification.TunableFactory().default(
        owner,
        title=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(title),
        text=lambda *args, **kwargs: LocalizationHelperTuning.get_raw_text(text),
    )
    dialog.show_dialog()


def _sim_snapshot(sim):
    info = sim.sim_info
    mood = info.get_mood()
    return {
        'id': str(info.sim_id),
        'name': '{} {}'.format(info.first_name, info.last_name).strip(),
        'traits': [trait.__name__ for trait in info.trait_tracker.personality_traits],
        'mood': mood.__name__ if mood else None,
        'mood_intensity': info.get_mood_intensity(),
    }


def _observe(interaction):
    global _last_shown, _event_count, _pending
    if not _enabled or not interaction.is_social:
        return
    actor = interaction.sim
    target = interaction.get_participant(ParticipantType.TargetSim)
    if actor is None or target is None or not getattr(target, 'is_sim', False):
        return
    household_id = services.active_household_id()
    if actor.sim_info.household_id != household_id and target.sim_info.household_id != household_id:
        return
    if _pending is not None:
        return
    now = time.monotonic()
    if now - _last_shown < 10:
        return
    _last_shown = now
    _event_count += 1
    event = {
        'type': 'social',
        'mode': _mode,
        'event_id': '{}-{}'.format(int(time.time() * 1000), _event_count),
        'observed_at': time.time(),
        'interaction': type(interaction).__name__,
        'actor': _sim_snapshot(actor),
        'target': _sim_snapshot(target),
        'relationship': {
            'friendship': actor.sim_info.relationship_tracker.get_relationship_score(
                target.sim_info.sim_id, RelationshipTrack.FRIENDSHIP_TRACK),
            'romance': actor.sim_info.relationship_tracker.get_relationship_score(
                target.sim_info.sim_id, RelationshipTrack.ROMANCE_TRACK),
        },
    }
    if _mode == 'ai':
        _pending = dict(event, zone_id=services.current_zone_id())
    _record(event)
    if _mode == 'fixed':
        _notify('Banter Lab: {} → {}'.format(event['actor']['name'], event['target']['name']),
                '"Well, this is already more interesting than standing by the fridge."\n\n'
                'Fixed test line. Detected: {}'.format(event['interaction']), actor.sim_info)


class _ReplyPoller:
    """Read complete companion results from a game-thread alarm."""

    def poll(self, alarm_handle):
        global _pending, _enabled
        if not _enabled or _pending is None:
            return
        if time.time() - _pending['observed_at'] > 30:
            _record({'type': 'expired', 'event_id': _pending['event_id']})
            _pending = None
            return
        if not os.path.exists(_reply_path):
            return
        try:
            with open(_reply_path, encoding='utf-8') as stream:
                reply = json.load(stream)
            if reply['event_id'] != _pending['event_id']:
                return
            event = _pending
            _pending = None
            if services.current_zone_id() != event['zone_id']:
                return
            if 'error' in reply:
                _enabled = False
                _notify('Banter Lab', 'Generation stopped: {}. Check the companion.'.format(reply['error']))
            else:
                title = '{} ↔ {}'.format(event['actor']['name'], event['target']['name'])
                _notify(title, reply['text'])
                _record(dict(reply, type='displayed', displayed_at=time.time()))
        except Exception:
            _record({'type': 'error', 'traceback': traceback.format_exc()})


_poller = _ReplyPoller()


def _cancel_polling():
    global _alarm, _pending
    if _alarm is not None:
        alarms.cancel_alarm(_alarm)
        _alarm = None
    _pending = None


_original_start = Interaction._trigger_interaction_start_event


@functools.wraps(_original_start)
def _on_interaction_start(self, *args, **kwargs):
    # Always let the game finish its original callback, including raising its own errors.
    result = _original_start(self, *args, **kwargs)
    try:
        _observe(self)
    except Exception:
        # A mod callback must not turn an observation failure into a broken game action.
        _record({'type': 'error', 'traceback': traceback.format_exc()})
    return result


Interaction._trigger_interaction_start_event = _on_interaction_start


@sims4.commands.Command('banter.start', command_type=sims4.commands.CommandType.Live)
def start(_connection=None):
    global _enabled, _last_shown, _mode
    _cancel_polling()
    _enabled = True
    _mode = 'fixed'
    _last_shown = 0
    sims4.commands.CheatOutput(_connection)('Banter Lab observing social interactions.')
    _notify('Banter Lab', 'Social observation is on for this session. Use banter.stop to turn it off.',
            services.active_sim_info())
    _record({'type': 'started', 'mode': _mode, 'observed_at': time.time(),
             'active_sim': _sim_snapshot(services.get_active_sim())})


@sims4.commands.Command('banter.ai', command_type=sims4.commands.CommandType.Live)
def start_ai(_connection=None):
    global _enabled, _last_shown, _mode, _alarm, _reply_path
    with open(os.path.join(_data_directory, 'bridge.json'), encoding='utf-8-sig') as stream:
        _reply_path = json.load(stream)['reply_file']
    _cancel_polling()
    _enabled = True
    _mode = 'ai'
    _last_shown = 0
    _alarm = alarms.add_alarm_real_time(
        _poller, clock.interval_in_real_seconds(0.5), _poller.poll, repeating=True)
    sims4.commands.CheatOutput(_connection)('Banter Lab: generated mode; start the companion first.')
    _record({'type': 'started', 'mode': _mode, 'observed_at': time.time(),
             'active_sim': _sim_snapshot(services.get_active_sim()), 'reply_file': _reply_path})


@sims4.commands.Command('banter.stop', command_type=sims4.commands.CommandType.Live)
def stop(_connection=None):
    global _enabled
    _enabled = False
    _cancel_polling()
    sims4.commands.CheatOutput(_connection)('Banter Lab stopped.')


@sims4.commands.Command('banter.status', command_type=sims4.commands.CommandType.Live)
def status(_connection=None):
    sims4.commands.CheatOutput(_connection)(
        'Banter Lab: enabled={}, mode={}, observed={}, log={}'.format(
            _enabled, _mode, _event_count, _data_directory))
    nearby = []
    for info in services.sim_info_manager().values():
        sim = info.get_sim_instance()
        if sim is not None:
            nearby.append({'id': str(info.sim_id), 'name': '{} {}'.format(info.first_name, info.last_name)})
    _record({'type': 'status', 'enabled': _enabled, 'mode': _mode,
             'active_sim': _sim_snapshot(services.get_active_sim()), 'nearby': nearby})


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
    _notify('Banter Lab', 'English text is working. This is a manual notification test.',
            services.active_sim_info())
    sims4.commands.CheatOutput(_connection)('Notification sent.')


_record({'type': 'loaded', 'observed_at': time.time(), 'enabled': False})
