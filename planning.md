# The Sims 4 birthday mod

Planning interview started October 20, 2026. Birthday target: October 29, 2026.

The current experiment plan is [plan.md](plan.md), the append-only handoff is [progress.md](progress.md), and reusable mechanisms are recorded in [how-sims-works.md](how-sims-works.md). This file retains the interview and prior-art research.

## Confirmed brief

- The gift is for Max's girlfriend, who has over 1,000 hours in The Sims 4.
- Her interests, in order: relationships and drama; building dream homes and restaurants; food. She is a great chef and often laughs while playing.
- Max is an experienced software engineer, new to Sims modding and large game reverse-engineering projects.
- Max is willing to invest substantial time, but wants to start small.
- Explore features independently, beginning with the smallest experiments.
- Have the design conversation before selecting and running implementation experiments.
- First feature selected: watch Sims interact with funny English dialogue, rather than starting with direct player conversation or AI-controlled actions.
- Match The Sims' energy: recognizable personalities and relationships, with playful and occasionally absurd situations. Do not assume constant jokes or impose a restaurant theme on every interaction.
- Develop and test on this PC. Prefer to keep the gift a surprise; discovery is acceptable rather than a hard constraint.

## First feature: contextual dialogue

The game supplies the social interaction. Generated banter should reflect the actual participants, interaction, personalities, moods, and relationship as far as those can be observed. Food and restaurant context is useful when it is actually present, not invented for every scene.

Max confirmed the smallest integration experiment: identify one real social interaction and show one fixed English test line in a game notification. Then use captured context to generate short banter. Text-first is an acceptable milestone; speech is a separate experiment.

Direct player conversation, narration, English speech, and model-selected game actions remain independent feature tracks. Their architecture is not a prerequisite for proving this first integration.

## Feature candidates, not selected scope

| Candidate | Experience to explore | Independent uncertainty |
| --- | --- | --- |
| Contextual dialogue | English lines for interactions between Sims, informed by game state | Can we identify the interaction, participants, and relevant context reliably? |
| English audio | Hear generated lines instead of, or alongside, Simlish | Playback, suppression of existing speech, timing, and interruption need separate investigation. |
| Conversation | Address a particular Sim and receive an in-character reply | Whether the player speaks as herself, through her own Sim, or as a director is unresolved. |
| Narration | Describe events and respond to the player's commentary | Narrating events and changing events are different capabilities. |
| World actions | Translate an intention into actions within the game | Requested, queued, and completed actions must be distinguished. |

Food and restaurant drama are promising creative settings, not confirmed requirements. Other possible small experiences include a Sim's diary of the day's drama or remembered gossip between Sims.

## Research checked October 20, 2026

### Decision APIs

