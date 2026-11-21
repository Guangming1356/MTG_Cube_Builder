"""Vendored removal evaluation from mtg-draft / mtgcommander.metrics.

Copyright (c) 2026 albertngo1; MIT license, see data/mtg_draft_LICENSE.txt.
Source: https://github.com/albertngo1/mtg-draft
Commit: ac9bc2a8e73ffe0442726d29e087cfcd4a39c4a8
Only the pure removal evaluation functions and their constants are included.
"""

SPEED_WEIGHTS = {"instant": 1.0, "repeatable ability": 1.0, "sorcery speed": 0.75}
# reach: what it can hit. "Conditional" is removal with a limit on its target (toughness, "nonblack", damage).
REACH_WEIGHTS = {"any permanent": 1.0, "creatures and planeswalkers": 0.8, "creatures only": 0.7,
                 "one kind of permanent": 0.6, "conditional": 0.6}
CONDITIONAL_TAGS = {"removal-toughness", "doom-blade", "removal-burn"}
# permanence: how well the target stays gone
PERMANENCE_WEIGHTS = {"exile": 1.0, "destroy": 0.9, "damage or -X/-X": 0.8, "bounce": 0.5}
# cost: (the highest mana value, weight); a dearer card is worth COST_DEAR
COST_WEIGHTS = ((2, 1.0), (3, 0.9), (4, 0.8))
COST_DEAR = 0.65
REPEATABLE_WEIGHT = 1.5      # removal that works again and again
ONE_SIDED_WEIGHT = 1.5       # a board wipe that spares your own side (wipe power only)


def _is_instant_speed(rec):
    return "Instant" in rec["types"] or "flash" in {k.lower() for k in rec["keywords"]}


def removal_kind(rec, attrs):
    """The words for each factor of a removal card's quality: {"speed", "reach", "permanence", "cost" ("MV 2"),
    "repeatable" (bool)}. `attrs` is the card's set of roles.ATTRIBUTE_TAGS slugs."""
    attrs = frozenset(attrs)
    repeatable = "repeatable-removal" in attrs
    if _is_instant_speed(rec):
        speed = "instant"
    elif repeatable and "Planeswalker" not in rec["types"]:
        speed = "repeatable ability"
    else:
        speed = "sorcery speed"
    if "removal-permanent" in attrs or "removal-nonland" in attrs:
        reach = "any permanent"
    elif "removal-creature" in attrs and "removal-planeswalker" in attrs:
        reach = "creatures and planeswalkers"
    elif "removal-creature" in attrs:
        reach = "creatures only"
    else:
        reach = "one kind of permanent"
    if CONDITIONAL_TAGS & attrs:
        reach = "conditional"
    if "removal-exile" in attrs:
        permanence = "exile"
    elif "removal-destroy" in attrs:
        permanence = "destroy"
    elif "removal-bounce" in attrs:
        permanence = "bounce"
    else:
        permanence = "damage or -X/-X"
    return {"speed": speed, "reach": reach, "permanence": permanence, "cost": f"MV {rec['cmc']:g}",
            "repeatable": repeatable}


def _cost_weight(mana_value):
    return next((w for top, w in COST_WEIGHTS if mana_value <= top), COST_DEAR)


def removal_quality(rec, attrs):
    """(value, weights) for one removal card: value = speed × reach × permanence × cost × repeatable, and weights
    holds the five numbers it was made of. For example Assassin's Trophy, an instant that destroys any permanent
    for 2 mana, is 1.0 × 1.0 × 0.9 × 1.0 × 1.0 = 0.90. `attrs` is the card's set of roles.ATTRIBUTE_TAGS slugs."""
    kind = removal_kind(rec, attrs)
    weights = {"speed": SPEED_WEIGHTS[kind["speed"]], "reach": REACH_WEIGHTS[kind["reach"]],
               "permanence": PERMANENCE_WEIGHTS[kind["permanence"]], "cost": _cost_weight(rec["cmc"]),
               "repeatable": REPEATABLE_WEIGHT if kind["repeatable"] else 1.0}
    value = 1.0
    for w in weights.values():
        value *= w
    return value, weights
