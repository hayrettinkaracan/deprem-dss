"""Eski zincir çözücüsü. Girdi legacy fixture'dır; yeni Çizelge 5.1 ayrı testte."""

from __future__ import annotations

import time

import pulp
import pytest

from data.legacy_section_5_3 import PERIODS, legacy_section_5_3 as section_5_3
from model.chain_checks import chain_violations
from model.instance import Center, Instance, Scenario, Site, TeamType
from model.network import REPORT_PERIODS, build_network, route_h, travel_sey
from model.routing import chain_rows, constraint_names, format_routing, solve_team_chains

# Varış periyodu saatten gelir. ℓ enkaz sırasını kesmez.
S1_CHAINS = {
    "hafif-1": ["σ", "o_J2", "(I2,1)", "(J2,2,1)", "(I3,3)", "(J2,3,1)", "(I4,4)", "(J2,5,1)", "ω"],
    "orta-1": ["σ", "o_J1", "(I1,1)", "(J1,2,1)", "(I2,3)", "(J1,3,1)", "ω"],
    "orta-2": ["σ", "o_J2", "(I2,1)", "(J2,2,1)", "(I3,3)", "(J2,3,1)", "(I4,4)", "(J2,5,1)", "ω"],
    "agir-1": ["σ", "o_J1", "(I1,1)", "(J1,2,1)", "(I2,3)", "(J1,3,1)", "ω"],
}
S2_CHAINS = {
    "hafif-1": S1_CHAINS["hafif-1"],
    "orta-2": S1_CHAINS["orta-2"],
    "orta-1": ["σ", "o_J1", "(I1,1)", "(J1,2,1)", "(I2,3)", "(J1,4,1)", "ω"],
    "agir-1": ["σ", "o_J1", "(I1,1)", "(J1,2,1)", "(I2,3)", "(J1,4,1)", "ω"],
}
S3_CHAINS = {
    "hafif-1": ["σ", "o_J2", "(I3,1)", "(J2,2,1)", "ω"],
    "orta-2": ["σ", "o_J2", "(I3,1)", "(J2,2,1)", "ω"],
    "orta-1": ["σ", "o_J1", "(I2,1)", "(J1,2,1)", "ω"],
    "agir-1": ["σ", "o_J1", "(I2,1)", "(J1,2,1)", "ω"],
}


def route_sey(instance, arc, scenario):
    return travel_sey(instance, arc.u.physical(), arc.v.physical(), arc.departure_t, scenario)


def _solve(instance, periods=None, reentry_ban=True):
    solver = pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1, timeLimit=90)
    return solve_team_chains(
        instance,
        solver=solver,
        periods=periods,
        reentry_ban=reentry_ban,
    )


def _one_center_instance(sites, teams, scenarios, tau, n_max=1, u_top=0, w_top=0):
    capacity = {spec.k: spec.A for spec in teams}
    return Instance(
        centers=[Center(j="J1", name="J1", C=capacity, U_max=u_top, W_max=w_top)],
        team_types=teams,
        sites=sites,
        scenarios=scenarios,
        tau=tau,
        N_max=n_max,
        U_top=u_top,
        W_top=w_top,
        L=2.0,
    )


