# Experiment progress

Append-only, oldest first. Read the plan, then the newest entries; verify the live state before resuming.

## 2026-10-20 — Interview and handoff setup

- 🎯 Max confirmed automatic English banter, text first, then generated dialogue; this PC is the test machine and preserving the birthday surprise is preferred. The agreed experiment starts with a fixed line on a real social interaction.
- 📚 Created the [plan](plan.md), this log, and [reusable Sims findings](how-sims-works.md). The initial [research notebook](planning.md) and [glossary](CONTEXT.md) already exist. Max expects to replace plan/progress when production work starts.
- 🔎 Inspected installed game version `1.128.90.1030` and embedded Python `3.7.0`. Targeted bytecode inspection verified the base social-start callback and notification/alarm API patterns; no live callback behavior has been verified. See [evidence](how-sims-works.md).
- 🧰 Downloaded the official Python 3.7.9 embeddable archive into ignored `.local/`, checked its checksum against python.org, and compiled `dist/BanterLab.ts4script`. The archive contains `banter_lab/__init__.pyc` and passed ZIP integrity checks.
- 🧪 Recorded SHA-256 hashes of three existing `.save` files in ignored `.local/saves-before.json`. The mod is dormant until `banter.start`; it has not been verified in-game.
- 🧱 Installation through the Python 3.7 build script failed with `WinError 2` creating a child of the OneDrive-backed Mods directory. PowerShell confirms the parent exists and is a reparse point. Cause is not yet established. Do not infer that the game's mod loader is broken from this builder failure.
- 🎮 Launched the installed game. Computer Use initially reported no targetable window, but a subsequent window inventory found `The Sims™ 4` and the process is running. No save has been opened during this experiment.
- 🔑 An `OPENROUTER_API_KEY` environment variable is present; its value was not printed. The public model catalog includes `openai/gpt-6-luna`. No authenticated model request has been made.

Next:

1. Separate the legacy bytecode compiler from modern filesystem installation; investigate the OneDrive path with a small read/write experiment.
2. Install only our dormant experimental archive, then restart the game if needed.
3. Create a separate test save, verify notification and social hook, and inspect the captured events before adding generation.

## 2026-10-20 — Installation cause established

- 🔎 Correction to the earlier open question: both Python 3.7 and 3.13 can recognize/list the Mods directory. Defender Operational events 1123 explicitly identify Controlled Folder Access blocking Python at 00:27 and PowerShell at 00:30 from creating `Mods/BanterLab`. The parent being a OneDrive reparse point was incidental to this observed failure; no OneDrive or security settings were changed.
- 🧰 Simplified `build.py` to compile/package only. Removed its blocked installation option. The built archive remains outside protected Documents; no mod has been installed successfully.
- 🎮 Activated the game window and visually confirmed its main menu. An earlier inactive-window capture showed the foreground video, so it was not accepted as game evidence. No save has been opened.
- 💬 Requested confirmation to copy our archive through File Explorer and restart for testing. The user asked whether the security alerts were ours; confirmed the protected-folder alerts match our two attempts. That question does not authorize the copy.

Next:

