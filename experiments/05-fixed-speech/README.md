# Fixed English speech experiment

Goal: replace one known Simlish greeting with a fixed English clip before adding generation or speech-synthesis latency. This is an independent mechanism test, not a commitment to package every generated line as a static asset.

## Current evidence

The installed base animation package contains readable greeting cue names. FNV-1 64-bit hashing of cue names with voice suffixes resolves audio configurations in `Data/Client/ClientFullBuild1.package`. Counts, resource keys, hashes, and limits are in [result.json](result.json). Run `python3.15 lab.py exp05 resources` from `gaming/sims-ai` to reproduce the configuration lookup using the existing local Sims 4 Workspace reader. Raw game resources remain private.

Prepared our own [English WAV](audio/fixed-hello.wav) and [MP3](audio/fixed-hello.mp3), saying **Oh. Hello.**, with the installed Microsoft Zira voice through Windows SAPI, followed by MP3 conversion with the installed ffmpeg. This is a fixed test asset, not the proposed final TTS voice or service.

## Tool roles

- **Text-to-speech (TTS):** converts text into audible speech. Windows SAPI produced this test clip; a future live TTS system remains a separate experiment.
- **TS4 Sound Tool:** the [creator's utility](https://modthesims.info/d/639090/ts4-sound-tool.html) imports audio into Sims sound resources and creates packages. It does not generate speech from text. Release 1.1.29 is downloaded into ignored `.local/tools`, with archive identity retained in the result. It has not been launched; its UI confirmation is pending clarification.
- **Our eventual runtime:** must connect game state to timely English playback, suppress the matching Simlish, and handle interruption and overlap. Neither the fixed clip nor the utility establishes that runtime path.

## Next proof

Use one current cue and voice variant to build a reversible test package. Verify the effective resource against patch overrides, then test playback and replacement in Banter Lab with original save contents backed up. Compare targeted speech with other voices, music, and effects. Do not claim replacement from an added overlapping sound alone.
