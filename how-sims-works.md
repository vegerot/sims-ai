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

## Reading saves offline

On this installation, saves are DBPF containers with a type `0x0000000D` resource holding the save's serialized Protocol Buffers message. The installed `Game/Bin/Python/generated.zip` contains `protocolbuffers.FileSerialization_pb2.SaveGameData`, which describes that message. Its schema exposes households, Sims, zones, relationships, careers, skill progress, and business statistics. The DBPF index supplies each resource's stored size, decoded size, and compression type; these saves used RefPack compression (`0xFFFF`). Validate the decompressed size before interpreting the message. References: [Sims4Tools DBPF format](https://github.com/Kuree/Sims4Tools/wiki/DBPF-Format) and [a reference RefPack reader](https://github.com/gbataglini/sims4-workspace/blob/main/util/datamining/refpack.py).

**Observed compatibility problem:** running the installed generated messages and bundled protobuf library under a separate Python 3.7 interpreter initially reported successful parsing but populated no known fields. A tiny synthetic `guid=42` round trip failed too: decoder table keys were strings while incoming tags were bytes. A private in-process adapter converted `encoder.TagBytes` to Latin-1 bytes before generated-module imports and replaced the float/double decoder factories with the bundled `_StructPackDecoder` using `<f`/`<d`. The synthetic round trip and four actual copied saves then parsed. This changes only the analysis process; installed game files remain untouched. `IsInitialized()` alone did not detect the original failure.

Useful interpretation boundaries:

- Restrict preference analysis to played households; premade Sims and venues are not evidence of the player's choices. `is_unplayed`, the active household, and the last played Sim are useful together. One manual save had active household ID `1`, which did not identify the played household; do not rely on that field alone.
- Compare against a fresh save from the same installation. Default landlord businesses and numerous developmental milestone records also existed in our untouched test household. Counting those as player activity would have been misleading.
- Relationship tracks store friendship/romance values. Career event records can include readable tuning names. Skill `value` is raw progress, not a displayed level; installed `Skill.convert_to_user_value` uses the tuned `Skill.SKILL_LEVEL_LIST[skill_level_type]` thresholds. Those thresholds are needed for levels and cross-skill comparisons. [Sims4CommunityLibrary's enums](https://github.com/DeviantGameMods/Sims4CommunityLibrary/tree/main/Scripts/sims4communitylib/enums) provide useful ID names but are not a complete catalog of the installed game or custom mods.
- Business ownership is separate from operation: inspect business type and saved revenue/open-hour data. A venue named "Restaurant" does not prove the player owns or operates a restaurant.
- Compare lot names only where a stable lot identity has a unique match in both saves. Apartment and rental subdivisions can share identifiers. A changed name or customized venue does not establish whether it was built manually, downloaded from the Gallery, or inherited from an imported world.
- Save state is not an action log, a record of enjoyment, or a measure of human play time. Autonomy, cheats, imported content, and other mods can contribute to the state.

The read-only experiment used hashed copies in ignored `.local/save-analysis/`, with schema/reference inspection in `.local/research/`. It did not launch the game, send save contents to a model, or write to the original save folder. Keep original saves, account metadata, and household-specific summaries out of the public repository.

## Audio entry points for a fixed speech experiment

Inspection of installed `audio/primitive.pyc` found `PlaySound(target, sound_id, sound_name, is_vox, joint_name_hash, play_on_active_sim_only, immediate)`. Its `start()` constructs a sound-start message and sends a `SOUND_START` operation through the game's distributor. `stop()` detaches or stops that sound operation. `TunablePlayAudio` takes a `PROPX` resource key. These are game sound-resource entry points; this inspection does not establish arbitrary WAV-path playback, interception of animation-triggered speech, or selective suppression of existing Simlish.

An [EA developer's audio-format explanation](https://forums.ea.com/discussions/the-sims-4-mods-and-custom-content-en/i-have-a-few-questions-about-the-audio-configuration-fd04e3be-type-/396903) describes voice prefixes, voice/age suffixes, audio configuration resources (`0xFD04E3BE`), and varied samples. This is an older primary-source explanation, so conventions need checking against current resources. The [TS4 Sound Tool creator](https://modthesims.info/d/639090/) documents cloning a sound event, importing replacement audio, and saving a package. Creator documentation establishes a prior-art workflow, not that the tool or replacement works with this installation.

A useful independent next proof is one fixed English greeting in place of one known Simlish cue. First establish audio playback and replacement/suppression, then add generated speech. Fixed audio removes model and speech-synthesis latency from that mechanism test. No audio tool, package, or playback change was installed for this source inspection.

## Local source references and tuning readers

`findrepo sims` found useful local implementations, summarized with exact entry points in [repo-research.md](repo-research.md). S4CL distinguishes interaction start, outcome, and cancellation, and exposes venue context; Lot51 provides lifecycle hook examples. These are candidates for more grounded dialogue and cleanup during travel, not locally verified callback behavior yet. Lot51's balloon example uses icons and does not establish arbitrary text above Sims.

The local Sims 4 Workspace reader was tested against actual installed packages: 20,351 base XML tuning instances and 1,021 GP03 binary DATA tuning instances parsed successfully. The latter includes recipe definitions. A binary combined-tuning decoder is therefore already available; no independent binary-format implementation is needed for this tested case. See [the result](experiments/03-local-repo-readers/result.json). Override/load-order merging and complete coverage remain unverified, as do numerical skill thresholds and localized label resolution.

## Type annotations and independent Python versions

The Python 3.7 compiler/runtime used for our script archive successfully ran function annotations with `str`, `typing.List`, `typing.Dict`, and `typing.Optional`. It also successfully deferred an undefined `SimInfo` annotation with `from __future__ import annotations`, consistent with [Python 3.7's PEP 563 documentation](https://docs.python.org/3.7/whatsnew/3.7.html#pep-563-postponed-evaluation-of-annotations). Native annotations do not require a stripping stage. Use syntax and typing APIs supported by that runtime; newer grammar such as `type Alias = ...` cannot be made compatible merely by deferring annotations.

There is a specific runtime consumer to preserve: inspection of installed `sims4/commands.pyc` found that `Command.named_command` calls `inspect.getfullargspec`, `parse_args` reads `spec.annotations`, and `_parse_arg` invokes the annotated type to convert input. Our console commands should therefore retain concrete runtime annotations such as `first_name: str`. Do not enable deferred annotations across that module without checking the command parser. This is a bytecode finding; no deliberately broken command was installed or tested.

The community [Sims4ScriptingTemplate](https://github.com/mycroftjr/Sims4ScriptingTemplate) includes `type_hints.py` for generating game API stubs with mypy/protoc. Stubs can improve editor/type-checker knowledge without being loaded by the game. This is a source example, not a survey establishing which workflow is most common.

The external companion now runs with the already installed Python 3.15.0, independently of the game's Python 3.7 bytecode. On this PC `python3.15` works; the legacy `py -3.15` command does not resolve the uv-managed interpreter. The CLI and six real HTTP generation requests succeeded under 3.15. This did not relaunch the game or re-test the entire in-game bridge under the new interpreter.

## Reasoning effort and latency

The first live generation experiment omitted reasoning configuration. Its three responses reported 134, 195, and 136 reasoning tokens, so those were not reasoning-disabled measurements. The live OpenRouter catalog subsequently reported that `openai/gpt-6-luna` defaults to medium reasoning and supports `none`. [OpenRouter's reasoning guide](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens) distinguishes disabling reasoning from merely excluding its returned text.

The companion now sends `reasoning: {"effort": "none"}` by default, with a `--reasoning-effort` override, and records the effort and finish reason. In a six-call alternating comparison with the same captured test scene and prompt, omitted/default reasoning used 89, 121, and 110 reasoning tokens; explicit `none` reported zero for all three calls. Median request times were 2.476 seconds for default and 2.728 seconds for none. [Results and limits](experiments/04-reasoning-latency/result.json).

This verifies the parameter and removes reasoning work, but does not demonstrate faster responses in this small sample. Provider routing/cache state, network variation, and output lengths were uncontrolled. The timer covers the HTTP request/response; the companion's 0.25-second polling and game's 0.5-second polling occur outside it. Future speech generation/playback adds another latency path. Dialogue quality was not systematically evaluated.

## Fixed audio override and digital loopback verification

Base-game voice configurations (`0xFD04E3BE`) map 64-bit FNV-1 cue hashes (such as `vo_expr_greet_uncomfortable_45f_fa` -> `0xAE9960DCFFD5C32E`) to EA Layer 3 audio sample resources (`0x01A527DB`). Patch packages such as `ClientDeltaBuild1.package` can override those configurations with updated sample lists.

Using TS4 Sound Tool 1.1.29 with the creator-linked no-silence-removal `ealayer3 0.7.0` codec and `libmpg123.dll` from Destrospean's release, a 44.1 kHz stereo MP3 of `"Oh. Hello."` imported cleanly and round-tripped back to MP3 (duration 2.429 seconds). Trimming the resulting package with `s4pi` left exactly two resources: the overridden configuration `FD04E3BE!00000000!AE9960DCFFD5C32E` and the English sample `01A527DB!001407EC!2A95B32D1417C761`.

In live gameplay (`Banter Lab`), `PlaySound(services.get_active_sim(), sound_id=..., is_vox=False, immediate=True).start()` triggered both the untouched control cue (`0x04A64CD44542ACEC`) and the overridden greeting (`0xAE9960DCFFD5C32E`). Because system speakers remained muted overnight, digital output from `TS4_x64.exe` was verified through Windows Core Audio `IAudioMeterInformation` per-process session peaks and pre-endpoint-mute WASAPI loopback capture (`AUDCLNT_STREAMFLAGS_LOOPBACK`):

- The overridden `hello` probe produced a two-utterance session peak profile on `TS4_x64.exe`: `"Oh."` peaked at `0.1056` (`0.75–1.00 s`), dropped to `0.0020` across the preserved `0.65 s` pause (`1.05–1.70 s`), and peaked at `0.1253` on `"Hello."` (`1.75–2.30 s`).
- The captured loopback waveform correlated with our source `"Oh. Hello."` clip at **`r = 0.9790`** (25 ms RMS envelope), **`r = 0.9726`** (10 ms RMS envelope), and **`|r| = 0.6462`** (direct 16 kHz sample-by-sample waveform correlation across 38,034 samples), compared with `r = 0.4673` for the untouched Simlish control cue. [Results](experiments/05-fixed-speech/result.json), [console screenshot](experiments/05-fixed-speech/in-game-console.png).

Static `.package` overrides are indexed when the game starts, so they do not provide runtime injection of freshly synthesized dialogue during play. The temporary override package was removed after verification.

## Social interaction lifecycle, outcomes, and passive containers

Inspecting `interactions/base/interaction.pyc`, `interactions/utils/outcome.pyc`, and combined tuning revealed two structural facts about social interactions:

1. **Passive conversation containers vs. social mixers:** `sim_Chat` (`13998`, STBL `0x482BA41C` -> `"Chat with {1.SimFirstName}"`) and `sim_BeAffectionate` (`13991`, STBL `0xDB04B08F` -> `"Chat"`) are `SocialSuperInteraction` containers that keep Sims grouped in a conversation while individual `SocialMixerInteraction` actions run inside them. Despite its legacy internal name, `sim_BeAffectionate` has the user-facing display name `"Chat"` and runs during ordinary non-romantic conversations (`romance = 0.0`). Filtering `('sim_Chat', 'sim_BeAffectionate')` prevents the model from mistaking the container name for an affectionate action.
2. **Outcome timing relative to start and completion:** Wrapping `_trigger_interaction_start_event`, `store_result_for_outcome(self, outcome, result)`, `_trigger_interaction_complete_test_event`, and `cancel` in live Banter Lab gameplay showed that `store_result_for_outcome` fires **30–37 ms** after `start`, whereas `complete` fires several seconds later when the animation finishes (for example, `mixer_social_DiscussLocalFishingSpots`: `start` at `+0.000 s`, `outcome = SUCCESS` at `+0.037 s`, displayed AI banter at `+3.175 s`, and `complete` at `+7.619 s`). Triggering generation on `store_result_for_outcome` supplies the verified `OutcomeResult` (`SUCCESS` or `FAILURE`) while still displaying the banter mid-animation. [Results](experiments/06-social-outcomes/result.json), [in-game screenshot](experiments/06-social-outcomes/in-game-outcome-banter.png).

## String-table (STBL) resolution and richer scene context

Although `LocalizationHelperTuning` returns `LocalizedString` protobuf messages rather than Python strings inside the game, every `TunableLocalizedStringFactory._Wrapper` exposes `._string_id` and every `LocalizedString` protobuf exposes `.hash` (the 32-bit FNV-32 key into `Strings_ENG_US.package`, resource type `0x220557DA`).

A 90-line pure-stdlib DBPF v2.0 + RefPack (`0x10FB`/`0x50FB`) + ZLIB + STBL v5 reader in `companion.py` loads all **165,095** official English strings across the 141 installed `Strings_ENG_US.package` files in **2.04 seconds** (plus 11,171 additional strings from `Mods/*.package`, cached in `.local/stbl_en_us.json` for **0.36-second** startup). In live gameplay, this resolves:

- **Interaction labels:** e.g. `3744887214` -> `"Respectful Introduction"`, `701032414` -> `"Discuss Local Fishing Spots"`, `838640678` -> `"Discuss Logic Puzzles"`.
- **Trait labels:** e.g. `3818473410` -> `"Geek"`, `3765179452` -> `"Bookworm"`, `2182590620` -> `"Clumsy"`, `2332510722` -> `"Neat"`, `1495053396` -> `"Adventurous"`, `3554440226` -> `"Kleptomaniac"`.
- **Active visible buffs and reasons:** iterating `sim.sim_info.Buffs` where `buff.visible` is true captures `buff.buff_name` and `buff.buff_reason` / `default_buff_reason` STBL keys, resolving live moodlets such as `"Emotionally Mindful"` (`"(From Being Emotionally Mindful)"`) and `"Feeling Great"` (`"(From High Needs)"`).
- **Venue and relationship bits:** `services.current_zone().venue_service.active_venue` resolves `4239733099` -> `"Residential"`, and `relationship_tracker.get_all_bits(target_sim_id)` resolves `"Neighbor"`, `"Good Compatibility"`, `"Acquaintances"`, and `"Pleasant Conversation"`.
- **Sim voice metadata:** `sim_info.age`, `sim_info.gender`, `sim_info.voice_actor`, and `sim_info.voice_pitch` are captured on every Sim snapshot. [Results](experiments/07-rich-scene-context/result.json).

## Dual-portrait auto-expanded speech notifications

In Experiment 02, `UiDialogNotification.TunableFactory().default(...)` used the default `expand_behavior = USER_SETTING (0)` and `visual_type = INFORMATION (0)`, which allowed notification toasts to collapse to titles.

Setting `expand_behavior = UiDialogNotificationExpandBehavior.FORCE_EXPAND (1)`, `visual_type = UiDialogNotificationVisualType.SPEECH (1)`, and `information_level = UiDialogNotificationLevel.SIM (1)`, and passing `icon_override = IconInfoData(obj_instance=actor_info)` plus `secondary_icon_override = IconInfoData(obj_instance=target_info)` to `dialog.show_dialog(...)` causes the notification to pop open automatically in the top-right corner as a blue speech card displaying **both Sims' portraits** and the full two-line exchange. [Results](experiments/08-notification-presentation/result.json), [in-game screenshot](experiments/08-notification-presentation/dual-portrait-speech-popup.png).

## Companion per-Sim spoken English banter

To synthesize spoken English for dynamically generated lines without restarting the game or rebuilding `.package` files, `companion.py` maps each Sim's `gender`, `voice_actor`, and `voice_pitch` to a distinct voice (`Microsoft Zira` for female Sims; `Microsoft David` and `Microsoft Mark` alternated by `voice_actor` for male Sims so two male Sims in a conversation never share the same voice) and scales SSML `<prosody pitch>` from `voice_pitch`. Both lines are rendered in a single SSML pass (`0.60–0.82 seconds`) to a WAV file before `reply.json` is written. When `--speak` is passed, `companion.py` waits for the game's `_ReplyPoller` to record `{"type": "displayed"}` in `events.jsonl` and plays the WAV asynchronously via `winsound.PlaySound` so speech starts when the visual card appears. [Results](experiments/09-spoken-banter/result.json).

## Multi-monitor DPI scaling & Computer Use coordinate rules

1. **Cross-monitor `SetWindowPos` (`WM_DPICHANGED`):** When moving the windowed game across monitors with different DPI scaling (for example, from a 4K primary monitor at 150% DPI to a 1440p secondary monitor at 100% DPI), the first `SetWindowPos` call crosses the monitor boundary and triggers `WM_DPICHANGED`, which rescales the client area to `846×461`. Calling `SetWindowPos` a second time once the window is on the target monitor restores the exact `1280×720` DirectX client rect. When driving via `@oai/sky` (`sky.drag`), clicking the Windows Maximize button (`[]`) once the window is on `DISPLAY1` triggers `WM_SIZE` at `2560×1392` (`100%` native DPI), making all `@oai/sky` window coordinates 1:1 with Scaleform hit-testing.
2. **Windowed title-bar vertical offset (`ClientOrigin.y - WindowRect.top`):** `Windows.Graphics.Capture` window screenshots include the non-client Windows title bar at the top (`31–45 px` depending on window size/DPI), whereas *The Sims 4* in windowed mode interprets mouse coordinates relative to the DirectX client area. When clicking a small UI target (such as `OK` / `Cancel` in a modal dialog or a filter tab in the Relationship Panel), subtract the title-bar height (`y_click = y_screenshot - (ClientOrigin.y - WindowRect.top)`, typically `35–45 px`) so the click does not land on the button immediately below the target.
3. **Radial Pie Menu cursor warp:** Whenever a click opens a radial Pie Menu on a Sim or object, *The Sims 4* automatically teleports the OS mouse cursor to the center of the radial menu (clamped inward if the target was near the edge of the window). Seeing the cursor move to the Pie Menu's center in the post-click screenshot is normal engine behavior, not coordinate drift.
4. **Never call `activate_window` right before `click` on the same observation:** In `@oai/sky`, `sky.click` activates the target window automatically. Calling `sky.activate_window` first without a fresh `get_window_state` invalidates the observation (`user input was detected in this window`).

## Dynamic per-Sim Simlish voice suppression (`voice_actor` FNV-32 suffixes)

Disassembling `sims/sim_info_base_wrapper.pyc`, `audio/object_voice_actor_state.pyc`, and `server_commands/object_commands.pyc` revealed how the game resolves and overrides per-Sim Simlish voices:

- **`sim_info.voice_actor` is an FNV-32 suffix hash:** Each Sim's `voice_actor` property holds the 32-bit FNV-1 hash of their 2- or 3-letter voice suffix:
  - `'ma'` -> `1685527063` (`0x64771a17`, e.g. Alex Keen)
  - `'mb'` -> `1685527060` (`0x64771a14`, e.g. Geoffrey Landgraab)
  - `'mc'` -> `1685527061` (`0x64771a15`)
  - `'fa'` -> `1802970394` (`0x6b77251a`, Female Voice A, and the C++ default fallback when `voice_actor` is set to `0`)
  - `'fc'` -> `1802970392` (`0x6b772518`)
  - `'fd'` -> `1802970399` (`0x6b77251f`, e.g. Liberty Lee)
  - `'ca'` / `'cb'` -> `1853303381` / `1853303382` (`0x6e772a55` / `0x6e772a56`, Child Voices A/B, e.g. Rieko Okada)
- **Why `0` falls back while `0x7FFFFFFF` silences `is_vox=True` cues:** Assigning `info.voice_actor = 0` causes the C++ setter to assign the default `'fa'` hash (`1802970394`). Assigning a non-zero unmapped 32-bit integer (`0x7FFFFFFF` = `2147483647`) and distributing `SetVoiceActor` on both `SimInfo` and the live `Sim` instance (`Distributor.instance().add_op(sim, SetVoiceActor(actor_hash))`) stores `2147483647` verbatim.
- **Controlled `is_vox=True` measurement:** With the living-room TV removed (`objects.destroy`), `PlaySound(active_sim, sound_id=0, sound_name='vo_expr_greet_angry_25f', is_vox=True, immediate=True).start()` produced a `TS4_x64.exe` session peak of **`0.0415`** unmuted (`voice_actor = 1685527063`), dropped 10× to the **`0.0040`** ambient floor under `banter.mute on` (`voice_actor = 2147483647`), and preserved the true `voice_actor` (`1685527063`) in `_sim_snapshot` for companion TTS voice selection. Under `clock.pause`, simulation audio channels are paused (`MaxSessionPeak = 0.0` even with `immediate=True`). [Results](experiments/10-simlish-suppression/result.json), [console screenshot](experiments/10-simlish-suppression/in-game-vox-mute-console.png).

## Direct player-to-Sim conversation (`banter.say` and `banter.talk` modal)

Subclassing `UiDialogTextInputOkCancel` (`ui/ui_dialog_generic.pyc`) and overriding `on_text_input` plus `build_msg` (`msg.text_input.add().text_input_name = 'message'`) provides a native Sims 4 text-input modal without external library dependencies:

- `banter.talk` opens the in-game modal displaying the active Sim's portrait, header (`Alex Keen → Rieko Okada`), and text field. Submitting `OK` sends a `player_chat` event through the companion and displays the target Sim's in-character reply in the dual-portrait speech banner.
- `banter.say <message>` sends a `player_chat` event directly from the cheat console.
- Keeping a warm persistent PowerShell `System.Speech` worker in `companion.py` reduced two-speaker SSML WAV synthesis latency from `0.60–0.82 seconds` down to **`0.033–0.135 seconds` (33–135 ms)**. [Results](experiments/11-player-conversation/result.json), [modal screenshot](experiments/11-player-conversation/in-game-talk-modal.png), [reply screenshot](experiments/11-player-conversation/in-game-talk-reply.png), [`banter.say` screenshot](experiments/11-player-conversation/in-game-player-say.png).

## Multitasking activities, carried objects, and recipe STBL context

Sims frequently perform social mixers while seated, watching TV, reading, cooking, or carrying food/drinks:

- Iterating `sim.si_state` captures active non-social `SuperInteraction`s (`display_name` STBL hash) and their target objects (`target.catalog_name` STBL hash), resolving live labels such as `"Watch World Culture Network"` on `"Been There, Watched That TV"` and `"Sit"` on `"Squarely There Modern Loveseat"`.
- Iterating `sim.posture_state.carry_targets` (`left`, `right`, and `back` hands) captures carried objects even when the body posture is `sim-stand`, and `target.crafting_component.get_recipe().get_recipe_name()` extracts the STBL key for crafted dishes and drinks. [Results](experiments/12-activity-and-food-context/result.json).

## Zero-`.package` Sim Pie-Menu injection (`BanterPieMenuInteraction`)

Adding custom interactions to the Sim Pie Menu normally requires shipping XML tuning resources inside a `.package` file so `services.affordance_manager()` can construct a tuned `ImmediateSuperInteraction` class.

Inspecting `interactions/base/interaction.pyc`, `interactions/choices.pyc`, `objects/script_object.pyc`, and `zone.pyc` showed that a script mod can instead subclass an already-loaded base-game `ImmediateSuperInteraction` (`services.affordance_manager().get(13142)`) at runtime in Python 3.7:

- Setting `cheat = False`, `debug = False`, `simless = False`, `allow_user_directed = True`, `category = None`, and `pie_menu_priority = 30` (the maximum EP14 priority) places the interaction on **Page 1** of the radial Pie Menu without holding Shift.
- Overriding `@flexmethod def test(cls, inst, *args, target=DEFAULT, context=DEFAULT, **kwargs)` to return `TestResult.TRUE` when `target.is_sim` bypasses the base tuning's object state tests.
- Overriding `@flexmethod def _get_name(...)` with `LocalizationHelperTuning.get_raw_text(...)` renders `"Enable English Banter"` / `"Disable English Banter"` when clicking the active Sim, and `"Speak to <FirstName> (English)..."` when clicking any other Sim.
- Wrapping `Zone.on_loading_screen_animation_finished` attaches the class to `type(sim)._super_affordances` (`object_sim`) once per Sim class (without setting `sim.__dict__['_super_affordances']`, which would shadow later class-level affordance injections from other mods) when any lot finishes loading, so the player never needs to open the cheat console (`Ctrl+Shift+C`). [Results](experiments/13-pie-menu-interaction/result.json), [Enable screenshot](experiments/13-pie-menu-interaction/in-game-pie-menu-self.png), [Disable screenshot](experiments/13-pie-menu-interaction/in-game-pie-menu-disable.png).

## Desktop SAPI5 vs. WinRT OneCore voice registries & OpenRouter `gpt-audio-mini`

- Windows maintains two separate TTS voice registries:
  - `Windows.Media.SpeechSynthesis` (WinRT OneCore) registers `"Microsoft David"`, `"Microsoft Zira"`, and `"Microsoft Mark"`.
  - `System.Speech.Synthesis.SpeechSynthesizer` (Desktop SAPI5) only registers **`"Microsoft David Desktop"`** and **`"Microsoft Zira Desktop"`**. Passing `<voice name="Microsoft Zira">` without the `" Desktop"` suffix in SAPI5 SSML causes a silent fallback to `Microsoft David Desktop`.
- On OpenRouter, `google/gemini-3.8-flash` only exposes `audio` as an input modality (`HTTP 404` on audio output), whereas `openai/gpt-audio-mini` supports streaming 24 kHz 16-bit mono PCM (`modalities: ["text", "audio"]`, `audio: {"voice": ..., "format": "pcm16"}`, `stream: true`) in English, Hebrew, and Russian. Framing the system prompt as a closed-caption voice-over reader for a T-rated comedy game (`Read aloud verbatim: <read>...</read>`) prevents conversational replies. When `openai/gpt-audio-mini` still refuses a profane/spicy line (caught by `_transcript_matches` < 60% word overlap), OpenRouter's dedicated `/api/v1/audio/speech` endpoint with `model: "google/gemini-3.8-flash-lite-tts"` and `response_format: "pcm"` (`Kore`, `Aoede`, `Leda`, `Zephyr`, `Puck`, `Charon`, `Fenrir`, `Orus`) returns raw 24 kHz 16-bit mono PCM directly in `1.5–3.0 s` with zero refusals across English, Hebrew, and Russian ([Experiment 18](experiments/18-openrouter-tts-endpoint-benchmark/result.json)).

## Pet `extended_species` integer vs. `species` enum (`SimInfoBaseWrapper`)

In `sims/sim_info_base_wrapper.pyc`, `info.gender` (`Gender(self._base.gender)`) and `info.age` (`Age(self._base.age)`) wrap the underlying C++ integer in an `enum.Int` instance with a `.name` attribute, whereas `info.extended_species` returns `self._base.species` as a **raw Python `int`** (`1` = `HUMAN`, `2` = `DOG`, `3` = `CAT`, `4` = `SMALLDOG`, `5` = `FOX`, `6` = `HORSE`). Reading `getattr(info.extended_species, 'name', str(info.extended_species))` therefore produces `"1"` or `"4"` instead of `"HUMAN"` or `"SMALLDOG"`. Mapping `{1: 'HUMAN', 2: 'DOG', 3: 'CAT', 4: 'SMALLDOG', 5: 'FOX', 6: 'HORSE'}` in `_sim_snapshot` ensures pets are identified as `"SMALLDOG"`, `"DOG"`, or `"CAT"` in `events.jsonl` and `companion.py`.

## Hot-reloading `.ts4script` archives (`zipimport._zip_directory_cache` + `sys.path_importer_cache`)

In Python 3.7, `zipimport.zipimporter.__init__` binds `self._files = _zip_directory_cache[archive_path]` and `importlib.machinery.PathFinder` caches that `zipimporter` instance in `sys.path_importer_cache[archive_path]`. When a `.ts4script` archive is rebuilt on disk while *The Sims 4* is running, calling `zipimport._zip_directory_cache.clear()` alone leaves the cached `zipimporter` instance holding the old `self._files` offset/size table, causing `importlib.reload()` to read the wrong slice of the new ZIP and fail with `zlib.error: Error -5 while decompressing data: incomplete or truncated stream` or `OSError: zipimport: can't read data`. Clearing **both** `zipimport._zip_directory_cache.clear()` and `sys.path_importer_cache.clear()` before `importlib.reload(sys.modules[__name__])` forces `CustomFinder.find_spec` (`sims4/importer/custom_import.pyc`) to construct a fresh `zipimporter` that reads the updated ZIP central directory.

## Pet friendship tracks (`SIM_TO_PET_FRIENDSHIP_TRACK` vs. `FRIENDSHIP_TRACK`)

In `relationships/relationship_track.pyc`, `RelationshipTrack.FRIENDSHIP_TRACK` (`16650`) only stores Human-to-Human friendship; querying `tracker.get_relationship_score(other_id, RelationshipTrack.FRIENDSHIP_TRACK)` between a Human and a Pet (or between two Pets) always returns `0.0` even when they are Good Friends or Companions (e.g., `Kenya Bower` and her Shetland Sheepdog `meimei` in `Slot_00000002.save`, whose saved `SIM_TO_PET_FRIENDSHIP` score is `60.66`). Checking `RelationshipTrack.FRIENDSHIP_TRACK`, `RelationshipTrack.SIM_TO_PET_FRIENDSHIP_TRACK` (`159228`), and `RelationshipTrack.PET_TO_PET_FRIENDSHIP_TRACK` in order (`_friendship_score`) returns the true friendship score across Human↔Human, Human↔Pet, and Pet↔Pet pairs.

## Group social mixers (`TargetType.GROUP` & `ParticipantType.Listeners`)

In `interactions/base/interaction.pyc` (`Interaction.get_participants`, lines 3198–3209) and `interactions/social/social_mixer_interaction.pyc` (`SocialMixerInteraction.get_participants`, lines 423–430), `interaction.get_participant(ParticipantType.TargetSim)` only returns a Sim when `interaction.target` is a `Sim` (`TargetType.TARGET`). For untargeted group social mixers (`target_type & TargetType.GROUP`, where `interaction.target` is `None` or a group/object), `ParticipantType.TargetSim` returns `None`, while `interaction.get_participants(ParticipantType.Listeners)` iterates `interaction.social_group` (`pipeline_progress >= RUNNING`) and returns the active listening Sims in the conversation.

- **Computer Use harness rule:** When running in Codex, always use Codex's built-in Computer Use tool; never use the open-source `~\code\github.com\trycua\cua\` (`cua-driver`) unless you're not in Codex.
- **Reverse-engineering routing rule:**
  - **Python gameplay scripts (`simulation.zip`, `base.zip`, `core.zip`):** Inspect directly with `.local\python37\python.exe` (`marshal` + `dis` on `.pyc` code objects) or the decompiled sources in [repo-research.md](repo-research.md).
  - **DBPF `.package` / STBL / XML / DATA tuning & Scaleform `.gfx`:** Use the stdlib parsers in `companion.py` / `build.py` and references in [repo-research.md](repo-research.md).
  - **Native C++ engine boundaries (`TS4_x64.exe`, `Simulation_x64.dll`, `python37_x64.dll`) or general RE methodology:** Reference `C:\Users\Max\code\github.com\morluto\rea\.agents\skills\` (`reverse-engineer-anything\SKILL.md`, `reverse-engineer-anything\references\evidence-workflows.md`, `rea-analysis-optimization\SKILL.md`, `rea-tool-design\SKILL.md`) for summary-first inspection, separating decompiler inferences from bytecode/runtime observations, and native Ghidra/PE analysis.


## Crafted dish quality & chef attribution (`CraftingComponent` & `CraftingTuning`)

In `objects/components/crafting_component.pyc` and `crafting/crafting_tunable.pyc`:
- `crafting.crafter_sim_id` returns `_crafting_process.crafter_sim_id` (or `0` for uncrafted objects), which resolves via `services.sim_info_manager().get(crafter_id)` to the Sim who cooked the dish or mixed the drink.
- `obj.get_state(CraftingTuning.QUALITY_STATE)` returns the `ObjectStateValue` (`display_name` STBL hash + `__name__`, e.g. `"Normal"`, `"Excellent!"`, `"Poor"`), `obj.get_state(CraftingTuning.FRESHNESS_STATE) is CraftingTuning.SPOILED_STATE_VALUE` detects spoiled food, and `obj.get_state(CraftingTuning.MASTERWORK_STATE) is CraftingTuning.MASTERWORK_STATE_VALUE` detects masterworks.

## Active `Situation`s (`_display_name` vs. `BaseSituation.display_name`) & `OutfitCategory` C++ integers

- In `situations/base_situation.pyc`, `BaseSituation.display_name` is a `@property` that unconditionally raises `NotImplementedError`; `Situation` (`situations/situation.pyc`) overrides it to return `self._display_name`. Reading `getattr(sit, "_display_name", None)` avoids triggering `NotImplementedError` on non-`Situation` subclasses (`getattr` only suppresses `AttributeError`), while `sit.get_current_job_for_sim(sim)` returns the `SituationJob` (`tooltip_name` / `display_name` STBL hash, e.g. `"Host"`).
- In `sims/sim_info_base_wrapper.pyc`, `info.get_current_outfit()` returns `(outfit_category, index)` where `outfit_category` from `self._base.outfit_type_and_index` is a raw C++ `int` (`0` = `EVERYDAY`, `1` = `FORMAL`, `2` = `ATHLETIC`, `3` = `SLEEP`, `4` = `PARTY`, `5` = `BATHING`, `6` = `CAREER`, `7` = `SITUATION`, `8` = `SPECIAL`, `9` = `SWIMWEAR`, `10` = `HOTWEATHER`, `11` = `COLDWEATHER`). Non-human pets reuse non-zero outfit slots internally for pet clothing/collars (e.g. `meimei` reports `2` = `ATHLETIC` in a dog sweater), so `outfit` should only be exposed for human Sims (`species == "HUMAN"`).
- Non-human pets have dedicated C++ `voice_actor` hashes (`1836525760` for dogs, `1702304872` for cats). `_mute_replaced` only sets `0x7FFFFFFF` on human Sims (`_is_human(info)`) so pets still emit their real in-game barks/meows alongside their Windows SAPI5 collar translation.

## Speech loudness normalization & silence trimming (`_normalize_and_trim_pcm`)

Waveform measurements across real playtest WAVs in `.local/tts/` revealed a **`9.3–14.7 dB` (`3–5.5×`) RMS loudness gap** between `openai/gpt-audio-mini` (`sage`/`coral` frequently arriving at `-30.5` to `-35.9 dBFS` RMS / `-19.9 dBFS` peak) and Windows SAPI5 `Microsoft Zira Desktop` (`-21.2 dBFS` RMS with `~0.75 s` trailing dead-zero silence). `_normalize_and_trim_pcm` (`array('h')` in `companion.py`) trims leading/trailing silence below `-45 dBFS` (preserving `25 ms` attack and `55 ms` release) and normalizes speech-gated RMS to **`-18.5 dBFS`** with a `-1.0 dBFS` (`29200`) `tanh` soft-knee ceiling on every line before stitching `combined_pcm`, bringing Human neural and Pet SAPI5 lines within `~1.9 dB` (`-19.3` to `-21.2 dBFS`) with zero clipping.

## Carried hand props (`PostureState.carry_aspects`), pregnancy, & outdoor weather

- `PostureState.carry_targets` (`postures/posture_state.pyc`) accesses `(self.left.target, self.right.target, self.back.target)` directly and raises `AttributeError` when a hand aspect is `None`; iterating `sim.posture_state.carry_aspects` and reading `getattr(aspect, 'target', None)` safely captures carried books, drinks, umbrellas, and plates not already covered by `sim.si_state`.
- `SeasonService.season` (`seasons/season_service.pyc`) returns a `SeasonType` (`{0: 'SUMMER', 1: 'FALL', 2: 'WINTER', 3: 'SPRING'}`) and `WeatherService._current_event.__name__` (`weather/weather_service.pyc`) names the active weather event (e.g. `weather_Rain_Heavy_Warm`, `Weather_Snow_Light`). `_make_event` queries weather only when at least one participant has `sim.is_outside == True`, keeping indoor scenes free of irrelevant weather tokens while grounding outdoor banter in rain, snow, and heatwaves.

## `build_buy` C++ builtins (`get_lot_value`, `get_user_in_build_buy`), `RentalUnitManager`, & `RestaurantZoneDirector`

- **`build_buy.get_lot_value(zone_id, is_furnished)`** is a C++ `_buildbuy` builtin that returns a **2-tuple** `(value, ...)` on multi-unit / residential lots rather than a plain `int`; unwrap via `lv[0] if isinstance(lv, tuple) and lv else (lv or 0)`.
- **`build_buy.get_user_in_build_buy(zone_id)`** requires `zone.id` (`1` positional argument; calling `get_user_in_build_buy()` with `0` arguments raises `TypeError: function takes exactly 1 argument (0 given)`) and returns `account_id` while the player is inside Build/Buy Mode or `None` in Live Mode (`objects/game_object.pyc`, lines 311–312). Checking `get_user_in_build_buy(zone.id) is not None` inside `_ReplyPoller.poll` detects Build/Buy renovations (`abs(delta) >= 500`) with zero callback hooks.
- **`BusinessManager` & `RentalUnitManager` (`multi_unit/rental_unit_manager.pyc`):** When `getattr(getattr(b_mgr, 'tuning_data', None), 'min_and_max_star_rating', None) is not None`, `b_mgr.get_star_rating()` returns the `1.0–5.0` unit/restaurant star rating; on *For Rent* rental units, `b_mgr.rent` returns the daily rent (`§/day`) and `b_mgr.get_currently_owed_rent()` returns `due_rent + overdue_rent`.
- **`RestaurantZoneDirector` (`restaurants/restaurant_zone_director.pyc`):** Before dishes arrive on the table, `zd.get_active_group_order_for_sim(sim_id)` returns the active `GroupOrder` (`is_complimentary`) and `group_order.get_sim_order(sim_id)` exposes `food_recipe_id` and `drink_recipe_id`, resolved via `services.get_instance_manager(sims4.resources.Types.RECIPE).get(rid)`.
- **Mod subdirectories inside `saves/`:** `saves/WickedWhimsMod` and `saves/BasementalDrugs` store mod settings/state alongside `Slot_*.save*` files. Save cleanup scripts must filter strictly on `p.is_file()` (never `rmtree` subdirectories in `saves/`), and `Slot_ffffffff.save*` must be restored after Build/Buy tests because *For Rent* / MCCC autosaves to `Slot_ffffffff.save` on Build/Buy exit.
- **Codex `@oai/sky` window coordinates:** When `TS4_x64.exe` is maximized on `DISPLAY1` (`2560×1392`), omit `screenshotId` in `sky.click({ window, x, y })` to address exact `2560×1392` outer-window pixel coordinates (`y ≈ 46` for the `Ctrl+Shift+C` cheat input box, `x = 2495, y = 42` for the top-right Notification Wall).
