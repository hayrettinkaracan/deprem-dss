"""Operasyonel yeniden çözüm. El ile kurulmuş durum; uzun 5.3 koşusu yok."""

from __future__ import annotations

from model.instance import Center, Instance, Scenario, Site, TeamType
from model.operational import (
    OperationalState,
    TeamState,
    build_operational_network,
    solve_operational,
)
from model.staff import Resource


def _case():
    instance = Instance(
        centers=[
            Center(j="J1", name="J1", C={"agir": 1}, U_max=0, W_max=0),
            Center(j="J2", name="J2", C={"agir": 1}, U_max=0, W_max=0),
        ],
        team_types=[TeamType(k="agir", name="Ağır", A=2, p=1.0)],
        sites=[
            Site(i="I1", name="I1", m=1.0, E=0, damage="Ağır", gamma=3.0, m_U=0.0, m_W=0.0),
            Site(i="I2", name="I2", m=1.0, E=0, damage="Orta", gamma=2.0, m_U=0.0, m_W=0.0),
        ],
        scenarios=[
            Scenario(s="s1", name="s1", P=0.5, D=None, beta={"I1": 0.0, "I2": 0.0}),
            Scenario(s="s2", name="s2", P=0.5, D=None, beta={"I1": 0.5, "I2": 0.5}),
        ],
        tau={
            ("J1", "I1"): 0.4,
            ("J2", "I1"): 1.0,
            ("J1", "I2"): 1.0,
            ("J2", "I2"): 0.4,
        },
        N_max=2,
        U_top=0,
        W_top=0,
        L=2.0,
        a={("I1", "agir"): 1, ("I2", "agir"): 1},
    )
    free = Resource(r="agir-1", group="A", p=1.0, k="agir")
    riding = Resource(r="agir-2", group="A", p=1.0, k="agir")
    state = OperationalState(
        t0=2,
        theta=2.0,
        open_centers={"J1", "J2"},
        teams=[
            TeamState(free, b_key="c_J1_t2_l1", e_r=2.0, free=True, left_sites={"I2"}),
            TeamState(riding, b_key="d_I1_t2", e_r=2.0 + 0.5, free=False, left_sites={"I2"}),
        ],
        remaining={
            ("A", "I1", "s1"): 1.0,
            ("A", "I1", "s2"): 1.0,
            ("A", "I2", "s1"): 1.0,
            ("A", "I2", "s2"): 1.0,
        },
    )
    return instance, state


def test_operational_graph_has_no_past_and_only_the_nearest_return():
    instance, state = _case()
    network = build_operational_network(instance, last_period=3, state=state)
    for scenario in instance.scenarios:
        for team in state.teams:
            arcs = network.team_arcs[scenario.s][team.resource.r]
            sigma_heads = [arc.v.key for arc in arcs if arc.u.kind == "sigma"]
            assert sigma_heads == [team.b_key]
            assert all(arc.v.i != "I2" for arc in arcs if arc.v.kind == "debris")
            assert all(arc.u.period() is None or arc.u.period() >= 2 for arc in arcs)
            returns = [arc for arc in arcs if arc.u.kind == "debris" and arc.v.kind == "center"]
            for arc in returns:
                if arc.u.i == "I1":
                    assert arc.v.j == "J1"
                if arc.u.i == "I2":
                    assert arc.v.j == "J2"


def test_en_route_clock_and_free_team_agree_across_scenarios():
    instance, state = _case()
    solution = solve_operational(instance, last_period=3, state=state, time_limit=15, delta=0.001)
    assert solution.status == "Optimal"
    assert solution.objective is not None
    for scenario in ("s1", "s2"):
        assert solution.bas[("agir-2", "d_I1_t2", scenario)] == 2.5
    assert solution.bit[("agir-1", "c_J1_t2_l1", "s1")] == solution.bit[("agir-1", "c_J1_t2_l1", "s2")]
    first = []
    for scenario in ("s1", "s2"):
        dest = None
        for tail, head in solution.arcs[("agir-1", scenario)]:
            if tail != "c_J1_t2_l1":
                continue
            if head.startswith("d_"):
                dest = head.split("_")[1]
        first.append(dest)
    assert first[0] == first[1]
    assert solution.chains[("agir-2", "s1")][0] == "σ"
