"""Yeni planlama grafı, hipotetik τ ve (4.29)–(4.33)."""

from __future__ import annotations

import pytest

from data.section_5_3 import (
    HYPOTHETICAL_TAU_LABEL,
    hypothetical_site_tau,
    section_5_3,
    triangle_bounds,
)
from model.network import route_h, travel_sey
from model.planning_network import build_planning_network, has_time
from model.staff import planning_staff

# Orta nokta, 0,1 saate, tam yarıda yukarı. Elle.
SITE_TAU = {
    ("I1", "I2"): 0.8,
    ("I1", "I3"): 1.2,
    ("I1", "I4"): 1.3,
    ("I1", "I5"): 1.3,
    ("I2", "I3"): 1.1,
    ("I2", "I4"): 1.3,
    ("I2", "I5"): 1.3,
    ("I3", "I4"): 0.8,
    ("I3", "I5"): 1.0,
    ("I4", "I5"): 1.0,
}


def test_hypothetical_tau_is_labelled_symmetric_and_inside_the_triangle():
    instance = section_5_3()
    assert HYPOTHETICAL_TAU_LABEL == "HYK onayıyla üretilmiş hipotetik veri"
    centers = [center.j for center in instance.centers]
    sites = [site.i for site in instance.sites]
    center_tau = {(center, site): instance.tau[(center, site)] for center in centers for site in sites}
    generated = hypothetical_site_tau(center_tau, sites, centers)
    for (left, right), expected in SITE_TAU.items():
        lower, upper = triangle_bounds(center_tau, centers, left, right)
        assert lower <= expected <= upper
        assert instance.tau[(left, right)] == pytest.approx(expected)
        assert instance.tau[(right, left)] == pytest.approx(expected)
        assert generated[(left, right)] == pytest.approx(expected)
    # I1–I4 orta noktası 1,25'tir; yarıda yukarı 1,3 olur.
    lower, upper = triangle_bounds(center_tau, centers, "I1", "I4")
    assert (lower + upper) / 2 == pytest.approx(1.25)
    assert instance.tau[("I1", "I4")] == pytest.approx(1.3)


def test_sey_uses_destination_beta_and_the_known_center_leg():
    instance = section_5_3()
    optimistic = instance.scenarios[0]
    expected = instance.scenarios[1]
    # Çizelge: I2–J1 = 0,5. s1 β = 0,10. Sey = 0,55.
    assert travel_sey(instance, "J1", "I2", 1, optimistic) == pytest.approx(0.55)
    assert travel_sey(instance, "I2", "J1", 1, optimistic) == pytest.approx(0.55)
    # Hedef I5, s2 β = 0,30. Karşı yön hedefin β'si 0,15.
    assert travel_sey(instance, "I2", "I5", 1, expected) == pytest.approx(1.3 * 1.30)
    assert travel_sey(instance, "I5", "I2", 1, expected) == pytest.approx(1.3 * 1.15)
    for scenario in instance.scenarios:
        for left, right in SITE_TAU:
            assert route_h(instance, left, right, 1, scenario) == 1
            assert route_h(instance, right, left, 18, scenario) == 1


def test_planning_graph_filters_teams_and_drops_global_m():
    instance = section_5_3()
    staff = planning_staff(instance)
    network = build_planning_network(instance, periods=2, staff=staff)
    assert not hasattr(network, "big_m")
    assert network.horizon == 4
    timed = {visit.key for visit in network.timed()}
    for visit in network.visits:
        if visit.kind == "enroute":
            assert visit.key not in timed
            assert has_time(visit) is False
        elif visit.kind in {"origin", "debris", "center"}:
            assert has_time(visit) is True

    centers = {center.j for center in instance.centers}
    for scenario in instance.scenarios:
        for resource in staff.resources:
            for arc in network.team_arcs[scenario.s][resource.r]:
                ends = {arc.u.physical(), arc.v.physical()}
                assert ends != centers
                if arc.kind == "travel":
                    start = arc.u.period()
                    end = arc.v.period()
                    assert start is not None and end is not None
                    assert end in {start, start + 1}
                    assert arc.m_uv == pytest.approx(
                        instance.L * (start - end + 1) + arc.sey
                    )
                    assert route_h(
                        instance, arc.u.physical(), arc.v.physical(), arc.departure_t, scenario
                    ) == 1
                if arc.kind in {"continue", "wait"}:
                    assert arc.sey == 0
                    assert arc.m_uv == 0
                if arc.kind == "enroute":
                    assert arc.u.t == network.periods
                    assert arc.m_uv is None
                    assert arc.v.kind == "enroute"
                if arc.v.kind == "debris" and resource.r == "hafif-1":
                    assert arc.v.i == "I4"
                if arc.v.kind == "debris" and resource.group == "W":
                    assert arc.v.i not in {"I3", "I4"}

        umke = network.team_arcs[scenario.s]["umke-1"]
        entered = {arc.v.i for arc in umke if arc.v.kind == "debris"}
        assert entered == {"I1", "I2", "I3", "I4", "I5"}
        site_site = [
            arc
            for arc in umke
            if arc.kind == "travel" and arc.u.kind == "debris" and arc.v.kind == "debris"
        ]
        assert site_site
        sample = next(arc for arc in site_site if arc.u.i == "I2" and arc.v.i == "I5" and arc.v.t == 1)
        assert sample.sey == pytest.approx(travel_sey(instance, "I2", "I5", 1, scenario))
