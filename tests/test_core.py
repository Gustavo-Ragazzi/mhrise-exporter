from mhrise_exporter.export import Names, _merge_skills, apply_slot_bonus
from mhrise_exporter.gamedata import skill_msg_tag
from mhrise_exporter.murmur3 import hash_utf8, murmur3_32


def test_murmur3_known_field_hashes():
    # Constants from ChevalGrand/mhrise-save-editor src/edit.rs
    assert hash_utf8("_WeaponArmorInventoryList") == 0xA097349E
    assert hash_utf8("snow.data.EquipBox") == 0xF0509899
    assert murmur3_32(b"") == 0x81F16F39


def test_slot_bonus_rule_matches_observed_pieces():
    # (base slots, slot points) -> result; every case was observed in a real save
    assert apply_slot_bonus([3, 2], 2) == [4, 2, 1]
    assert apply_slot_bonus([4, 4, 2], 1) == [4, 4, 3]
    assert apply_slot_bonus([3, 2, 1], 1) == [4, 2, 1]
    assert apply_slot_bonus([4, 4], 1) == [4, 4, 1]
    assert apply_slot_bonus([3], 3) == [4, 1, 1]
    assert apply_slot_bonus([4, 4, 4], 2) == [4, 4, 4]


def test_skill_tags():
    assert skill_msg_tag(1) == "PlayerSkill_000"
    assert skill_msg_tag(0x6F) == "PlayerSkill_110"
    assert skill_msg_tag(0x70) == "PlayerSkill_200"
    assert skill_msg_tag(0) is None


def test_merge_skills_keeps_order_and_splits_signs():
    ups, downs = _merge_skills([(23, -1), (89, 1), (49, 1), (89, 1)])
    assert ups == [(89, 2), (49, 1)]
    assert downs == [(23, -1)]


def test_names_fallback():
    n = Names({"skills": {"1": {"en": "Attack Boost", "ja": "攻撃"}}, "armors": {}}, "pt-br")
    assert n.skill(1) == "Attack Boost"
    assert n.skill(0) == ""
    assert "skill 1" in n.missing
