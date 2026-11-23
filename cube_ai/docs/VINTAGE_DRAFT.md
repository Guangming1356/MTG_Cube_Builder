# Vintage draft behavior / Vintage 轮抽行为

The official 540-card reference uses an offline pick-priority prior from the
[CubeCobra public card export](https://cubecobra-public.s3.amazonaws.com/export/simpleCardDict.json)
(source updated 2026-11-11, retrieved 2026-11-24). It covers 522 cards after
resolving double-faced card names. These are site-wide Cube draft-pick Elo
values, not Vintage-specific game results. Cards without a value keep the
project's existing heuristic. The bounded blend applies only to classic drafts
with Vintage legality; Commander and other formats retain their old scoring.

Traditional decks use casting-color requirements rather than Commander color
identity. Hybrid and life-payment choices are considered. The readiness model
still estimates individual mana payments and does not simulate game effects.
Simple sacrifice-to-fetch-a-basic lands count as fixing. Classic decks may
include up to two unrestricted colorless utility lands while reserving the
remaining land slots for colored sources and basics. This is a heuristic; the
model does not simulate restricted mana, enters-tapped timing, depletion of
fetch targets, or the value of an unpayable off-color activated ability.

For a reproducible local diagnostic, 20 fixed-seed eight-player reference
drafts (160 decks) were compared with the previous published draft code. The
old/new runs both built 160 decks. Of opened cards, Black Lotus appeared in
2/14 versus 14/14 decks and Ancestral Recall in 0/13 versus 13/13. These are
small structural observations of one scripted drafter, not human pick rates,
game outcomes, or proof of a stronger deck. The prior and color/land changes were
applied together, so these results do not isolate either change's effect.

默认英文；轮抽报告会说明评级覆盖数量和局限。上述对照只是自动组牌的
结构观察，不是 Forge 对局，也不能证明胜率或娱乐性。
