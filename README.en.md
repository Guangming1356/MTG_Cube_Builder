# MTG Cube Builder

[中文说明](README.md) · English

MTG Cube Builder is a local workspace for designing, checking, drafting and refining Magic: The Gathering Cubes. The Windows portable release includes the card snapshot and Forge; no API key is needed for local construction and simulation.

## Getting started

1. Download the Windows x64 portable ZIP from the [releases page](https://github.com/Guangming1356/MTG_Cube_Builder/releases).
2. Extract the entire archive and double-click **启动Cube助手.exe**. The application opens at a local address in your browser.
3. Choose Commander, a conventional Cube, or the MTGO Vintage Cube reference. The Vintage reference deliberately includes powerful cards such as Black Lotus.
4. Configure the draft rules, run draft checks, and inspect the resulting decks. Forge multiplayer game simulation currently supports three-player Commander.

The Vintage reference is the [MTGO October 7, 2026 card list](https://www.mtgo.com/vintage-cube-cardlist), not a new official list. Card data is a dated snapshot and needs updating as new sets or rules appear.

## Evaluation and learning

Drafted decks receive local structural and mana-readiness diagnostics. A conservative adapter includes the targeted-removal metric from [mtg-draft](https://github.com/albertngo1/mtg-draft), MIT licensed, at commit `ac9bc2a8e73ffe0442726d29e087cfcd4a39c4a8`. The adapter scores only recognized removal; other interaction is reported as unclassified. Its values are judgments, not win probabilities. The observed-game learning pipeline uses these features and real Forge outcomes, with held-out validation before a model can be adopted.

## Data and updates

Your decklists, settings, logs and learned models remain local. Download the portable release rather than sharing a used installation folder. Before upgrading, back up your data and extract a new release to a separate directory.

Select **English** in the header to switch the interface and report downloads without an internet connection. The catalog combines reviewed translations and offline machine-assisted translations. User-authored text, card names and original Oracle text retain their source language. AI advice requests ask the connected provider to answer in the selected language. Source code and issue discussions are welcome in either Chinese or English.

Draft settings include the number of players and packs, cards per pack, picks per turn, and either passing each pack once or drafting all cards. Random collation is available; seeded packs apply only to the single-pass mode. Automatic drafters currently favor two-color decks and do not model every Vintage combo or player decision.

The current game-outcome learner runs after Forge optimization rather than after every standalone draft. Vintage drafts are evaluated structurally but cannot yet be played through this project's Forge integration or used to train a Vintage game-outcome model.
