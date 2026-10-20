# Local Sims source references

Inspected October 20, 2026 after Max asked about `findrepo sims`. The command returned 19 repositories under `C:\Users\Max\code\github.com\sims`. This is a source map for small experiments, not a decision to install frameworks or replace our working prototype.

## Most useful now

| Reference | What the inspected source teaches | Useful experiment |
| --- | --- | --- |
| [Sims4CommunityLibrary](https://github.com/DeviantGameMods/Sims4CommunityLibrary) | The interaction dispatcher wraps start, outcome, and cancellation separately. Location helpers expose actual venue tuning/type; age and species helpers provide participant context. | Observe outcome/cancellation alongside our start hook. Compare accepted/rejected socials before deciding which evidence should drive the reply. Capture venue type without inferring it from the lot's name. |
| [Lot51 Core Library](https://github.com/lot51/core-library) | Event hooks cover loading screens, zones, objects, game ticks, and Build/Buy. Its balloon example distributes icons, not arbitrary English text. | Test travel cleanup and cancel stale replies. Investigate presentation separately; the icon-balloon example does not establish that text subtitles can be placed above Sims. |
| [Sims 4 Workspace](https://github.com/ssinakhot/sims4-workspace) | Read-only package readers, RefPack decoding, combined-tuning parsing, and a binary DATA-to-XML decoder are already implemented. | Resolve interaction/recipe/skill IDs from this installation; investigate tuned fields without writing a binary decoder ourselves. Two actual packages were successfully read below. |
| [Sims 4 Toolkit models](https://github.com/sims4toolkit/models) and [extraction](https://github.com/sims4toolkit/extraction) | Package/resource models, string-table resources, and a TypeScript binary combined-tuning decoder provide an independent format reference. | Resolve readable game labels from string tables and compare format interpretations when needed. No Node packages were installed or executed for this audit. |

Concrete local entry points:

- [Interaction outcome/cancellation hooks](C:/Users/Max/code/github.com/sims/Sims4CommunityLibrary/Scripts/sims4communitylib/events/interaction/common_interaction_event_dispatcher.py:364): wraps `Interaction.store_result_for_outcome`; cancellation hook begins at line 398. Inspect the installed game's signature and actual result values before using this callback.
- [Venue context](C:/Users/Max/code/github.com/sims/Sims4CommunityLibrary/Scripts/sims4communitylib/utils/location/common_location_utils.py:715): `get_venue_type_by_zone_id` calls `build_buy.get_current_venue(zone_id)`; the venue service is separately available through the zone.
- [Display-name handling](C:/Users/Max/code/github.com/sims/Sims4CommunityLibrary/Scripts/sims4communitylib/utils/resources/common_interaction_utils.py:316): returns a `LocalizedString` from `interaction.display_name._string_id`, not an English Python string. This corroborates our existing localization boundary.
- [Lot51 event names and dispatcher](C:/Users/Max/code/github.com/sims/core-library/services/events.py), [zone hooks](C:/Users/Max/code/github.com/sims/core-library/events/zone.py), and [balloon example](C:/Users/Max/code/github.com/sims/core-library/loot/balloons.py).
- [Python binary tuning decoder](C:/Users/Max/code/github.com/sims/sims4-workspace/util/datamining/binary_tuning.py:422), [combined-tuning reference resolver](C:/Users/Max/code/github.com/sims/sims4-workspace/util/datamining/combined_tuning.py:205), and [package reader](C:/Users/Max/code/github.com/sims/sims4-workspace/util/datamining/package_reader.py:155).
- [Independent TypeScript decoder](C:/Users/Max/code/github.com/sims/models/src/lib/resources/combined-tuning/serialization/binary-to-xml.ts) and [string-table model](C:/Users/Max/code/github.com/sims/models/src/lib/resources/stbl/stbl-resource.ts).

## Read-only proof

Imported the local workspace's reader modules under Python 3.13 and read installed packages without launching the game or changing game files:

1. `Data/Simulation/SimulationFullBuild0.package`: decoded the XML combined-tuning resource into **20,351 tuning instances** and 29,541 shared references. Exact ID lookups resolved Homestyle Cooking (`16705`), Gourmet Cooking (`16701`), friendship (`16650`), romance (`16651`), and the Culinary career (`9231`). Cooking's tuned skill-level type is `MAJOR`; numerical level thresholds were not extracted.
2. `GP03/SimulationFullBuild0.package`: decoded a real **binary DATA** combined-tuning resource into XML, then parsed **1,021 tuning instances** and 2,786 shared references. Samples include the Cubed Supreme, Vertical Berry Cake, and Eggs Benedict recipe definitions.

Counts, representative IDs, timings, and reader-source SHA-256 hashes are retained in [result.json](experiments/03-local-repo-readers/result.json). The private reproduction helper is `.local/research/probe_local_tuning_reader.py`; raw game tuning stays private. These samples establish that the readers work on these resources. They do not establish complete format coverage, correct load-order merging across patch/pack/mod overrides, or the behavior of any recipe or social in a running game.

This corrects the earlier assessment that binary combined tuning would require a larger independent format implementation: a working decoder was already present in the local checkout. No further binary-format work is needed for this tested path.

## Useful later

[Control Any Sim](https://github.com/TitanNano/TS4ControlAnySim) has concrete source for selection, travel, and Sim lifecycle behavior. Its [game event bus](C:/Users/Max/code/github.com/sims/TS4ControlAnySim/src/control_any_sim/util/game_events.py) is a useful comparison for zone teardown and active-Sim changes. NPC selection/control remains an independent future feature, not a prerequisite for dialogue.

The scripting templates and decompilers may shorten a specific future investigation; we already have a working build/import path and can inspect installed bytecode. SimRipper concerns character appearance extraction. The mod manager and unrelated gameplay-mod source have lower immediate value than the references above. Not all 19 repositories received a deep audit.

## Applying the findings

Keep our small working mod. Study the implementations, verify a needed method against the installed game, then test that one behavior in the separate save. Adding S4CL or Lot51 as a dependency is a separate choice with installation and update costs; source inspection alone does not justify it.

The highest-value next experiments are outcome-aware replies, actual venue/meal context, and reliable cleanup when traveling or leaving live gameplay. Keep UI, audio, direct player chat, and world actions independent, as already agreed. The repositories provide leads and reference implementations; our live experiments establish what works here.
