"""Tests for the patch-notes renderer (ingestion/load_patch_notes.py).

`render_notes` is pure -- it takes the datafeed payload plus three name lookups
and returns text -- so nothing here touches the network or the DB. The cases
are the shapes actually observed in 7.39-7.41e.
"""
from app.ingestion.load_patch_notes import render_notes

HEROES = {2: "Axe", 11: "Shadow Fiend"}
ITEMS = {208: "Abyssal Blade", 1868: "Ocean Heart"}
ABILITIES = {5008: "Battle Hunger", 1348: "Demolish"}

HEADER = "Dota 2 patch 7.41e (released 2026-07-30)"


def render(**sections) -> str:
    payload = {"patch_number": "7.41e", "patch_timestamp": 1785394800, **sections}
    return render_notes(payload, HEROES, ITEMS, ABILITIES)


def note(text: str, **extra) -> dict:
    return {"indent_level": 1, "note": text, **extra}


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------

def test_header_carries_version_and_release_date():
    assert render().splitlines()[0] == HEADER


def test_a_patch_with_no_changes_is_just_the_header():
    assert render() == HEADER


def test_empty_sections_are_dropped_entirely():
    out = render(items=[], neutral_items=[], heroes=[], general_notes=[])
    assert "== ITEMS ==" not in out and "== HEROES ==" not in out


def test_sections_appear_in_a_fixed_order():
    out = render(
        general_notes=[{"title": "Twin Gates", "generic": [note("Interruptible by root")]}],
        items=[{"ability_id": 208, "ability_notes": [note("Strength +26 to +30")]}],
        neutral_items=[{"ability_id": 1868, "ability_notes": [note("Forage 1s to 0.75s")]}],
        heroes=[{"hero_id": 2, "hero_notes": [note("Base Agility 20 to 18")]}],
    )
    order = [out.index(f"== {s} ==") for s in ("GENERAL", "ITEMS", "NEUTRAL ITEMS", "HEROES")]
    assert order == sorted(order)


# --------------------------------------------------------------------------
# Note rendering
# --------------------------------------------------------------------------

def test_spacer_notes_are_dropped():
    # The feed pads entries with a <br> note carrying hide_dot; it must not
    # survive as an empty bullet.
    out = render(items=[{
        "ability_id": 208,
        "ability_notes": [note("Strength +26 to +30"), note("<br>", hide_dot=True)],
    }])
    assert out.count("\n- ") == 1
    assert "<br>" not in out


def test_an_entry_whose_notes_are_all_spacers_is_dropped():
    out = render(items=[{"ability_id": 208, "ability_notes": [note("<br>", hide_dot=True)]}])
    assert "Abyssal Blade" not in out and "== ITEMS ==" not in out


def test_info_is_appended_in_parentheses():
    out = render(neutral_items=[{
        "ability_id": 1868,
        "ability_notes": [note("Damage 30 to 20", info="From 39 to 26 with Dormant Curio")],
    }])
    assert "- Damage 30 to 20 (From 39 to 26 with Dormant Curio)" in out


def test_indent_level_two_is_nested():
    out = render(items=[{"ability_id": 208, "ability_notes": [
        note("Strength +26 to +30"), {"indent_level": 2, "note": "Also on illusions"},
    ]}])
    assert "- Strength +26 to +30" in out
    assert "-   Also on illusions" in out


# --------------------------------------------------------------------------
# Name resolution
# --------------------------------------------------------------------------

def test_ability_notes_are_prefixed_with_the_ability_name():
    out = render(heroes=[{
        "hero_id": 2,
        "abilities": [{"ability_id": 5008, "ability_notes": [note("DPS 30 to 24")]}],
    }])
    assert "Axe\n- Battle Hunger: DPS 30 to 24" in out


def test_hero_notes_and_talent_notes_need_no_prefix():
    out = render(heroes=[{
        "hero_id": 11,
        "hero_notes": [note("Base Intelligence 18 to 16", icon="intelligence")],
        "talent_notes": [note("Level 25 Talent no longer applies attack modifiers")],
    }])
    assert out.endswith(
        "Shadow Fiend\n"
        "- Base Intelligence 18 to 16\n"
        "- Level 25 Talent no longer applies attack modifiers"
    )


def test_a_hero_with_no_abilities_key_still_renders():
    # 7.41c and 7.41d both ship hero entries with hero_notes and nothing else.
    out = render(heroes=[{"hero_id": 2, "hero_notes": [note("Base Armor decreased by 1")]}])
    assert "Axe\n- Base Armor decreased by 1" in out


def test_spirit_bear_is_named_rather_than_shown_as_an_id():
    out = render(heroes=[{
        "hero_id": 1961,
        "abilities": [{"ability_id": 1348, "ability_notes": [note("Building damage 30% to 20%")]}],
    }])
    assert "Spirit Bear\n- Demolish: Building damage 30% to 20%" in out


def test_unknown_ids_fall_back_to_the_id_instead_of_raising():
    out = render(
        items=[{"ability_id": 999, "ability_notes": [note("New item")]}],
        heroes=[{
            "hero_id": 888,
            "abilities": [{"ability_id": 777, "ability_notes": [note("New spell")]}],
        }],
    )
    assert "Item 999\n- New item" in out
    assert "Hero 888\n- Ability 777: New spell" in out


# --------------------------------------------------------------------------
# Neutral item headings
# --------------------------------------------------------------------------

def test_neutral_tier_headings_are_kept():
    out = render(neutral_items=[
        {"ability_id": -1, "title": "Artifacts", "is_general_note": True},
        {"ability_id": 1868, "ability_notes": [note("Forage 1s to 0.75s")]},
    ])
    assert "[Artifacts]" in out
    assert out.index("[Artifacts]") < out.index("Ocean Heart")


def test_a_heading_with_nothing_under_it_is_dropped():
    out = render(neutral_items=[
        {"ability_id": -1, "title": "Artifacts", "is_general_note": True},
        {"ability_id": 1868, "ability_notes": [note("<br>", hide_dot=True)]},
    ])
    assert "Artifacts" not in out
