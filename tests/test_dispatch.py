"""4.9 sevk kuralı. Elle yazılmış noktalar."""

from __future__ import annotations

from model.dispatch import dispatch_target
from model.instance import Center, Instance, Scenario, Site, TeamType
from model.staff import Resource


def _world() -> tuple[Instance, object]:
    instance = Instance(
        centers=[
            Center(j="J1", name="J1", C={"hafif": 1, "agir": 1}, U_max=1, W_max=0),
            Center(j="J2", name="J2", C={"hafif": 1, "agir": 1}, U_max=1, W_max=0),
        ],
        team_types=[
            TeamType(k="hafif", name="Hafif", A=1, p=1.0),
            TeamType(k="agir", name="Ağır", A=1, p=1.0),
        ],
        sites=[
            Site(i="I1", name="I1", m=4.0, E=1, damage="Ağır", gamma=3, m_U=1.2, m_W=2.0),
            Site(i="I4", name="I4", m=1.5, E=0, damage="Hafif", gamma=1, m_U=0.45, m_W=0.0),
        ],
        scenarios=[Scenario(s="s1", name="s1", P=1.0, D=None, beta={"I1": 0.0, "I4": 0.0})],
        tau={
            ("J1", "I1"): 0.4,
            ("J1", "I4"): 1.2,
            ("J2", "I1"): 1.2,
            ("J2", "I4"): 0.4,
            ("I1", "I4"): 0.8,
            ("I4", "I1"): 0.8,
        },
        N_max=2,
        U_top=1,
        W_top=0,
        L=2.0,
        a={("I1", "hafif"): 0, ("I1", "agir"): 1, ("I4", "hafif"): 1, ("I4", "agir"): 1},
    )
    return instance, instance.scenarios[0]


def test_light_team_skips_the_near_heavy_site():
    instance, scenario = _world()
    light = Resource(r="hafif-1", group="A", p=1.0, k="hafif")
    target = dispatch_target(
        instance,
        light,
        scenario,
        t=1,
        origin="J1",
        open_centers={"J1", "J2"},
        remaining={("A", "I1"): 4.0, ("A", "I4"): 1.5},
        left_sites=set(),
    )
    assert target == "I4"


def test_umke_waits_for_eta_then_takes_the_ready_site():
    instance, scenario = _world()
    umke = Resource(r="umke-1", group="U", p=1.0)
    blocked = dispatch_target(
        instance,
        umke,
        scenario,
        t=1,
        origin="J1",
        open_centers={"J1"},
        remaining={("A", "I1"): 4.0, ("U", "I1"): 1.2, ("A", "I4"): 1.5, ("U", "I4"): 0.45},
        left_sites=set(),
    )
    assert blocked == "J1"
    ready = dispatch_target(
        instance,
        umke,
        scenario,
        t=1,
        origin="J1",
        open_centers={"J1", "J2"},
        remaining={("A", "I1"): 3.7, ("U", "I1"): 1.2, ("A", "I4"): 1.5, ("U", "I4"): 0.0},
        left_sites=set(),
    )
    assert ready == "I1"


def test_left_site_is_skipped_and_closed_center_is_not_a_refuge():
    instance, scenario = _world()
    heavy = Resource(r="agir-1", group="A", p=1.0, k="agir")
    target = dispatch_target(
        instance,
        heavy,
        scenario,
        t=1,
        origin="I4",
        open_centers={"J2"},
        remaining={("A", "I1"): 4.0, ("A", "I4"): 0.0},
        left_sites={"I1"},
    )
    assert target == "J2"
