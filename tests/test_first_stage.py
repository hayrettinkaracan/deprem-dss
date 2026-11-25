"""Eski çözücü (4.4)–(4.10). Girdi legacy fixture'dır; yeni Çizelge 5.1 ayrı testte."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pulp
import pytest

from data.legacy_section_5_3 import PERIODS, TAU, legacy_section_5_3 as section_5_3
from model.checks import violations
from model.instance import h_matrix, route_open
from model.planning_inputs import build_live_instance
from model.problem import constraint_names, format_solution, solve_first_stage

ROOT = Path(__file__).resolve().parents[1]

# τ(1+β) ≤ 2 kuralının elle hesabı. s1 ve s2 aynı desene düşer.
H_S1 = {"J1": "11000", "J2": "01110"}
H_S3 = {"J1": "01000", "J2": "00100"}


def _solve(instance):
    solver = pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1)
    return solve_first_stage(instance, solver=solver)


def test_table_5_1_and_route_rule():
    instance = section_5_3()
    assert PERIODS == 36
    assert instance.L == 2
    assert [site.m for site in instance.sites] == [4.0, 3.0, 2.5, 1.5, 4.5]
    assert [site.E for site in instance.sites] == [1, 1, 0, 0, 1]
    assert [site.damage for site in instance.sites] == ["Ağır", "Orta", "Orta", "Hafif", "Ağır"]
    assert [team.A for team in instance.team_types] == [1, 2, 1]
    assert instance.U_top == 3 and instance.W_top == 2 and instance.N_max == 2
    assert instance.tau == TAU
    assert [scenario.P for scenario in instance.scenarios] == pytest.approx([0.30, 0.45, 0.25])
    assert sum(scenario.P for scenario in instance.scenarios) == pytest.approx(1)

    usable = h_matrix(instance)
    for scenario, expected in (("s1", H_S1), ("s2", H_S1), ("s3", H_S3)):
        for center, bits in expected.items():
            got = "".join(str(usable[(center, f"I{n}", scenario)]) for n in range(1, 6))
            assert got == bits
    # I5 hiçbir senaryoda iki saatin altında değil.
    assert route_open(3.0, 0.10, 2) == 0
    assert route_open(1.5, 0.10, 2) == 1


def test_constraint_names_are_report_equations():
    names = constraint_names(section_5_3())
    for prefix in ("eq_4_4_", "eq_4_5_", "eq_4_6_", "eq_4_7_", "eq_4_8_", "eq_4_9_", "eq_4_10_"):
        assert any(name.startswith(prefix) for name in names)
    assert not any("budget" in name or "cap_tot" in name for name in names)


def test_section_53_optimal_and_first_stage_constraints():
    instance = section_5_3()
    solution = _solve(instance)
    print(format_solution(instance, solution))

    assert solution.status == "Optimal"
    assert not violations(instance, solution)
    assert solution.G == {"J1": 1, "J2": 1}
    assert solution.V == {
        ("J1", "hafif"): 0,
        ("J1", "orta"): 1,
        ("J1", "agir"): 1,
        ("J2", "hafif"): 1,
        ("J2", "orta"): 1,
        ("J2", "agir"): 0,
    }
    assert solution.VU == {"J1": 0, "J2": 0}
    assert solution.VW == {"J1": 0, "J2": 0}
    assert sum(solution.V.values()) == 4
    # s1 = s2 = 8/3 + 1.2 + 14 = 268/15; s3 = 12+4+10 = 26; beklenti 19.9
    assert sum(solution.unmet[(site.i, "s1")] for site in instance.sites) == pytest.approx(268 / 15)
    assert sum(solution.unmet[(site.i, "s3")] for site in instance.sites) == pytest.approx(26)
    assert solution.objective == pytest.approx(19.9)

    again = _solve(section_5_3())
    assert again.G == solution.G and again.V == solution.V
    assert again.VU == solution.VU and again.VW == solution.VW


def test_second_stage_uses_only_prepositioned_teams_and_open_routes():
    instance = section_5_3()
    solution = _solve(instance)
    for center in instance.centers:
        for team in instance.team_types:
            for scenario in instance.scenarios:
                dispatched = sum(
                    solution.y[(center.j, team.k, site.i, scenario.s)] for site in instance.sites
                )
                assert dispatched <= solution.V[(center.j, team.k)]
                for site in instance.sites:
                    flow = solution.y[(center.j, team.k, site.i, scenario.s)]
                    if solution.h[(center.j, site.i, scenario.s)] == 0:
                        assert flow == 0


def test_nmax_zero_blocks_prepositioning():
    instance = section_5_3()
    instance.N_max = 0
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert not violations(instance, solution)
    assert all(value == 0 for value in solution.G.values())
    assert all(value == 0 for value in solution.V.values())
    assert all(value == 0 for value in solution.VU.values())
    assert all(value == 0 for value in solution.VW.values())
    assert all(value == 0 for value in solution.y.values())
    assert solution.objective == pytest.approx(40)


def test_closing_j1_changes_outcome():
    base = _solve(section_5_3())
    assert base.G["J1"] == 1
    closed = section_5_3()
    closed.centers = [center for center in closed.centers if center.j != "J1"]
    alternative = _solve(closed)
    assert alternative.status == "Optimal"
    assert not violations(closed, alternative)
    assert alternative.G == {"J2": 1}
    assert alternative.objective == pytest.approx(25.9)
    assert alternative.objective > base.objective + 1


def test_zero_probability_does_not_open_centers():
    instance = section_5_3()
    instance.scenarios = [replace(scenario, P=0.0) for scenario in instance.scenarios]
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert solution.objective == pytest.approx(0)
    assert all(value == 0 for value in solution.G.values())


def test_competency_zero_removes_service():
    instance = section_5_3()
    instance.a = {
        (site.i, team.k): 0 for site in instance.sites for team in instance.team_types
    }
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert not violations(instance, solution)
    assert all(value == 0 for value in solution.G.values())
    assert solution.objective == pytest.approx(40)


def test_live_adapter_is_deterministic_and_feasible():
    enkaz = [
        {"id": 1, "isim": "Avcılar-Merkez", "enlem": 40.9840, "boylam": 28.7275, "talep": 180},
        {"id": 2, "isim": "Avcılar-Ambarlı", "enlem": 40.9568, "boylam": 28.6810, "talep": 130},
    ]
    ekipler = [
        {"id": 10, "tip": "Arama-Kurtarma", "kapasite": 80},
        {"id": 11, "tip": "Arama-Kurtarma", "kapasite": 40},
    ]
    first = build_live_instance(enkaz, ekipler)
    second = build_live_instance(list(reversed(enkaz)), list(reversed(ekipler)))
    assert first.tau == second.tau
    assert [scenario.P for scenario in first.scenarios] == pytest.approx([0.30, 0.45, 0.25])
    solution = _solve(first)
    assert solution.status == "Optimal"
    assert not violations(first, solution)
    assert sum(solution.G.values()) >= 1
    assert sum(solution.V.values()) == 2


def test_model_package_has_no_ui_imports():
    banned = {"streamlit", "supabase"}
    for folder in ("model", "data"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module.split(".")[0]]
                else:
                    continue
                assert banned.isdisjoint(modules), f"{path} {modules}"


def test_app_delegates_the_model():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "LpProblem" not in source
    assert "LpVariable" not in source
    assert "solve_team_to_site" in source
    assert "solve_first_stage" in source
