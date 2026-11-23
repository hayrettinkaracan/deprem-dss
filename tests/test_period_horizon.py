"""36 periyot, periyot aşan yol ve ufuk sonu dönüşü."""

from __future__ import annotations

import pulp
import pytest

from model.chain_checks import chain_violations
from model.instance import Center, Instance, Scenario, Site, TeamType
from model.network import build_network, route_h, travel_sey
from model.routing import _build, solve_team_chains

SOLVER = pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1, timeLimit=30, warmStart=True)


def _instance(tau, beta=0.0, beta_t=None, periods_demand=10.0, m=2.0):
    return Instance(
        centers=[Center(j="J1", name="J1", C={"hafif": 1}, U_max=0, W_max=0)],
        team_types=[TeamType(k="hafif", name="Hafif", A=1, p=1.0)],
        sites=[Site(i="I1", name="I1", m=m)],
        scenarios=[
            Scenario(
                s="s1",
                name="Tek",
                P=1.0,
                D={"I1": periods_demand},
                beta={"I1": beta},
                beta_t=beta_t,
            )
        ],
        tau={("J1", "I1"): tau},
        N_max=1,
        U_top=0,
        W_top=0,
        L=2.0,
    )


def _solve(instance, periods):
    return solve_team_chains(instance, solver=SOLVER, periods=periods)


def test_sey_and_h_use_the_departure_period():
    """(4.1) ve (4.26). Varış periyodunun β'si süreyi yeniden yazmaz."""

    beta_t = {("I1", 1): 0.0, ("I1", 2): 0.5}
    instance = _instance(1.5, beta=0.5, beta_t=beta_t)
    scenario = instance.scenarios[0]
    assert travel_sey(instance, "J1", "I1", 1, scenario) == pytest.approx(1.5)
    assert travel_sey(instance, "I1", "J1", 1, scenario) == pytest.approx(1.5)
    assert travel_sey(instance, "I1", "J1", 2, scenario) == pytest.approx(2.25)
    assert route_h(instance, "I1", "J1", 1, scenario) == 1
    assert route_h(instance, "I1", "J1", 2, scenario) == 0

    solution = _solve(instance, periods=4)
    assert solution.status == "Optimal"
    assert not chain_violations(instance, solution)
    trip = solution.crossings[0]
    assert trip.departure_period == 1
    assert trip.arrival_period == 2
    assert trip.beta == pytest.approx(0.0)
    assert trip.sey == pytest.approx(1.5)
    assert trip.arrive_h == pytest.approx(trip.depart_h + trip.sey)
    assert abs((trip.arrive_h - trip.depart_h) - 2.25) > 0.2


def test_cross_period_trip_keeps_one_duration_and_blocks_the_team():
    """Elle: 0'da çıkış, 1.5'te enkaz, 1.5'te dönüş, 3.0'da merkez. Periyot 1→2."""

    instance = _instance(1.5)
    solution = _solve(instance, periods=4)
    assert solution.status == "Optimal"
    assert solution.objective == pytest.approx(0.0)
    assert not chain_violations(instance, solution)
    assert solution.chains[("hafif-1", "s1")] == ["σ", "o_J1", "(I1,1)", "(J1,2,1)", "ω"]
    trip = solution.crossings[0]
    assert trip.origin == "(I1,1)"
    assert trip.dest == "(J1,2,1)"
    assert trip.departure_period == 1
    assert trip.arrival_period == 2
    assert trip.depart_h == pytest.approx(1.5)
    assert trip.sey == pytest.approx(1.5)
    assert trip.arrive_h == pytest.approx(3.0)
    # Dönüş periyot 1'in sonunda havada. Stok ancak varış periyodunda geri gelir.
    assert solution.inventory[("J1", "hafif", 0, "s1")] == 1
    assert solution.inventory[("J1", "hafif", 1, "s1")] == 0
    assert solution.inventory[("J1", "hafif", 2, "s1")] == 1
    clock = {label: (bas, bit) for label, bas, bit in solution.clock[("hafif-1", "s1")]}
    assert clock["(I1,1)"][1] <= trip.depart_h + 1e-6
    assert clock["(J1,2,1)"][0] >= trip.arrive_h - 1e-6


def test_horizon_return_is_kept_and_not_added_to_inventory():
    """(4.32)–(4.33) ve 5.3.2. Dönüş 2 saati aşar; kayıt H'dedir, stoka girmez."""

    instance = _instance(1.5)
    solution = _solve(instance, periods=1)
    assert solution.status == "Optimal"
    assert not chain_violations(instance, solution)
    assert solution.chains[("hafif-1", "s1")] == ["σ", "o_J1", "(I1,1)", "ω^yol_J1", "ω"]
    trip = solution.crossings[0]
    assert trip.horizon
    assert trip.sey == pytest.approx(1.5)
    assert trip.arrive_h == pytest.approx(solution.horizon)
    assert trip.depart_h + trip.sey == pytest.approx(3.5)
    assert trip.depart_h + trip.sey > solution.horizon
    assert solution.inventory[("J1", "hafif", 0, "s1")] == 1
    assert solution.inventory[("J1", "hafif", 1, "s1")] == 0


def test_time_makes_a_two_cycle_infeasible():
    """Graf aynı periyotta gidilip dönülebilir. (4.29)–(4.30) bu çevrimi keser."""

    instance = _instance(0.5)
    network = build_network(instance, 1)
    forward = network.by_arc["s1"][("c_J1_t1_l1", "d_I1_t1")]
    backward = network.by_arc["s1"][("d_I1_t1", "c_J1_t1_l1")]
    assert forward.kind == "travel" and backward.kind == "travel"
    problem, bundle, _primary = _build(instance, network, reentry_ban=True)
    team = bundle["teams"][0].r
    y = bundle["Y"]
    problem += y[(team, "sigma", "omega", "s1")] == 1
    problem += y[(team, forward.u.key, forward.v.key, "s1")] == 1
    problem += y[(team, backward.u.key, backward.v.key, "s1")] == 1
    status = pulp.LpStatus[problem.solve(pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1))]
    assert status == "Infeasible"


def test_thirty_six_periods_solve_a_tiny_case():
    instance = _instance(0.5)
    solution = _solve(instance, periods=36)
    assert solution.status == "Optimal"
    assert solution.periods == 36
    assert solution.horizon == 72
    assert solution.objective == pytest.approx(0.0)
    assert not chain_violations(instance, solution)
    assert solution.chains[("hafif-1", "s1")][0] == "σ"
    assert solution.chains[("hafif-1", "s1")][-1] == "ω"
    assert any(label.startswith("(I1,") for label in solution.chains[("hafif-1", "s1")])