1. On confirmation, copy `dist/BanterLab.ts4script` using File Explorer (or verify the user's manual copy), then restart the game.
2. Create a separate test save, run `banter.test` and `banter.start`, and verify a real social interaction.
3. Recheck the three existing-save hashes and append live results; generated dialogue remains downstream of the integration proof.

## 2026-10-20 — Installation succeeded; display prepared

- ✅ Max reported granting access and asked us to retry. PowerShell then created `Mods/BanterLab` and copied the archive successfully. Installed/source SHA-256 matched: `8CD8CB103BE625E80E9CC17AD42AFAC21F7D4271CF7E9920A36B2F1DCFD8BD26`.
- 🖥️ Max requested normal windowed 720p. He handled the initial display UI after live-input detection prevented automation. Persisted settings were then windowed `1024×768`; after he said to continue, we exited normally from the main menu, backed up the options in `.local/Options.before-720p.ini`, and set exactly `1280×720`, `fullscreen = 0`, `windowedfullscreen = 0` while the game was closed. File contents verified; reopened display remains to be checked visually.
- 🎮 Relaunched the installed game to load the new script archive. No existing save has been opened.

Next:

1. Verify the windowed display and whether the dormant module loaded; inspect our log and any new game exceptions.
2. Create the separate test save and prove notification plus one real social event.

## 2026-10-20 — Script module loaded

- ✅ The restarted game created `Mods/BanterLab/BanterLabData/events.jsonl` with a `loaded` event and `enabled: false`. This establishes that this game build imports our Python 3.7 bytecode archive from the existing Mods directory. It also verifies the archive-relative log path in the actual game.
- 🖥️ The game reopened in a normal bordered window. Settings file has `1280×720` and both fullscreen flags at zero; screenshot dimensions are logical pixels under Windows display scaling.

Next:

1. Create the separate test save, test a notification, and observe a social interaction before adding context fields or network work.

## 2026-10-20 — Disposable household setup

- 🎮 Started New Game and reached Create a Sim, leaving the three existing saves unopened. A disposable Sim has random personality traits; the household setup is not complete or saved yet.
- 🧱 Live input detection repeatedly interrupted individual automation actions. Requested a short hands-off interval or a user-created test household; do not keep issuing blind inputs against stale screenshots.
- 🛡️ Rechecked the three original `.save` files against `.local/saves-before.json`; all hashes remain unchanged.

Next:

1. Complete the disposable household once game controls are available, then place it in the world.
2. Run `banter.test`, `banter.start`, and a normal social interaction; inspect event/log evidence.

## 2026-10-20 — First live experiment passed

- ✅ The user completed the remaining CAS setup while attempting to help, then handed controls back. Placed the disposable Alex Keen household in Willow Creek's Daisy Hovel. Existing saves were not loaded.
- ⌨️ Verified `banter.test` in the console and visually saw its English notification. `banter.start` armed the observer. Inspected game code for built-in live commands rather than assuming old cheat lists work.
- 💾 Verified numeric save slot 8888 was unused, then ran `persistence.save_to_new_slot 8888 "Banter Lab"`. Confirmed `Slot_000022b8.save` exists (about 5 MB). New Game also created `Slot_ffffffff.save`; neither is one of the original three files.
- 🧪 Real social callbacks produced logged actor/target IDs and names plus tuned interaction names. Visually verified the fixed-line notification for Mortimer Goth → Marcel Price. Subsequent wave/affection events were observed without logged observer errors. Representative [result and three samples](experiments/01-social-hook/result.json) are retained.
- 📚 Observation: the initial hook also catches NPC-only scenes away from the active household. This motivates a household filter before ongoing dialogue generation. Notifications may queue behind other installed mods' startup messages, so console success and visible display were checked separately.
- 🧩 Prepared the next build with verified personality/mood/relationship fields, household filtering, and optional generated mode. Added a small companion using the existing OpenRouter key; network calls remain outside the game. Communication is a scene-event log plus an atomic reply file, with game-thread polling. These additions compile but are not yet loaded/tested; no API call has been made.

Next:

1. Restart with the updated archive, load only Banter Lab, and inspect real context values in fixed mode.
2. Start the companion and switch to `banter.ai`; verify generated text appears for the correct scene, record latency/usage, and stop it after testing.
3. Recheck original-save hashes and document any failures or limits.

## 2026-10-20 — Companion filesystem boundary

- 🔎 A small reply-write probe using installed Python 3.13 failed; Defender event 1123 confirmed that this separate executable still lacks protected-Documents write access. Do not confuse permission granted to PowerShell/the compiler with permission for every Python installation.
- 🧩 Kept companion output in `.local/bridge/reply.json` instead. The game reads the configured path from `Mods/BanterLab/BanterLabData/bridge.json`, written using the already-authorized PowerShell process. The companion's write/read/remove probe succeeded in the experiment workspace. No additional security-setting change was made.
- ⌨️ Added `banter.summon First Last` for deterministic test-save setup, using the same manager lookup and SimSpawner API as the built-in commands. Arrival is recorded separately from a summon request. `banter.status` logs active and currently instanced Sim IDs, avoiding transcription of long console numbers.

Next:

1. Deploy the rebuilt archive with this reply-path change and restart; the prior running build does not yet read bridge.json.
2. Load Banter Lab, verify household-filtered context, and then test the model bridge.

## 2026-10-20 — Model connection verified on a captured scene

- 🌐 Ran one authenticated request using an actual scene from the first hook experiment and the existing OpenRouter credential. Model `openai/gpt-6-luna` returned a two-line Mortimer/Marcel exchange in 3.157 seconds. This proves model connectivity and generation from captured scene data, not the in-game reply bridge or personality grounding yet.
- 📊 Returned usage was 249 prompt tokens and 122 completion tokens (81 reasoning). OpenRouter reported `cost: 0`, `is_byok: true`, and upstream inference cost `0.0000859`; preserve those distinct fields rather than presenting the upstream estimate as the user's bill. Probe artifacts are ignored `.local/model-probe-*.json`.
- 🧩 Removed game-internal Sim IDs from the scene sent to the model; only the relevant participant context and interaction go upstream. Configured companion stdout as UTF-8 after the first console capture mangled a typographic apostrophe; reply-file encoding was already UTF-8.
- 🧰 Installed the final bridge-path build after a normal main-menu exit. Verified installed/source hash `FA65BDF2309F1253D952328926D59193DA8399FDC314ED885A2262948B6C8A70`, then relaunched. The newer companion stdout change does not alter the script archive.

Next:

1. Load the disposable Banter Lab save, run fixed mode and summon a test NPC, and inspect actual context values.
2. Start the companion, switch to AI mode, and prove the returned dialogue is displayed in-game.

## 2026-10-20 — Shared autosave preservation correction

- 🔎 The next save check found the two original numbered saves unchanged, but the original `Slot_ffffffff.save` changed when the new game entered live mode. Earlier checks reporting three unchanged files predated that transition. The new `Slot_00000004.save` is also a test save, not one of the original three.
- 🛡️ Located the exact original autosave in `Slot_ffffffff.save.ver0` using the pre-test SHA-256. Copied it into ignored `.local/save-backups/Slot_ffffffff.save` and reverified the initial hash. Also copied the two unchanged original numbered saves into that backup directory. All three original save contents are now preserved for restoration/checking after testing.
- 📚 Correction to the test approach: a unique named test save does not isolate the shared autosave. Back up actual contents before future tests rather than relying solely on hash detection. Do not report all original files unchanged until the autosave has been restored after closing the game.
- 🌐 The generation companion is waiting in exec session `95652`; it only processes new AI-mode events. No in-game model request has been triggered yet.

Next:

1. Finish context and generated-dialogue checks in Banter Lab.
2. Stop observer and companion; close the game, restore the original autosave from the verified backup, and check all three initial hashes.

## 2026-10-20 — First generated-dialogue slice verified and stopped

- ✅ Loaded the named Banter Lab save, entered its Keen household, and verified actual personality/mood snapshots. Native `interactions.push sim_Chat 792940683143809502 792940683128864783` queued Alex → Mortimer; routing and later real social starts were observed separately. The household filter captured their chat, handshake, mischief, and joke events, with real friendship/romance scores and no logged observer errors.
- 🌐 Started `banter.ai` with the companion already listening. Three AI-mode events produced three results matched by event ID and submitted through the game notification API. Provider-call times were 5.163, 4.105, and 3.891 seconds. Relevant context, requests, response text, usage, and limits are retained in [result.json](experiments/02-context-and-generation/result.json).
- 👀 Opened the Notification Wall using its top-right button and read both lines of event `1792483374962-7` in the actual game. Retained [the screenshot](experiments/02-context-and-generation/in-game.jpg). The code's `displayed` tag denotes a `show_dialog()` submission; this separate visual check establishes actual rendered body text for that exchange.
- 📚 Found a presentation limitation: popups honor the user's expansion preference and can collapse to just the title. Other installed mods queue messages too. `FORCE_EXPAND` exists, but we have not changed presentation or chosen the birthday UI yet. The prototype currently uses notifications, not final speech balloons.
- 🛑 Ran `banter.stop` successfully, canceled game polling, and stopped companion session `95652` with Ctrl+C. Closed the game normally, leaving the existing named test checkpoint rather than saving the later experiment state.
- 🛡️ Restored the exact original `Slot_ffffffff.save` from the verified backup after the game exited. All three original hashes now match: `Slot_00000002.save`, `Slot_00000003.save`, and `Slot_ffffffff.save`. No new lastException/UIException/Crash files were found for this run. Test saves `Slot_00000004.save` and `Slot_000022b8.save` remain available.
- 🖥️ Final options file verified normal windowed `1280×720`: fullscreen and windowedfullscreen are both zero. The experimental archive remains installed but is dormant on the next launch until explicitly started. No companion remains running; no recurring model calls are active.
- 📚 Updated the glossary and reusable Sims notes, linked the experiment from the Gaming index, and kept the experiment plan/progress separate as requested. Files are local working-copy changes, not committed or published.

Next:

1. Review the actual dialogue tone and decide how automatic text should appear without crowding normal gameplay.
2. Before another live test, preserve all original save contents again, including the shared autosave; the current verified originals are also in `.local/save-backups`.
3. Improve scene grounding only where useful (age, venue/food context, and remembered events are absent now). Test failure/pause/travel behavior before treating the experiment as a birthday release.
4. Keep other feature tracks independent. Replace plan/progress only when Max decides to begin the production build; retain the verified mechanism notes and relevant experiment evidence.

## 2026-10-20 — Conversation archive prepared

- 📚 Added the [conversation archive](../sims4-ai-birthday-mod-experiments.md) with all 14 user turns, updated the Gaming index, and retained source, result records, and the in-game screenshot. The two supplied security screenshots had identical SHA-256 hashes; retained [one copy](experiments/01-social-hook/protected-folder-access.png).
- 🧪 Verified archive metadata, turn numbering, local Markdown links, whitespace, and image signatures. The archive helper's own 19-test suite has two existing Grok-test errors on Windows (missing `time.tzset` and a failed subprocess); its Codex extraction succeeded. Recorded the follow-up in the skill's IDEAS file without modifying the archiver.
- 🗂️ Prepared a scoped archive/source/evidence commit and the requested push. Private saves, runtimes, credentials, raw game inspection artifacts, and generated archives remain ignored. Repository history is the source for the final publication commit.

Next:

1. Resume the experiment from plan.md and the verified results above; review tone and presentation before choosing production scope.
2. Address the archive helper's Windows test portability separately from Sims work.

## 2026-10-20 — Read-only save audit

- 🔎 At Max's request, inspected copies of the three original saves to look for gameplay preferences. Used our fresh Banter Lab save as a control; excluded our test household from preference findings. Kept raw saves, the whitelist summaries, and household-specific `findings.md` in ignored `.local/save-analysis/`.
- 🧪 Parsed DBPF indexes and RefPack resources using the installed save-message schema. A synthetic round trip exposed a bundled protobuf string/bytes problem before any save interpretation. A private in-process adapter fixed tag and float/double decoding; four copied saves then parsed. Recorded the reusable mechanism and interpretation limits in [how-sims-works.md](how-sims-works.md#reading-saves-offline).
- 📚 The audit supports relationship-aware dialogue and food/social settings. It does not establish a ranking of enjoyment, construction authorship, or operated restaurants. Fresh-save comparison prevented default businesses, milestone records, and rental subdivisions from being miscounted as player activity.
- 🛡️ Kept the game closed and made no model calls with save contents. All four original/control files and their analysis copies matched their before-analysis hashes afterward; private evidence is in `.local/save-analysis/verification.json`. This new work has not been committed or pushed.

Next:

1. Review the private findings with Max. Keep the agreed banter scope; consider meals/date venues as grounded scene context for the next experiment.
2. Treat the save audit as evidence about available game state, not a substitute for her own account of what she enjoys. Resolve building authorship or favorite comic moments through observation or conversation if those become important.

## 2026-10-20 — Local Sims repository audit

- 🔎 Ran `findrepo sims`: 19 local repositories. Inspected the strongest source references and recorded the useful entry points in [repo-research.md](repo-research.md). S4CL provides outcome/cancellation and venue-context examples; Lot51 provides lifecycle hooks; Control Any Sim provides a separate reference for selection and travel.
- 🧪 Ran a small read-only experiment with the existing Sims 4 Workspace readers. Parsed 20,351 tuning instances from a base XML resource and 1,021 from an actual GP03 binary DATA resource, including recipes. Retained metadata, sample IDs, and source hashes in [result.json](experiments/03-local-repo-readers/result.json). Raw game resources and the reproduction helper remain in ignored `.local/research/`.
- 📚 Corrected the earlier assumption that binary combined tuning would need a larger independent implementation: a working local decoder exists. Numerical skill thresholds and patch/pack/mod override merging are still unverified. Source inspection does not prove live compatibility of lifecycle or outcome hooks.
- 🛡️ Kept the game closed. Added no runtime dependency, installed no framework, and changed no saves or game files. The working mod remains as previously tested; these are reference findings and a package-reading proof.

Next:

1. Continue small independent experiments: compare real social outcomes/cancellations with starts, then add actual venue/meal context where available.
2. Test travel/loading cleanup before a birthday release. Use these source references as leads and verify behavior against the installed game.

## 2026-10-20 — Resumed conversation archive prepared

- 📚 Updated the existing [conversation archive](../sims4-ai-birthday-mod-experiments.md) with the save audit and local-source research, preserving all 17 user turns and refreshing the helper's frozen metadata/token snapshot. Updated the Gaming index and project entry point rather than creating a duplicate archive.
- 🧪 Reran the archive helper's 19 tests: 17 passed; the same two previously documented Grok errors remain on Windows. The archiver was not changed. Metadata, local links, evidence JSON, and the explicit publication scope are checked separately.
- 🛡️ Raw saves, household-specific private summaries, game-resource dumps, credentials, and downloaded runtimes stay ignored. This archive publishes the bounded conclusions, reusable mechanisms, source map, and package-reader result metadata.

Next:

1. Resume from the experiment plan and latest research entries; keep outcome, context, presentation, and lifecycle tests small and independently reviewable.
2. Repository history records the requested publication commit; do not treat an archive as a birthday-release milestone.

## 2026-10-20 — Engineering walkthrough, Python 3.15, and reasoning comparison

- 📚 Resumed from the plan and progress log, inspected the current source, and taught the working social-hook → external generation → notification path. Max then clarified the long-term target: replace all Simlish with contextual spoken English. Recorded that goal without treating full speech coverage as a proven birthday scope.
- 🔎 Inspected outcome selection, completion, and cancellation entry points in the installed bytecode. The proposed outcome trace was interrupted before any probe code was added or deployed. These callbacks remain untested in live gameplay.
- 🧪 Verified native Python 3.7 annotations and deferred annotations with the actual compiler runtime. Inspected the installed console parser's runtime use of annotations; recorded why command argument types should remain concrete. Found a community template that generates game API stubs; no stripping or stub-generation dependency was added.
- 🐍 Verified the existing `python3.15` command resolves Python 3.15.0. Updated companion launch instructions and ran its CLI plus six real generation requests under that interpreter. `py -3.15` failed to resolve the uv-managed interpreter, so it is not the documented command. The game's 3.7 compiler and installed archive were unchanged.
- ⏱️ Found that the earlier calls omitted reasoning settings. Added explicit `none` as the companion default and a comparison flag. A six-call alternating experiment reported default reasoning tokens 89/121/110 versus zero for all three `none` calls. Median request times were 2.476 versus 2.728 seconds respectively: no demonstrated latency gain. Preserved the reproduction script, outputs, usage, and limitations in [experiment 04](experiments/04-reasoning-latency/result.json).
- 🧑‍💻 At Max's request, read Anthropic's learning-output-style README and injected instructions. Adopt its session behavior: explain project-specific tradeoffs, handle obvious setup directly, and invite small meaningful code contributions at design decisions. Installed no hook or plugin. Controlled Folder Access was discussed but not changed.
- 🛡️ Kept the game closed, made no requests using original save data, and changed no installed game files. Model calls used only the already-public disposable Alex/Mortimer scene. The Python 3.15 full live bridge and voice replacement remain unverified.

Next:

1. Continue the learning session. Give Max a focused implementation opportunity when a meaningful dialogue-selection or stale-reply policy is chosen, with surrounding code and a clear contract prepared first.
2. Choose the next independent experiment from outcome grounding, dialogue selection, or speech playback/suppression. Full speech replacement needs coverage and timing evidence beyond the current social text hook.
3. Before a live test, preserve current save contents including the shared autosave. Re-test the full bridge under Python 3.15 and verify the modified reasoning setting in-game.

## 2026-10-20 — Requested CFA exception blocked by computer-use tool

- 🛡️ Max explicitly requested using Settings to disable Controlled Folder Access for Sims. Read-only `Get-MpPreference` confirmed CFA remains enabled (`1`); this unelevated process could not inspect allowed-app exclusions. No security setting was changed.
- 🖥️ The computer-use launch of Settings exposed no targetable window. After checking current windows and locating the installed Windows Security executable, the computer-use tool rejected its launch with `product policy blocks this app`. Stopped that action rather than working around the tool restriction.
- 🐍 Confirmed the companion's actual interpreter path is `C:\Users\Max\AppData\Roaming\uv\python\cpython-3.15-windows-x86_64-none\python.exe`. Modern annotations in companion-only Python 3.15 code are independent of the game module's Python 3.7 constraints.

Next:

1. If Max manually grants the companion access, verify a small write probe before changing bridge paths. The existing bridge continues to work without that change.
2. Continue the selected mod experiment and learning session; the CFA tool block does not prevent workspace development.

## 2026-10-20 — CFA path correction and fixed-audio research

- 🧪 After Max reported making the manual change, Python 3.15 still could not create a small probe file in `BanterLabData`. Defender event 1123 explicitly reported the blocked executable as `C:\Users\Max\AppData\Roaming\uv\python\cpython-3.15.0-windows-x86_64-none\python.exe`. The previously supplied `cpython-3.15-...` path was uv's version alias; it did not identify the resolved path shown by Defender. CFA remains enabled. Kept the existing workspace reply location and bridge configuration; no protected probe file was created.
- 🔎 Inspected installed audio bytecode and found per-target `PlaySound` start/stop operations, an `is_vox` parameter, and `PROPX` audio resource references. Checked an EA developer's voice-resource explanation and the TS4 Sound Tool creator's replacement workflow. Recorded mechanisms and limits in [how-sims-works.md](how-sims-works.md#audio-entry-points-for-a-fixed-speech-experiment).
- 🎙️ Proposed the next independent proof: one fixed English greeting replacing one known Simlish cue. No audio playback, selective suppression, package override, or external audio-tool compatibility has been tested. The game remained closed; no audio tool or game-file change was installed.

Next:

1. Identify one current greeting cue/resource and test fixed English playback, then replacement or selective suppression in Banter Lab. Back up saves including the shared autosave before launching.
2. Keep generated speech and broader cue coverage downstream of the fixed-audio mechanism proof. Prepare a focused user coding contribution when an actual selection or timing policy is needed.
3. If Max allows the resolved Python executable through CFA, repeat the small write probe before simplifying bridge paths. This does not block the audio investigation.

## 2026-10-20 — Python 3.15 protected-folder access verified

- ✅ After Max added the Python entries and requested a retry, the resolved Python 3.15.0 executable successfully created a uniquely named file in `Mods/BanterLab/BanterLabData`, atomically replaced it, read its UTF-8 JSON contents, and deleted it. The probe left no files behind. This establishes the needed companion write access in that directory.
- 📚 The separate workspace reply location is no longer required by this tested filesystem restriction. The current bridge configuration has not been changed; simplifying it is a separate small change.

Next:

1. Continue the fixed-audio experiment. When updating the bridge, it is now possible to place replies beside events and verify the simpler path in-game.

## 2026-10-20 — Fixed greeting asset packaged; live comparison started

- 🎙️ Prepared our own English `Oh. Hello.` WAV with Windows SAPI/Zira and MP3 with ffmpeg. Resolved 48 base-game greeting/voice configurations using FNV-1 64-bit hashes. The chosen Female Voice 1 uncomfortable-greeting configuration also appears in `ClientDeltaBuild1.package`; the sound editor showed its patched six-sample list.
- 🛠️ At Max's explicit approval, launched TS4 Sound Tool 1.1.29. Its missing codec required a separate download; the original Bitbucket download is unavailable. The creator-linked patched 0.7.0 codec initially failed with missing `libmpg123.dll` (`0xC0000135`). A complete open-source codec release supplied the dependency. A 22.05 kHz import failed; a 44.1 kHz stereo MP3 with patched 0.7.0 imported successfully. Codec and input format changed together, so their individual effects were not isolated.
- 🧪 Saved a private greeting package and used the existing s4pi API to retain exactly two resources: configuration `FD04E3BE!00000000!AE9960DCFFD5C32E` and our sample `01A527DB!001407EC!2A95B32D1417C761`. Independent package reading passed. The packaged sample decoded back to a 44.1 kHz stereo MP3, duration 2.429 seconds; this proves conversion and package structure, not in-game playback.
- ⌨️ Added manual `banter.audio hello`, `control`, and `stop` commands. They request a fixed audio resource through `PlaySound`; they do not generate speech or choose a social. The request log deliberately does not claim audible playback.
- 🛡️ With the game closed, copied and SHA-256 verified all 38 current save/version files to ignored `.local/save-backups/audio-20261020-230352`. Preserved the prior script archive there. Installed the test script (`CCAA7C48133FA360AD3DFFA970ECFD1537D3743DD83C4CFA21BA79C36C752E1F`) and two-resource package (`C4F8C929DD05E87457FAD52674CF49F9D7E72612D24993610AFC23E199AB6E36`). Relaunched the game; its new dormant `loaded` log confirms script import.

Next:

1. Load only Banter Lab, request the untouched control cue and overridden English cue, and distinguish the sound request from a human-confirmed audible result.
2. Close without saving later test state, restore/check original save contents and shared autosave against this snapshot, and remove the temporary always-active audio package after testing.
3. Keep realtime generation/loading and interruption behavior as separate experiments. A static package does not establish runtime loading of freshly generated speech.

## 2026-10-21 — Overnight experiments 05–09 verified on secondary monitor (muted)

- 🖥️ Positioned The Sims 4 on the secondary 1440p monitor (`DISPLAY1`, `(3920, 399)`) and verified that a second `SetWindowPos` after crossing the `150% -> 100%` DPI boundary restores the exact `1280×720` DirectX client rect. Left system volume muted throughout so Max could sleep undisturbed.
- 🎙️ **Experiment 05 (Fixed speech package):** Loaded `Banter Lab` and ran `banter.audio control` (`0x04A64CD44542ACEC`) and `banter.audio hello` (`0xAE9960DCFFD5C32E`). While hardware speakers stayed muted, verified digital rendering from `TS4_x64.exe` via `IAudioMeterInformation` session peaks and pre-endpoint-mute WASAPI loopback capture (`r = 0.9790` 25 ms envelope correlation, `r = 0.9726` 10 ms envelope correlation, and `|r| = 0.6462` 16 kHz sample-level correlation across 38,034 samples vs. `r = 0.4673` for control). Removed the temporary `BanterLabGreeting.package` from `Mods/BanterLab` afterward. See [result.json](experiments/05-fixed-speech/result.json) and [console screenshot](experiments/05-fixed-speech/in-game-console.png).
- 🎯 **Experiment 06 (Social outcomes, cancellations, and passive containers):** Wrapped `store_result_for_outcome`, `_trigger_interaction_complete_test_event`, and `cancel` alongside `_trigger_interaction_start_event`. Discovered that `sim_Chat` (`13998`) and `sim_BeAffectionate` (`13991`, STBL display name `"Chat"`) are passive `SocialSuperInteraction` conversation containers rather than affectionate mixers, explaining the earlier false-positive romantic prompt at `romance = 0`. Live `banter.trace` measurements showed `store_result_for_outcome` fires **30–37 ms** after `start` and **4.4 seconds before** animation completion, allowing `banter.ai` (now defaulting to `outcome`) to include the verified `OutcomeResult` (`SUCCESS` / `FAILURE`) while still displaying dialogue mid-animation. See [result.json](experiments/06-social-outcomes/result.json) and [in-game screenshot](experiments/06-social-outcomes/in-game-outcome-banter.png).
- 📚 **Experiment 07 (Rich scene context, 176k-string STBL resolver, and simplified bridge):** Added a pure-stdlib DBPF v2.0 + RefPack + ZLIB + STBL v5 reader to `companion.py` that loads all 165,095 official English strings from 141 `Strings_ENG_US.package` files plus 11,171 strings from `Mods/*.package` (cached in `.local/stbl_en_us.json`, 0.36 s load). Verified live resolution of interaction labels (`"Respectful Introduction"`, `"Discuss Local Fishing Spots"`, `"Discuss Logic Puzzles"`), traits, active visible moodlets and their reasons (`"Emotionally Mindful"`, `"Feeling Great"`), venue (`"Residential"`), relationship bits (`"Neighbor"`, `"Good Compatibility"`, `"Acquaintances"`), Sim `age`/`gender`/`voice_actor`/`voice_pitch`, bounded per-zone `recent_dialogue` continuity, and direct reply delivery via `BanterLabData/reply.json` without `bridge.json`. See [result.json](experiments/07-rich-scene-context/result.json).
- 💬 **Experiment 08 (Dual-portrait auto-expanded speech UI):** Configured `UiDialogNotification` with `expand_behavior = FORCE_EXPAND`, `visual_type = SPEECH`, `information_level = SIM`, `icon_override = IconInfoData(obj_instance=actor_info)`, and `secondary_icon_override = IconInfoData(obj_instance=target_info)`. Verified live in-game that banter cards automatically expand in the top-right corner showing both Sims' portraits and the full dialogue without opening the Notification Wall. See [result.json](experiments/08-notification-presentation/result.json) and [popup screenshot](experiments/08-notification-presentation/dual-portrait-speech-popup.png).
- 🔊 **Experiment 09 (Companion per-Sim spoken banter synthesis):** Added `--tts-dir` and `--speak` to `companion.py`, mapping each Sim's `gender`, `voice_actor`, and `voice_pitch` to distinct voices (`Microsoft Zira` for female Sims; `Microsoft David` and `Microsoft Mark` alternated by `voice_actor` for male Sims) and rendering two-speaker SSML WAV clips in **0.60–0.82 seconds** during the live Banter Lab conversation. See [result.json](experiments/09-spoken-banter/result.json).
- 🛡️ Closed the game without saving, deployed the refined `BanterLab.ts4script` (`3A743B2C5B5FFB578C889EE93017A0E63E8BFB861CA82DD6D90BEEDC2B3282D5`), and restored/verified all **38 save files** (including the shared autosave) against the pre-test SHA-256 manifest (`audio-20261020-230352`).

Next:

1. When Max is awake with audio unmuted, optionally run `companion.py --data-directory ... --speak` (with in-game `voiceslevel = 0` if suppressing Simlish) or drop `dist/BanterLabGreeting.package` into `Mods/BanterLab` to judge the spoken audio by ear.
2. Review the verified capabilities (outcome-aware banter, STBL-resolved context + moodlets + venue + relationship bits, scene continuity, dual-portrait auto-expanding speech UI, and companion TTS) and select the production birthday mod scope so we can replace the experiment `plan.md` and `progress.md` with the production build plan.

## 2026-10-21 — Experiments 10–12 verified: runtime Simlish mute, in-game player chat modal, activity/object context, and 33 ms warm TTS

- 🔇 **Experiment 10 (Dynamic per-Sim Simlish suppression in Python):** Decoded `sim_info.voice_actor` as the 32-bit FNV-1 hash of the 2–3 character voice suffix (`'ma'` -> `1685527063`, `'mb'` -> `1685527060`, `'fa'` -> `1802970394`, `'fd'` -> `1802970399`, `'cb'` -> `1853303382`). Found that assigning `0` triggers a C++ fallback to `'fa'` (`1802970394`), whereas assigning `0x7FFFFFFF` (`2147483647`) and distributing `SetVoiceActor` stores verbatim and silences `is_vox=True` cues. In a TV-free room (`objects.destroy` on the test TV), `banter.audio vox` (`vo_expr_greet_angry_25f`, `is_vox=True`) dropped from a **`0.0415`** `TS4_x64.exe` session peak unmuted down to the **`0.0040`** ambient floor under `banter.mute on`, while preserving `1685527063` in `_sim_snapshot` and restoring on `banter.mute off` / `banter.stop`. See [result.json](experiments/10-simlish-suppression/result.json) and [console screenshot](experiments/10-simlish-suppression/in-game-vox-mute-console.png).
- 🗣️ **Experiment 11 (Direct player-to-Sim conversation + 33 ms warm TTS):** Added `banter.say <message>` and `banter.talk` (subclassing `UiDialogTextInputOkCancel` to open a native in-game text-input modal with the active Sim's portrait). Tested live with Geoffrey Landgraab (`banter.say`) and Rieko Okada (`banter.talk` modal: typed `"Is my living room minimalist or just empty?"`, clicked OK, and verified Rieko's in-character reply `"Empty. But in a fancy way, because you have a loveseat."` in the dual-portrait speech popup). Replaced per-call PowerShell TTS spawning with a warmed-up persistent worker in `companion.py`, reducing two-speaker WAV synthesis time from `0.60–0.82 s` to **`0.033–0.135 s` (33–135 ms)**. See [result.json](experiments/11-player-conversation/result.json), [modal screenshot](experiments/11-player-conversation/in-game-talk-modal.png), [reply screenshot](experiments/11-player-conversation/in-game-talk-reply.png), and [`banter.say` screenshot](experiments/11-player-conversation/in-game-player-say.png).
- 🛋️ **Experiment 12 (Multitasking activity, carried object, and recipe STBL context):** Added `_sim_activities(sim)` inspecting `sim.si_state`, `sim.posture_state.carry_targets`, `target.catalog_name`, and `crafting_component.get_recipe().get_recipe_name()`. Verified live resolution of `"Watch World Culture Network"` on `"Been There, Watched That TV"`, `"Watch Sports"`, and `"Sit"` on `"Squarely There Modern Loveseat"`, which Rieko Okada referenced directly in her reply. See [result.json](experiments/12-activity-and-food-context/result.json).
- 🛡️ Closed the game without saving, deployed the updated `BanterLab.ts4script` (`4C7EE1E42BBF6D8D8E8D6292C26B635E9B36715C3ED696083FB8BB93C110164B`), and restored/verified all **38 save files** against the pre-test SHA-256 manifest (`audio-20261020-230352`).

Next:

1. When Max is awake with speakers unmuted, test `companion.py --data-directory ... --speak` alongside `banter.ai` + `banter.mute on` and `banter.talk` to evaluate the spoken English banter and in-game Simlish suppression by ear.
2. Decide which verified capabilities (automatic outcome-aware banter, STBL-resolved scene/moodlet/activity/food/venue context, dual-portrait auto-expanding speech UI, `banter.talk` player conversation modal, `banter.mute` runtime Simlish suppression, and 33 ms companion TTS) belong in the production October 29 birthday mod, then replace the experiment `plan.md` and `progress.md` with the production build plan.

## 2026-10-21 — Experiment 13 verified: zero-`.package` Page-1 Sim Pie-Menu controls on lot load

- 🥧 **Experiment 13 (Zero-`.package` Sim Pie-Menu injection):** Subclassed `services.affordance_manager().get(13142)` (`ImmediateSuperInteraction`) at runtime in Python 3.7 with `cheat = False`, `debug = False`, `allow_user_directed = True`, `category = None`, `pie_menu_priority = 30`, `@flexmethod def test(...) -> TestResult.TRUE`, and `@flexmethod def _get_name(...)`. Hooked `Zone.on_loading_screen_animation_finished` so the interaction attaches to `object_sim._super_affordances` automatically when a lot loads.
- ✅ Verified live in `Banter Lab` with zero console commands entered: clicking Alex Keen displayed **`Enable English Banter`** on Page 1 of his radial Pie Menu; clicking it toggled `_enabled = True`, and clicking Alex Keen again displayed **`Disable English Banter`**. Fixed the `_connection is not None` guard in `start_ai` and `stop` so Pie-Menu execution completes cleanly without a console connection. See [result.json](experiments/13-pie-menu-interaction/result.json), [Enable screenshot](experiments/13-pie-menu-interaction/in-game-pie-menu-self.png), and [Disable screenshot](experiments/13-pie-menu-interaction/in-game-pie-menu-disable.png).
- 🛡️ Closed the game without saving, deployed `BanterLab.ts4script` (`5386228270B92AEC8713FC375D7C391CAA018BDBB82088090D167258DB0E4A21`), and restored/verified all **38 save files** against the pre-test SHA-256 manifest (`audio-20261020-230352`).

Next:

1. When Max is awake with speakers unmuted, launch the game with `companion.py --data-directory ... --speak` running and test the zero-console workflow: click your active Sim -> **Enable English Banter**, watch a social interaction, and click another Sim -> **Speak to <Sim> (English)...**.
2. Choose the final feature set for the October 29 birthday release and transition from the experiment `plan.md` / `progress.md` to the production build plan.
