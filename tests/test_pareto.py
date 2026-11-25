"""Z2 ve ε taraması, küçük örnek. 5.3'ün 36 periyodu burada çözülmez."""

from __future__ import annotations

import pytest

from model.instance import Center, Instance, Scenario, Site, TeamType
from model.opening_cost import calibrate_opening_cost
from model.pareto import pareto_sweep
from model.planning import solve_planning


def _tiny() -> Instance:
    return Instance(
        centers=[
            Center(j="J1", name="J1", C={"hafif": 1}, U_max=0, W_max=0),
            Center(j="J2", name="J2", C={"hafif": 1}, U_max=0, W_max=0),
        ],
        team_types=[TeamType(k="hafif", name="Hafif", A=1, p=1.0)],
        sites=[Site(i="I1", name="I1", m=1.0, E=0, damage="Hafif", gamma=1.0, m_U=0.0, m_W=0.0)],
        scenarios=[Scenario(s="s1", name="Tek", P=1.0, D=None, beta={"I1": 0.0})],
        tau={("J1", "I1"): 0.4, ("J2", "I1"): 0.8},
        N_max=2,
        U_top=0,
        W_top=0,
        L=2.0,
        a={("I1", "hafif"): 1},
    )


def test_opening_one_center_costs_its_calibrated_f():
    instance = _tiny()
    cost = calibrate_opening_cost(instance)
    solution = solve_planning(instance, periods=1, time_limit=10, mode="z2", min_centers=1, threads=1)
    assert solution.status == "Optimal"
    assert solution.z2 == pytest.approx(min(cost.f_j.values()))
    assert sum(solution.G.values()) == 1
    opened = next(name for name, flag in solution.G.items() if flag)
    assert solution.z2 == pytest.approx(cost.f_j[opened])


def test_pareto_sweep_on_a_tiny_instance_respects_epsilon():
    sweep = pareto_sweep(_tiny(), periods=2, time_limit=8, threads=1, points=5)
    assert sweep.z1 is not None
    assert sweep.z_bar_2 is not None and sweep.z_bar_2 > 0
    assert sweep.z_low_2 is not None
    assert sweep.delta == pytest.approx(1e-3 / sweep.z_bar_2)
    assert len(sweep.points) == 5
    epsilons = [point.epsilon for point in sweep.points]
    assert epsilons == sorted(epsilons)
    assert epsilons[0] == pytest.approx(min(sweep.z_low_2, sweep.z_bar_2))
    assert epsilons[-1] == pytest.approx(max(sweep.z_low_2, sweep.z_bar_2))
    for point in sweep.points:
        if point.status == "Optimal" and point.z2 is not None:
            assert point.z2 <= point.epsilon + 1e-3