def test_network_follows_section_4_3_and_the_two_hour_rule():
    instance = section_5_3()
    short = build_network(instance, periods=1)
    horizon = build_network(instance, periods=PERIODS)

    assert REPORT_PERIODS == 36
    assert horizon.horizon == 72
    assert horizon.big_m == 74
    assert "d_I1_t1" in short.by_key
    assert "d_I1_t36" in horizon.by_key
    assert horizon.by_key["o_J1"].period() == 1
    assert horizon.by_key["d_I5_t36"].label == "(I5,36)"

    for scenario in instance.scenarios:
        arcs = horizon.arcs[scenario.s]
        keys = {(arc.u.key, arc.v.key, arc.kind) for arc in arcs}
        assert ("d_I1_t1", "d_I1_t2", "continue") in keys
        assert ("d_I1_t35", "omega", "end") not in keys
        assert ("d_I1_t36", "omega", "end") in keys
        assert any(arc.kind == "enroute" and arc.u.i == "I2" and arc.v.j == "J1" for arc in arcs)
        assert not any(arc.kind == "enroute" and arc.u.i == "I5" for arc in arcs)
        assert any(arc.kind == "travel" and arc.crosses for arc in arcs)
        assert not any(arc.v.kind == "sigma" or arc.u.kind == "omega" for arc in arcs)
        assert not any(arc.v.kind == "origin" and arc.u.kind != "sigma" for arc in arcs)
        sigma_heads = {arc.v.kind for arc in arcs if arc.u.kind == "sigma"}
        assert sigma_heads == {"origin", "omega"}
        for arc in arcs:
            start = arc.u.period()
            end = arc.v.period()
            if start is not None and end is not None:
                assert end >= start
            if arc.kind == "travel":
                assert arc.v.period() >= arc.u.period()
                assert route_h(
                    instance, arc.u.physical(), arc.v.physical(), arc.departure_t, scenario
                ) == 1
                assert arc.sey == pytest.approx(
                    route_sey(instance, arc, scenario)
                )
                assert {arc.u.kind, arc.v.kind} != {"debris"}
                assert "debris" in {arc.u.kind, arc.v.kind}
            if arc.kind == "continue":
                assert arc.sey == 0
                assert arc.u.i == arc.v.i and arc.v.t == arc.u.t + 1
            if arc.kind == "end" and arc.u.kind == "debris":
                assert arc.u.t == PERIODS
            ends = {arc.u.physical(), arc.v.physical()}
            assert ends != {"J1", "J2"}
            if arc.kind == "travel" and ends == {"J1", "I4"}:
                raise AssertionError("J1–I4 iki saat kuralını aşıyor")
            if "I5" in ends and arc.kind == "travel":
                raise AssertionError("I5 hiçbir merkezden iki saatin altında değil")
    open_arcs = horizon.arcs["s1"]
    # Eski ℓ kuralı yüksek kopyadan küçük indisli enkaza çıkışı keserdi.
    assert any(arc.kind == "travel" and arc.u.key == "c_J2_t1_l4" and arc.v.i == "I2" for arc in open_arcs)
    assert any(arc.u.key == "c_J2_t1_l1" and arc.v.key == "d_I2_t1" for arc in open_arcs)
    assert any(arc.u.key == "d_I2_t1" and arc.v.key == "c_J2_t1_l1" for arc in open_arcs)

    assert route_h(instance, "J2", "I4", 1, instance.scenarios[0]) == 1
    assert route_h(instance, "I4", "J2", 3, instance.scenarios[0]) == 1
    assert route_h(instance, "J2", "I4", 1, instance.scenarios[2]) == 0
    assert route_h(instance, "J1", "I5", 1, instance.scenarios[0]) == 0


def test_constraint_names_cover_the_period_equations():
    names = constraint_names(section_5_3(), periods=2)
    for prefix in (
        "eq_4_4_",
        "eq_4_5_",
        "eq_4_6_",
        "eq_4_7_",
        "eq_4_8_",
        "eq_4_9_",
        "eq_4_10_",
        "eq_4_18_",
        "eq_4_19_",
        "eq_4_20_",
        "eq_4_21_",
        "eq_4_22_",
        "eq_4_23_",
        "eq_4_24_",
        "eq_4_25_",
        "eq_4_27_",
        "eq_4_28_",
        "eq_4_29_",
        "eq_4_30_",
        "eq_4_31_",
        "eq_4_32_",
        "eq_4_33_",
        "eq_4_36_",
        "eq_4_37_",
        "eq_4_38_",
        "eq_4_39_",
    ):
        assert any(name.startswith(prefix) for name in names), prefix
    for later in ("eq_4_11_", "eq_4_34_", "eq_4_46_"):
        assert not any(name.startswith(later) for name in names)

    relaxed = constraint_names(section_5_3(), periods=2, reentry_ban=False)
    assert not any(name.startswith("eq_4_23_") for name in relaxed)


