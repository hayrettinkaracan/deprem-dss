"""Birinci aşama kısıtları ve Bölüm 5.3 doğrulaması."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pulp
import pytest

from data.section_5_3 import COVERAGE_53, section_5_3
from model.checks import violations
from model.instance import coverage_matrix
from model.planning_inputs import build_live_instance
from model.problem import format_solution, solve_first_stage

ROOT = Path(__file__).resolve().parents[1]


def _solve(instance):
    solver = pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1)
    return solve_first_stage(instance, solver=solver)


def test_section_53_coverage_matches_documented_radius():
    assert coverage_matrix(section_5_3()) == COVERAGE_53


def test_section_53_optimal_and_first_stage_constraints():
    instance = section_5_3()
    solution = _solve(instance)
    print(format_solution(instance, solution))

    assert solution.status == "Optimal"
    assert not violations(instance, solution)

    # Bütçe j1+j3 = 160 ile dolar. Karşılanmayan talep senaryolara 190+310+450 dağılır.
    assert solution.G == {"j1": 1, "j2": 0, "j3": 1}
    assert solution.opening_cost == pytest.approx(160.0)
    assert solution.unmet_cost == pytest.approx(950.0)
    assert solution.objective == pytest.approx(1110.0)

    assert solution.V == {
        ("j1", "hafif"): 2,
        ("j1", "orta"): 0,
        ("j1", "agir"): 1,
        ("j2", "hafif"): 0,
        ("j2", "orta"): 0,
        ("j2", "agir"): 0,
        ("j3", "hafif"): 0,
        ("j3", "orta"): 1,
        ("j3", "agir"): 0,
    }
    assert solution.VU == {"j1": 2, "j2": 0, "j3": 1}
    assert solution.VW == {"j1": 1, "j2": 0, "j3": 1}
    assert sum(solution.unmet[(site.i, "iyimser")] for site in instance.sites) == pytest.approx(190.0)
    assert sum(solution.unmet[(site.i, "baz")] for site in instance.sites) == pytest.approx(310.0)
    assert sum(solution.unmet[(site.i, "kotumser")] for site in instance.sites) == pytest.approx(450.0)

    again = _solve(section_5_3())
    assert again.G == solution.G
    assert again.V == solution.V
    assert again.VU == solution.VU
    assert again.VW == solution.VW

    for team in instance.team_types:
        placed = sum(solution.V[(center.j, team.k)] for center in instance.centers)
        assert placed == team.N


def test_second_stage_uses_only_prepositioned_teams():
    instance = section_5_3()
    solution = _solve(instance)
    assert solution.status == "Optimal"

    for center in instance.centers:
        for team in instance.team_types:
            for scenario in instance.scenarios:
                dispatched = sum(
                    solution.y[(center.j, team.k, site.i, scenario.s)] for site in instance.sites
                )
                assert dispatched <= solution.V[(center.j, team.k)]
                if solution.G[center.j] == 0:
                    assert dispatched == 0
                for site in instance.sites:
                    flow = solution.y[(center.j, team.k, site.i, scenario.s)]
                    if scenario.h[site.i] == 0 or solution.coverage[(center.j, site.i)] == 0:
                        assert flow == 0


def test_zero_budget_no_prepositioning():
    instance = section_5_3()
    instance.B = 0
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert not violations(instance, solution)
    assert all(value == 0 for value in solution.G.values())
    assert all(value == 0 for value in solution.V.values())
    assert all(value == 0 for value in solution.VU.values())
    assert all(value == 0 for value in solution.VW.values())
    assert all(value == 0 for value in solution.y.values())
    total_demand = sum(scenario.pi * site.d for scenario in instance.scenarios for site in instance.sites)
    assert solution.objective == pytest.approx(total_demand)
    assert solution.opening_cost == pytest.approx(0.0)


def test_closing_center_changes_outcome():
    base_instance = section_5_3()
    base = _solve(base_instance)
    assert base.G["j1"] == 1

    closed = section_5_3()
    closed.centers = [center for center in closed.centers if center.j != "j1"]
    alternative = _solve(closed)

    assert alternative.status == "Optimal"
    assert not violations(closed, alternative)
    assert alternative.G == {"j2": 1, "j3": 1}
    assert alternative.objective == pytest.approx(1330.0)
    assert alternative.objective > base.objective + 1.0


def test_zero_scenario_weight_does_not_open_centers():
    instance = section_5_3()
    instance.scenarios = [replace(scenario, pi=0.0) for scenario in instance.scenarios]
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert not violations(instance, solution)
    assert solution.objective == pytest.approx(0.0)
    assert all(value == 0 for value in solution.G.values())


def test_competency_zero_removes_service():
    instance = section_5_3()
    instance.a = {
        (site.i, team.k): 0.0 for site in instance.sites for team in instance.team_types
    }
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert all(value == 0 for value in solution.G.values())
    assert all(value == 0 for value in solution.V.values())
    total_demand = sum(site.d for site in instance.sites) * len(instance.scenarios)
    assert solution.objective == pytest.approx(total_demand)


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
    for left, right in zip(first.scenarios, second.scenarios):
        assert left.h == right.h
        assert left.beta in (0.2, 0.5, 1.0)

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
