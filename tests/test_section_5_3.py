"""Yeni Çizelge 5.1, türetilmiş işler, a matrisi, h ve (4.6)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from data import section_5_3 as fixture
from data.section_5_3 import HYK_KARARI, PERIODS, RHO_U, RHO_W, section_5_3
from model.instance import h_matrix, route_open, validate
from model.network import beta_at, route_h
from model.opening_cost import calibrate_opening_cost
from model.problem import solve_first_stage

# Çizelge 5.1, rapordan. m^U ve m^W 5.3.1 çarpımıdır.
TABLE = {
    "I1": ("Ağır", 3, 4.0, 1.2, 2.0, 1, 0.8, 1.2, "J1"),
    "I2": ("Orta", 2, 3.0, 0.9, 1.5, 1, 0.5, 1.0, "J1"),
    "I3": ("Orta", 2, 2.5, 0.75, 0.0, 0, 1.2, 0.5, "J2"),
    "I4": ("Hafif", 1, 1.5, 0.45, 0.0, 0, 1.3, 0.8, "J2"),
    "I5": ("Ağır", 3, 4.5, 1.35, 2.25, 1, 1.3, 1.0, "J2"),
}

# a_{i,k}. Hafif yalnız Hafif, Orta Orta+Hafif, Ağır hepsi.
A_MATRIX = {
    "hafif": (0, 0, 0, 1, 0),
    "orta": (0, 1, 1, 1, 0),
    "agir": (1, 1, 1, 1, 1),
}


def test_table_5_1_cells_and_derived_work():
    instance = section_5_3()
    assert PERIODS == 36
    assert instance.L == 2
    assert [site.i for site in instance.sites] == ["I1", "I2", "I3", "I4", "I5"]
    for site in instance.sites:
        damage, gamma, m_a, m_u, m_w, machine, tau_j1, tau_j2, nearest = TABLE[site.i]
        assert site.damage == damage
        assert site.gamma == gamma
        assert site.m == pytest.approx(m_a)
        assert site.m_U == pytest.approx(m_u)
        assert site.m_W == pytest.approx(m_w)
        assert site.E == machine
        assert instance.tau[("J1", site.i)] == pytest.approx(tau_j1)
        assert instance.tau[("J2", site.i)] == pytest.approx(tau_j2)
        assert site.m_U == pytest.approx(RHO_U * site.m)
        assert site.m_W == pytest.approx(RHO_W * site.m if site.E == 1 else 0.0)
        assert RHO_U == pytest.approx(0.3)
        assert RHO_W == pytest.approx(0.5)
        by_tau = min(("J1", tau_j1), ("J2", tau_j2), key=lambda item: item[1])[0]
        assert by_tau == nearest
    assert not hasattr(fixture, "DEMAND")
    for scenario in instance.scenarios:
        assert scenario.D is None
        assert scenario.beta_t is None


def test_probabilities_betas_and_no_invented_arcs():
    instance = section_5_3()
    by_name = {scenario.s: scenario for scenario in instance.scenarios}
    assert [scenario.P for scenario in instance.scenarios] == pytest.approx([0.30, 0.45, 0.25])
    assert sum(scenario.P for scenario in instance.scenarios) == pytest.approx(1)
    assert by_name["s1"].name == "İyimser"
    assert by_name["s2"].name == "Beklenen"
    assert by_name["s3"].name == "Kötümser"
    for site in instance.sites:
        assert by_name["s1"].beta[site.i] == pytest.approx(0.10)
        expected_s2 = 0.30 if site.i in {"I1", "I5"} else 0.15
        assert by_name["s2"].beta[site.i] == pytest.approx(expected_s2)
        assert by_name["s3"].beta[site.i] == pytest.approx(0.50)
        for period in (1, 18, PERIODS):
            for center in instance.centers:
                assert beta_at(instance, by_name["s2"], center.j, site.i, period) == pytest.approx(
                    by_name["s2"].beta[site.i]
                )

    sites = {site.i for site in instance.sites}
    centers = {center.j for center in instance.centers}
    center_site = {(center, site) for center in centers for site in sites}
    assert center_site <= set(instance.tau)
    assert not hasattr(fixture, "REPLAN_EVENTS")


def test_competency_matrix():
    instance = section_5_3()
    assert [team.k for team in instance.team_types] == ["hafif", "orta", "agir"]
    assert [team.A for team in instance.team_types] == [1, 2, 1]
    for team in instance.team_types:
        got = tuple(instance.a[(f"I{n}", team.k)] for n in range(1, 6))
        assert got == A_MATRIX[team.k]


def test_h_is_one_on_every_center_site_pair():
    instance = section_5_3()
    usable = h_matrix(instance)
    worst = 0.0
    for center in instance.centers:
        for site in instance.sites:
            for scenario in instance.scenarios:
                travel = instance.tau[(center.j, site.i)] * (1.0 + scenario.beta[site.i])
                worst = max(worst, travel)
                assert usable[(center.j, site.i, scenario.s)] == 1
                assert route_open(instance.tau[(center.j, site.i)], scenario.beta[site.i], instance.L) == 1
                for period in range(1, PERIODS + 1):
                    assert route_h(instance, center.j, site.i, period, scenario) == 1
    # En uzun etkin süre: 1,3 × (1 + 0,50) = 1,95 ≤ 2.
    assert worst == pytest.approx(1.3 * 1.5)
    assert worst <= 2


def test_hyk_decisions_are_recorded_and_applied():
    instance = section_5_3()
    assert HYK_KARARI.baslik == "HYK kararı (rapor sayı vermiyor)"
    assert HYK_KARARI.N_max_kurali == "|J|"
    assert HYK_KARARI.C_jk == "A_k"
    assert HYK_KARARI.U_j_max_kurali == "U_top"
    assert HYK_KARARI.W_j_max_kurali == "W_top"
    assert HYK_KARARI.U_top == 3
    assert HYK_KARARI.W_top == 2
    assert HYK_KARARI.vartheta == pytest.approx(0.01)
    assert HYK_KARARI.beta_bar == "olasılık ağırlıklı senaryo ortalaması"
    assert instance.N_max == len(instance.centers) == 2
    assert instance.U_top == 3 and instance.W_top == 2
    for center in instance.centers:
        for team in instance.team_types:
            assert center.C[team.k] == team.A
        assert center.U_max == instance.U_top
        assert center.W_max == instance.W_top
    validate(instance)


def test_opening_cost_matches_the_hand_calculation():
    instance = section_5_3()
    cost = calibrate_opening_cost(instance)

    heavy = 0.30 * 0.10 + 0.45 * 0.30 + 0.25 * 0.50
    other = 0.30 * 0.10 + 0.45 * 0.15 + 0.25 * 0.50
    assert heavy == pytest.approx(0.29)
    assert other == pytest.approx(0.2225)
    for site_i, expected in (("I1", heavy), ("I5", heavy), ("I2", other), ("I3", other), ("I4", other)):
        assert cost.beta_bar[site_i] == pytest.approx(expected)
        assert cost.pi[site_i] == pytest.approx(1)

    assert cost.nearest == {"I1": "J1", "I2": "J1", "I3": "J2", "I4": "J2", "I5": "J2"}
    assert cost.second == {"I1": "J2", "I2": "J2", "I3": "J1", "I4": "J1", "I5": "J1"}

    # Elle: fark = |τ_J1 − τ_J2| · (1 + β̄), katkı = γ · fark. π = 1.
    psi_j1 = 3 * (1.2 - 0.8) * (1 + heavy) + 2 * (1.0 - 0.5) * (1 + other)
    psi_j2 = (
        2 * (1.2 - 0.5) * (1 + other)
        + 1 * (1.3 - 0.8) * (1 + other)
        + 3 * (1.3 - 1.0) * (1 + heavy)
    )
    assert psi_j1 == pytest.approx(2.7705)
    assert psi_j2 == pytest.approx(3.48375)
    assert cost.psi["J1"] == pytest.approx(psi_j1)
    assert cost.psi["J2"] == pytest.approx(psi_j2)
    assert cost.f == pytest.approx((psi_j1 + psi_j2) / 2)
    assert cost.f == pytest.approx(3.127125)
    assert cost.phi["J1"] == pytest.approx(9)
    assert cost.phi["J2"] == pytest.approx(9)
    assert cost.phi_bar == pytest.approx(9)
    assert cost.f_j["J1"] == pytest.approx(cost.f)
    assert cost.f_j["J2"] == pytest.approx(cost.f)

    # τ̄ örneği: I1–J1 = 0,8 × 1,29.
    assert cost.tau_bar[("J1", "I1")] == pytest.approx(0.8 * (1 + heavy))
    assert cost.tau_bar[("J2", "I5")] == pytest.approx(1.0 * (1 + heavy))


def test_f_j_scales_when_capacities_differ():
    instance = section_5_3()
    base = calibrate_opening_cost(instance)
    j1, j2 = instance.centers
    instance.centers = [j1, replace(j2, U_max=0)]
    scaled = calibrate_opening_cost(instance)
    assert scaled.f == pytest.approx(base.f)
    assert scaled.phi["J1"] == pytest.approx(9)
    assert scaled.phi["J2"] == pytest.approx(6)
    assert scaled.phi_bar == pytest.approx(7.5)
    assert scaled.f_j["J1"] == pytest.approx(base.f * 9 / 7.5)
    assert scaled.f_j["J2"] == pytest.approx(base.f * 6 / 7.5)


def test_legacy_solver_rejects_the_new_fixture():
    with pytest.raises(ValueError, match="D"):
        solve_first_stage(section_5_3())