def test_section_53_optimal_chains_and_equations():
    instance = section_5_3()
    started = time.perf_counter()
    solution = _solve(instance)
    print(f"çözüm süresi {time.perf_counter() - started:.1f} sn")
    print(format_routing(instance, solution))

    assert solution.status == "Optimal"
    assert solution.periods == PERIODS == 36
    assert solution.horizon == 72
    assert not chain_violations(instance, solution)
    # s1 = s2 = 10, s3 = 26. Beklenti 14. Madde 2'nin tek periyot sonucu da 14'tü;
    # fark, aynı kapsamın artık gerçek saatlerde durmasıdır.
    assert solution.objective == pytest.approx(14.0)
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
    for scenario_s, expected in (("s1", S1_CHAINS), ("s2", S2_CHAINS), ("s3", S3_CHAINS)):
        for team in solution.teams:
            assert solution.chains[(team.r, scenario_s)] == expected[team.r]
            assert solution.chains[(team.r, scenario_s)][0] == "σ"
            assert solution.chains[(team.r, scenario_s)][-1] == "ω"
    for scenario_s in ("s1", "s2"):
        for site_i, demand in (("I1", 0), ("I2", 0), ("I3", 0), ("I4", 0), ("I5", 10)):
            assert solution.unmet[(site_i, scenario_s)] == pytest.approx(demand)
        assert sum(solution.unmet[(f"I{n}", scenario_s)] for n in range(1, 6)) == pytest.approx(10)
    for site_i, demand in (("I1", 12), ("I2", 0), ("I3", 0), ("I4", 4), ("I5", 10)):
        assert solution.unmet[(site_i, "s3")] == pytest.approx(demand)
    assert sum(solution.unmet[(f"I{n}", "s3")] for n in range(1, 6)) == pytest.approx(26)

    # I5 hiç yok. I4 yalnız J2'den ve yalnız s1/s2'de.
    for team in solution.teams:
        for scenario_s in ("s1", "s2", "s3"):
            chain = solution.chains[(team.r, scenario_s)]
            assert not any(node.startswith("(I5,") for node in chain)
            if chain[1] == "o_J1":
                assert not any(node.startswith("(I4,") for node in chain)
        assert solution.chains[(team.r, "s1")][1] == solution.chains[(team.r, "s3")][1]
    rows = chain_rows(instance, solution)
    assert len(rows) == 12
    assert rows[0]["Zincir"].startswith("σ →")
    assert "1.65" in rows[0]["Zaman"] or rows[0]["Ekip"] != "hafif-1"
    trip = next(
        item
        for item in solution.crossings
        if item.team == "hafif-1" and item.scenario == "s1" and item.origin == "(I2,1)"
    )
    assert trip.departure_period == 1
    assert trip.arrival_period == 2
    assert trip.beta == pytest.approx(0.10)
    assert trip.sey == pytest.approx(1.65)
    assert trip.arrive_h == pytest.approx(trip.depart_h + trip.sey)
    assert trip.depart_h == pytest.approx(1.65)
    assert solution.inventory[("J2", "hafif", 0, "s1")] == 1
    assert solution.inventory[("J2", "hafif", 1, "s1")] == 0
    assert solution.inventory[("J2", "hafif", 5, "s1")] == 1


def test_known_two_site_chain_is_optimal():
    """Tek ekip, iki enkaz. Her giriş m_i = L işi bitirir; ikisi de gereklidir.

    Enkazlar arası yay yoktur. Ekip J1'e döner. Beraberlik, küçük indisi
    önce ve ℓ = 1 seçer. Zincir bu yüzden tektir.
    """

    sites = [
        Site(i="I1", name="I1", m=2.0, E=0),
        Site(i="I2", name="I2", m=2.0, E=0),
    ]
    instance = _one_center_instance(
        sites,
        [TeamType(k="hafif", name="Hafif", A=1, p=1.0)],
        [Scenario(s="s1", name="Tek", P=1.0, D={"I1": 10.0, "I2": 6.0}, beta={"I1": 0.0, "I2": 0.0})],
        {("J1", "I1"): 0.5, ("J1", "I2"): 0.5},
    )
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert not chain_violations(instance, solution)
    assert solution.objective == pytest.approx(0.0)
    assert solution.V[("J1", "hafif")] == 1
    assert solution.chains[("hafif-1", "s1")] == [
        "σ",
        "o_J1",
        "(I1,1)",
        "(J1,1,1)",
        "(I2,1)",
        "(J1,1,2)",
        "ω",
    ]
    clock = solution.clock[("hafif-1", "s1")]
    assert [item[0] for item in clock[1:6]] == ["o_J1", "(I1,1)", "(J1,1,1)", "(I2,1)", "(J1,1,2)"]
    assert [item[1] for item in clock[1:6]] == pytest.approx([0.0, 0.5, 1.0, 1.5, 2.0])
    assert [item[2] for item in clock[1:5]] == pytest.approx([0.0, 0.5, 1.0, 1.5])
    assert solution.entries[("hafif-1", "I1", "s1")] == 1
    assert solution.entries[("hafif-1", "I2", "s1")] == 1


