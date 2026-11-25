"""Planlama Z1. Altın amaç değeri yok; 5.3.2'nin bu dilimdeki denetimleri var."""

from __future__ import annotations

from data.section_5_3 import HYK_KARARI, section_5_3
from model.planning import constraint_names, solve_planning
from model.planning_checks import planning_violations
from model.planning_network import useful_center_copies

PREFIXES = (
    "eq_4_7_",
    "eq_4_8_",
    "eq_4_9_",
    "eq_4_10_",
    "eq_4_11_",
    "eq_4_12_",
    "eq_4_13_",
    "eq_4_14_",
    "eq_4_15_",
    "eq_4_16_",
    "eq_4_17_",
    "eq_4_18_",
    "eq_4_19_",
    "eq_4_20_",
    "eq_4_21_",
    "eq_4_22_",
    "eq_4_23_",
    "eq_4_24_",
    "eq_4_25_",
    "eq_4_26_",
    "eq_4_27_",
    "eq_4_30_",
    "eq_4_31_",
    "eq_4_32_",
    "eq_4_34_",
)


def test_planning_constraint_names_follow_the_new_report():
    names = constraint_names(section_5_3(), periods=2, vartheta=HYK_KARARI.vartheta)
    for prefix in PREFIXES:
        assert any(name.startswith(prefix) for name in names), prefix
    assert not any(name.startswith("eq_4_28_") for name in names)
    assert not any(name.startswith("unmet") or name.startswith("primary_lock") for name in names)
    assert not any(name.startswith("eq_4_36_") or name.startswith("eq_4_39_") for name in names)


def test_unreachable_center_copies_are_dropped_and_identical_teams_are_ordered():
    instance = section_5_3()
    # En kısa gidiş-dönüş 1,1 saat. İkinci dönüş aynı pencereye sığmaz; ℓ=2 yeter.
    assert useful_center_copies(instance) == 2
    names = constraint_names(instance, periods=1, vartheta=HYK_KARARI.vartheta)
    assert "sym_orta_1_orta_2" in names
    assert "sym_umke_1_umke_2" in names
    assert "sym_makine_1_makine_2" in names


def test_one_period_incumbent_passes_the_validation_checks():
    solution = solve_planning(
        section_5_3(),
        periods=1,
        time_limit=8,
        vartheta=HYK_KARARI.vartheta,
    )
    assert solution.status in {"Optimal", "Time limit"}
    assert solution.objective is not None
    assert solution.gap is not None
    assert planning_violations(section_5_3(), solution, vartheta=HYK_KARARI.vartheta) == []
    assert set(solution.z1_by_scenario) == {"s1", "s2", "s3"}

