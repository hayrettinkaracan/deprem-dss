"""En yakın açık merkeze dönüş (4.28). Küçük örnek; uzun 5.3 koşusu yok."""

from __future__ import annotations

from data.section_5_3 import section_5_3
from model.instance import Center, Instance, Scenario, Site, TeamType
from model.planning import nearer_centers, solve_planning


def _two_centers() -> Instance:
    return Instance(
        centers=[
            Center(j="J1", name="J1", C={"agir": 1}, U_max=0, W_max=0),
            Center(j="J2", name="J2", C={"agir": 1}, U_max=0, W_max=0),
        ],
        team_types=[TeamType(k="agir", name="Ağır", A=1, p=1.0)],
        sites=[
            Site(i="I1", name="I1", m=1.0, E=0, damage="Ağır", gamma=3.0, m_U=0.0, m_W=0.0),
            Site(i="I3", name="I3", m=1.0, E=0, damage="Orta", gamma=2.0, m_U=0.0, m_W=0.0),
        ],
        scenarios=[Scenario(s="s1", name="Tek", P=1.0, D=None, beta={"I1": 0.0, "I3": 0.0})],
        tau={
            ("J1", "I1"): 0.8,
            ("J2", "I1"): 1.2,
            ("J1", "I3"): 1.2,
            ("J2", "I3"): 0.5,
        },
        N_max=2,
        U_top=0,
        W_top=0,
        L=2.0,
        a={("I1", "agir"): 1, ("I3", "agir"): 1},
    )


def test_i1_prefers_j1_and_i3_prefers_j2():
    instance = section_5_3()
    scenario = instance.scenarios[0]
    assert nearer_centers(instance, scenario, "I1", "J2", 1) == ["J1"]
    assert nearer_centers(instance, scenario, "I1", "J1", 1) == []
    assert nearer_centers(instance, scenario, "I3", "J1", 1) == ["J2"]
    assert nearer_centers(instance, scenario, "I3", "J2", 1) == []


def test_both_centers_open_blocks_the_far_return():
    instance = _two_centers()
    solution = solve_planning(
        instance,
        periods=2,
        time_limit=15,
        threads=1,
        mode="z1",
        fix_centers={"J1": 1, "J2": 1},
    )
    assert solution.status == "Optimal"
    assert solution.G == {"J1": 1, "J2": 1}
    for (team, scenario), pairs in solution.arcs.items():
        for tail, head in pairs:
            if "I1" in tail and head.startswith("c_J2"):
                raise AssertionError(f"{team} {scenario} I1 dönüşü J2'ye gitti")
            if "I3" in tail and head.startswith("c_J1"):
                raise AssertionError(f"{team} {scenario} I3 dönüşü J1'e gitti")
