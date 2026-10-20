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