def test_reentry_ban_4_23_blocks_a_second_entry():
    """m = 4. Bir giriş L = 2 saat yazar, u = 4. İkinci giriş u = 0 yapardı.

    Devam (I1,1) → (I1,2) aynı görevdir ve (4.23) toplamına girmez; yer tutucu
    iş onu ikinci kez saymaz. Yasak kalkınca ekip merkezden ikinci kez girer.
    """

    site = [Site(i="I1", name="I1", m=4.0, E=0)]
    instance = _one_center_instance(
        site,
        [TeamType(k="hafif", name="Hafif", A=1, p=1.0)],
        [Scenario(s="s1", name="Tek", P=1.0, D={"I1": 8.0}, beta={"I1": 0.0})],
        {("J1", "I1"): 0.5},
    )
    banned = _solve(instance, periods=2, reentry_ban=True)
    assert banned.status == "Optimal"
    assert not chain_violations(instance, banned)
    assert banned.objective == pytest.approx(4.0)
    assert banned.entries[("hafif-1", "I1", "s1")] == 1
    assert banned.chains[("hafif-1", "s1")] == ["σ", "o_J1", "(I1,1)", "(J1,1,1)", "ω"]

    opened = _solve(instance, periods=2, reentry_ban=False)
    assert opened.status == "Optimal"
    assert not chain_violations(instance, opened)
    assert opened.objective == pytest.approx(0.0)
    assert opened.entries[("hafif-1", "I1", "s1")] == 2
    assert opened.chains[("hafif-1", "s1")] == [
        "σ",
        "o_J1",
        "(I1,1)",
        "(J1,1,2)",
        "(I1,2)",
        "ω",
    ]
    assert opened.objective < banned.objective


def test_unused_team_takes_sigma_omega_and_start_matches_v():
    site = [Site(i="I1", name="I1", m=2.0, E=0)]
    instance = _one_center_instance(
        site,
        [TeamType(k="hafif", name="Hafif", A=2, p=1.0)],
        [Scenario(s="s1", name="Tek", P=1.0, D={"I1": 10.0}, beta={"I1": 0.0})],
        {("J1", "I1"): 0.5},
    )
    solution = _solve(instance)
    assert solution.status == "Optimal"
    assert not chain_violations(instance, solution)
    assert solution.objective == pytest.approx(0.0)
    assert solution.V[("J1", "hafif")] == 1
    assert solution.chains[("hafif-1", "s1")] == ["σ", "ω"]
    assert solution.chains[("hafif-2", "s1")] == ["σ", "o_J1", "(I1,1)", "(J1,1,1)", "ω"]


def test_closed_horizon_and_incompetent_teams_do_not_travel():
    blocked = section_5_3()
    blocked.N_max = 0
    solution = _solve(blocked, periods=1)
    assert solution.status == "Optimal"
    assert not chain_violations(blocked, solution)
    assert solution.objective == pytest.approx(40)
    assert all(value == 0 for value in solution.G.values())
    assert all(value == 0 for value in solution.V.values())
    for team in solution.teams:
        for scenario in blocked.scenarios:
            assert solution.chains[(team.r, scenario.s)] == ["σ", "ω"]

    blind = section_5_3()
    blind.a = {(site.i, spec.k): 0 for site in blind.sites for spec in blind.team_types}
    blind_solution = _solve(blind, periods=1)
    assert blind_solution.status == "Optimal"
    assert not chain_violations(blind, blind_solution)
    assert blind_solution.objective == pytest.approx(40)
    assert all(value == 0 for value in blind_solution.entries.values())
    for team in blind_solution.teams:
        for scenario in blind.scenarios:
            chain = blind_solution.chains[(team.r, scenario.s)]
            assert not any(node.startswith("(I") for node in chain)
