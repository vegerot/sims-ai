# How The Sims 4 works: findings from the birthday experiments

Keep this knowledge separate from the disposable experiment plan. Each finding states its evidence and limits. Local inspection below used Windows game build **1.128.90.1030** on **October 20, 2026**; recheck after game updates.

## Script mods and the embedded interpreter

The installed game contains `Game/Bin/python37_x64.dll` with file/product version **3.7.0**. Its Python scripts are bytecode inside `Data/Simulation/Gameplay/{base,core,simulation}.zip` and `Game/Bin/Python/generated.zip`.

A `.ts4script` mod is a ZIP archive containing Python modules. We compiled our module with Python 3.7.9 into an archive with a `banter_lab/__init__.pyc` entry and verified its ZIP integrity. After installation and restart, the module wrote its `loaded` event with `enabled: false`, establishing actual game import on this build. A modern external Python can handle development tasks while Python 3.7 handles only compilation to the game's bytecode format.

Evidence: installed executable/DLL version metadata and archive entries; [Sims modding guide](https://github.com/SanjoSolutions/sims4-modding-guide); [existing script-mod builder](https://github.com/dnavaria/sims4ai/blob/master/sims4_ai_mod/build.py); [official compiler runtime](https://www.python.org/downloads/release/python-379/).

## Social interactions: actor, target, and callback

The game models a social interaction as an object with a performing Sim and participants. The interaction type carries the specific social action; observing this is more useful than guessing a conversation from the screen.

Installed bytecode verifies:

- `Interaction._trigger_interaction_start_event(self)` takes only `self`.
- `SocialMixerInteraction` overrides that callback and first calls `super()`, so a wrapper on the base method can observe social mixers without wrapping both classes.
- The actor is accessible through `interaction.sim.sim_info`.
- `interaction.get_participant(ParticipantType.TargetSim)` identifies the other Sim more explicitly than assuming the raw target is a Sim.
- `is_social` distinguishes social interaction types from the base interaction class.

A wrapper must preserve the original callback, return value, and original exceptions. Experimental observation should not turn a logging or generation problem into a broken game action.

**Live result:** the base hook captured Mortimer Goth → Marcel Price, interaction `sim_BeAffectionate`, followed by other social starts. The corresponding in-game fixed-line notification was visually verified. Three samples and build identity are in [the first experiment result](experiments/01-social-hook/result.json). The initial scope included NPC-only scenes; useful ongoing dialogue needs a deliberate scene/household filter.

The next build filtered to interactions involving the active household. A native `interactions.push sim_Chat` request made Alex Keen route to Mortimer Goth and begin a conversation; the observer then captured chat, handshake, mischief, and joke events. Queuing and actual interaction start were observed separately.

Evidence: targeted inspection of installed `interactions/base/interaction.pyc` and `interactions/social/social_mixer_interaction.pyc`; [Sims4CommunityLibrary dispatcher](https://github.com/DeviantGameMods/Sims4CommunityLibrary/blob/main/Scripts/sims4communitylib/events/interaction/common_interaction_event_dispatcher.py). **Not yet verified:** useful event coverage, timing, repeated events, and interaction with installed mods during actual gameplay.

## Displaying text

`UiDialogNotification.TunableFactory().default(...)` creates a notification. `LocalizationHelperTuning.get_raw_text(text)` produces a localized-string object for arbitrary text; title/text callbacks can supply it. Call `show_dialog()` to display the notification.

The APIs and factory tunables were checked against installed bytecode and [Sims4CommunityLibrary's notification implementation](https://github.com/DeviantGameMods/Sims4CommunityLibrary/blob/main/Scripts/sims4communitylib/notifications/common_basic_notification.py). Both manual and social-triggered notifications were then visually verified in-game. Other installed mods' startup notifications queued ahead of ours, so a successful `show_dialog()` did not mean the message was immediately visible. Notifications are a small experiment interface; this is not a decision about the final UI.

**Reading generated text:** the Notification Wall button was verified at the top right, immediately left of the options menu. Opening it showed the complete generated Mortimer/Alex exchange; [screenshot](experiments/02-context-and-generation/in-game.jpg). Popups may collapse to titles according to the user's setting. Installed notification enums distinguish `USER_SETTING` from `FORCE_EXPAND`; urgency is a separate `DEFAULT`/`URGENT` choice. The current prototype honors the default user expansion behavior. Its `displayed` log tag means `show_dialog()` was submitted, not that the body was immediately visible.

## The game console as an experiment interface

`Ctrl+Shift+C` opens the in-game console ([EA's cheat guide](https://www.ea.com/games/the-sims/the-sims-4/faq/cheats)). Our `banter.test`, `banter.start`, `banter.stop`, and `banter.status` commands are registered as `CommandType.Live`; no testing-cheats setting was needed to run them on a live lot.

Targeted inspection of this build also found live commands `sims.get_sim_id_by_name First Last`, `sims.summon_sim_to_zone <id>`, `interactions.push <interaction> <target_id> <actor_id>`, and `persistence.save_to_new_slot <unused_decimal_id> "Name"`. The save command was tested with an explicitly unused ID 8888 and created `Slot_000022b8.save`. Do not assume it automatically allocates an ID or safely replaces a collision.

`sims.spawn` is marked debug-only in this build; its appearance in a cheat list does not establish ordinary-console availability. No verified console shortcut completed the initial Create a Sim flow. New Game created `Slot_ffffffff.save` before our named save.

## Context: personality, mood, and relationships

- `TraitTracker.personality_traits` returns personality traits. `equipped_traits` includes additional hidden traits and is a poor unfiltered description of personality.
- `BuffComponent.get_mood()` and `get_mood_intensity()` expose current mood state; the Sim-info mixin also provides forwarding.
- `RelationshipTracker.get_relationship_score(target_sim_id, track)` requires a real relationship-track object. Integers guessed from unrelated examples are not a verified friendship/romance API.
- `RelationshipTrack.FRIENDSHIP_TRACK` and `.ROMANCE_TRACK` are defined on `relationships.relationship_track.RelationshipTrack` and used by existing game code. These are the concrete candidate track objects.
- `sim_info.get_mood()` and `.get_mood_intensity()` are supported by component-method forwarding from BuffComponent. Personality trait tuning objects expose `.__name__`, as does the mood tuning class.
- Comparing either participant's `household_id` with `services.active_household_id()` filters to household-involved scenes. This is also how the game computes `SimInfo.is_npc`.

Evidence: targeted inspection of installed class/property/method bytecode and game use sites, followed by the live samples below. `interaction.get_name()` returns a localization object, so the tuned interaction class name is the initial semantic identifier rather than assuming localization objects stringify into English. Richer scene context and localization-table resolution remain separate work.

**Live context verified:** Alex Keen had Neat, Adventurous, and Kleptomaniac traits; Mortimer Goth had Outgoing, Bookworm, and Creative. Mood names included Fine, Happy, and Uncomfortable. Friendship changed from `0.0` at chat start to positive values during normal socializing, while romance stayed `0.0`. These fields serialized into actual event records without observer errors. The model received scene context rather than internal Sim IDs. See [context samples and round trips](experiments/02-context-and-generation/result.json).

## Game callbacks and external model work

The installed alarm API provides `alarms.add_alarm_real_time(owner, time_span, callback, repeating=False, use_sleep_time=True, cross_zone=False)`. `clock.interval_in_real_seconds(seconds)` creates its interval; the callback receives one alarm handle. `alarms.cancel_alarm(handle)` cancels it. The implementation uses the game's wall-clock timeline.

This provides a way to drain external model results from a game callback instead of modifying game/UI objects on a network worker. Keep the alarm owner and handle referenced. Exact signatures were inspected locally and the normal bridge path was verified below; timeout, provider-error, pause, and travel cases remain unverified.

**Live bridge verified:** the game wrote observed scene events, a Python 3.13 companion called `openai/gpt-6-luna` through OpenRouter, and the companion atomically replaced a reply file. A game alarm matched replies by event ID and submitted their text through the notification API. Three live exchanges completed with provider-call latencies of `5.163`, `4.105`, and `3.891` seconds; the third exchange was read in the Notification Wall. This establishes the normal path, not every timeout, provider-error, pause, or travel case.

The companion reads events from the game's directory but writes replies inside the experiment workspace. Python 3.13's protected-Documents write probe was blocked by Controlled Folder Access; the workspace probe succeeded. `BanterLabData/bridge.json` provides the game the reply path. This lets each process use its own permitted file locations without changing additional protection settings. The API credential stays in the companion environment.

## Paths and deployment: avoid assumptions

- The active Documents path on this PC resolves to `C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4`. Mods and script mods are enabled in `Options.ini`.
- The installed `sims4.paths` module **does not define `USER_DATA_ROOT`**. That name appeared plausible but was rejected by inspecting this build.
- We found no verified Sims reference for a `-userDataPath` command-line flag. The executable contains `userdata` and `SetUserDataFolder`; those strings do not prove such a flag is supported. Do not use a guessed flag to claim save isolation.
- Python 3.7's attempted creation of a child under this OneDrive-backed Mods directory failed with `WinError 2`. A read-only comparison showed Python 3.7 and 3.13 could both recognize and list the parent. Defender's operational event **1123** then established the cause: **Controlled Folder Access** blocked Python at 00:27 and PowerShell at 00:30 from creating `Mods/BanterLab`. This is not an observed OneDrive/mod-loader problem. No protection or OneDrive settings were changed.

Existing-save preservation is checked with a before/after hash manifest. A separate test save is the current experiment approach; it does not imply a separate game profile.

**Observed shared-autosave behavior:** entering New Game changed `Slot_ffffffff.save` even though the test was subsequently saved under a unique slot. The two original numbered saves stayed byte-for-byte unchanged. The original autosave was found in `.save.ver0` by matching its SHA-256 against the initial manifest and copied to ignored `.local/save-backups/Slot_ffffffff.save` for restoration after the game closes. A unique named save does not isolate the shared autosave: back up save contents, not just hashes, before another such experiment.

This observation applies to this installation with its existing mods; we have not established which component manages the shared autosave or its day/week/month rotations. After testing, the game was closed, the original autosave restored, and all three original `.save` hashes matched the initial manifest.

The game's main menu was reached through the installed executable. An initial capture of the inactive full-screen game showed the foreground video instead; activating the returned game window and recapturing produced the actual main menu. Treat window selection and screenshot content as separate things to verify before acting.

## Dialogue, audio, and actions are different capabilities

Generating an English line does not replace a Simlish sound, synchronize a mouth animation, or make a Sim perform what the line describes. Likewise, selecting an action identifier does not prove that the action was accepted or completed by the game.

Prior-art inspection found one [action executor](https://github.com/dnavaria/sims4ai/blob/master/sims4_ai_mod/ai_sim_mod/tool_executor.py) that can fall back to descriptive notifications and return `proposed_only`. It is therefore research material, not evidence that its advertised actions work.

[Sims AI Chat's project site](https://sims4ai.duckdns.org/) advertises generated speech for directed chats, while ordinary socials generate text. [Mute Voice](https://www.curseforge.com/sims4/mods/mute-trait) describes silencing individual Sims via a voice trait. [TS4 Sound Tool](https://modthesims.info/d/639090/) documents offline audio-resource creation. These are creator/source findings; no runtime voice replacement has been tested here.

## Evidence artifacts

Targeted bytecode inspection helpers and listings live in ignored `.local/research/`. These may contain game implementation details; keep distributable source separate. Future live screenshots, event samples, API measurements, and corrections should be linked here or from append-only progress entries as they become available.