- [TypeSafe AI](https://typesafe.ai/) links to its official Jev documentation at `docs.typesafe.ai`. Similarly named Jev sites are not necessarily the vendor.
- [Jev introduction](https://docs.typesafe.ai/introduction), [API reference](https://docs.typesafe.ai/api/system-one), and [function-calling cookbook](https://docs.typesafe.ai/cookbooks/function_calling): Jev evaluates supplied state and answers typed questions, including fixed choices, scores, and yes/no probabilities. It does not generate dialogue. The documented endpoint is `POST https://api.typesafe.ai/v1/systemone`.
- [OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions): public beta using `gpt-6-luna`, with predicate, choice, and score questions at `POST /v1/decisions`. The guide distinguishes these results from generated text and function calling. Documentation availability does not establish access for a particular account.
- Possible independent experiment: choose a social intention from game-validated options, then separately generate a suitable line and, if in scope, request a game action. This is a candidate, not a selected architecture or a requirement for initial dialogue.

### Sims integration

- [Sims4CommunityLibrary interaction dispatcher](https://github.com/DeviantGameMods/Sims4CommunityLibrary/blob/main/Scripts/sims4communitylib/events/interaction/common_interaction_event_dispatcher.py) contains hooks for interaction start and outcome events. [Text input dialogs](https://github.com/DeviantGameMods/Sims4CommunityLibrary/blob/main/Scripts/sims4communitylib/dialogs/common_input_text_dialog.py) and [interaction utilities](https://github.com/DeviantGameMods/Sims4CommunityLibrary/blob/main/Scripts/sims4communitylib/utils/sims/common_sim_interaction_utils.py) provide additional source examples. Compatibility with the eventual test installation has not been checked.
- [dnavaria/sims4ai](https://github.com/dnavaria/sims4ai) has source for a script mod, state snapshots, a separate model process, and in-game notification replies. Source inspected; game behavior untested.
- Its [action executor](https://github.com/dnavaria/sims4ai/blob/master/sims4_ai_mod/ai_sim_mod/tool_executor.py) can fall back to descriptive notifications and `proposed_only` instead of executing an action. Its network worker also calls game/UI code. Treat it as research material, not verified gameplay functionality.
- [Simcronia](https://github.com/CarlosNahuelcoy/Simcronia) describes generated dialogue for social interactions and has source. Its repository claims additional provider-related license terms; inspect the actual license before considering reuse. Gameplay untested.
- [AI Autonomy Mod](https://github.com/esther-huang/AI_Autonomy_Mod) describes conversation and game actions, but the inspected repository does not publish implementation source. Claims unverified.
- [Llamafone AI](https://www.curseforge.com/sims4/mods/llamafone), a creator-maintained listing, describes contextual calls, texts, group texts, dating, and small changes to friendship and romance tracks. This suggests an alternative gift experience: an in-game message from a Sim after a dramatic meal or date. Source and gameplay not audited; the listing's wording about a character's "voice" alone does not establish spoken audio.
- [Empneon](https://github.com/mf-rl/Empneon) publishes a game-independent character runtime with a Sims adapter. Its README labels Core beta and the Sims adapter alpha, tested on a single hardware profile. Research reference only; do not adopt the whole runtime before establishing a need for its components.
- Sims AI Chat's [creator page](https://xpload32004.itch.io/sims-ai-chat) and [project site](https://sims4ai.duckdns.org/) describe generated text for clicked/autonomous social interactions and AI voice for directed chats. Implementation source has not been located; gameplay claims untested. The previously indexed [Nexus listing](https://www.nexusmods.com/thesims4/mods/6291?tab=description) currently says "Removed by staff," without a stated reason. Do not treat search snippets as proof of the current page contents or recommend that download.
- The [Mute Trait creator](https://www.curseforge.com/sims4/mods/mute-trait) documents per-Sim silencing using the Flower Bunny voice trait, requiring Seasons and XML Injector. This is a narrow suppression reference, not a selected dependency or a general runtime speech-replacement solution.
- [TS4 Sound Tool](https://modthesims.info/d/639090/) documents offline voice/sound resource creation and MP3-to-game-audio import. This does not establish runtime injection of arbitrary generated audio.
- `findrepo rea` located `C:\Users\Max\code\github.com\morluto\rea`. Its README describes a general reverse-engineering toolkit. Inference: defer it until a specific boundary cannot be reached through existing script-mod mechanisms.
- Verify the actual game build and embedded Python version before selecting build tooling; published modding examples are not proof of the installed runtime.

### This PC, inspected October 20, 2026

- Install path from the Windows registry: `C:\Program Files\EA Games\The Sims 4\`.
- Both game executables have file/product version `1.128.90.1030`, matching the last-run user config log.
- Embedded interpreter: `Game\Bin\python37_x64.dll`, file/product version `3.7.0`.
- Game scripts are in `Data\Simulation\Gameplay\base.zip`, `core.zip`, `simulation.zip`, and `Game\Bin\Python\generated.zip`.
- User data: `C:\Users\Max\OneDrive\Documents\Electronic Arts\The Sims 4`. Options currently have `scriptmodsenabled = 1` and `modsdisabled = 0`.
- Top-level Mods entries include `Basemental Drugs`, `Vortex Mods`, and `Resource.cfg`. Their versions and compatibility have not been audited.
- Installed pack directories: `EP01,03,04,05,07,08,09,10,11,12,13,15,16`; `GP03,05,06,10,11`; `SP08,10,13,14,16,35`; `FP01`. Presence alone does not establish entitlement or successful loading.
- Inspection of archive entries and byte strings confirms the candidate identifiers `_trigger_interaction_start_event`, `store_result_for_outcome`, and `is_social` are present in this build. This is not a test of callback signatures or behavior.
- No game launch, mod installation, or game-setting changes have been performed during the interview.

## Open interview decisions

- Model access and budget become relevant once the event/context integration works. No provider has been selected.
- Later feature branches include player speaker identity, narration controls, game-state consequences, English speech, and installation experience.

The first experiment's requirements are settled. The [experiment plan](plan.md) scopes the implementation and leaves other features independent. Record terminology in the glossary once its meaning is settled; create architecture decision records only for substantial decisions with real tradeoffs.

## Research workflow

Max explicitly reinforced searching the web early for unfamiliar terms and as a rough pass over new ideas. Look up product names before asking him to explain them; inspect primary pages after search, and distinguish current page contents, creator claims, inspected source, and observed gameplay.
