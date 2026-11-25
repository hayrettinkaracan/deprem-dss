"""5.3 planlama kadrosu. Çözücü yok."""

from __future__ import annotations

from data.section_5_3 import section_5_3
from model.staff import (
    GROUP_A,
    GROUP_G,
    GROUP_U,
    GROUP_W,
    PLANNING_PRODUCTIVITY,
    Resource,
    can_serve,
    group_load,
    planning_staff,
)


def test_planning_roster_is_nine_teams_and_volunteers_are_absent():
    staff = planning_staff(section_5_3())
    assert [resource.r for resource in staff.of(GROUP_A)] == [
        "hafif-1",
        "orta-1",
        "orta-2",
        "agir-1",
    ]
    assert [resource.k for resource in staff.of(GROUP_A)] == ["hafif", "orta", "orta", "agir"]
    assert [resource.r for resource in staff.of(GROUP_U)] == ["umke-1", "umke-2", "umke-3"]
    assert [resource.r for resource in staff.of(GROUP_W)] == ["makine-1", "makine-2"]
    assert staff.of(GROUP_G) == ()
    assert len(staff.resources) == 9
    assert len({resource.r for resource in staff.resources}) == 9
    assert all(resource.p == PLANNING_PRODUCTIVITY == 1.0 for resource in staff.resources)


def test_grouped_work_and_gamma():
    instance = section_5_3()
    for site in instance.sites:
        assert group_load(site, GROUP_A) == site.m
        assert group_load(site, GROUP_U) == site.m_U
        assert group_load(site, GROUP_W) == site.m_W
        assert site.gamma == {"Ağır": 3, "Orta": 2, "Hafif": 1}[site.damage]
    assert group_load(instance.sites[2], GROUP_W) == 0.0
    assert group_load(instance.sites[3], GROUP_W) == 0.0


def test_access_rules():
    instance = section_5_3()
    staff = planning_staff(instance)
    by_id = {resource.r: resource for resource in staff.resources}
    sites = {site.i: site for site in instance.sites}
    light = by_id["hafif-1"]
    medium = by_id["orta-1"]
    heavy = by_id["agir-1"]
    umke = by_id["umke-1"]
    machine = by_id["makine-1"]
    volunteer = Resource(r="gonullu-1", group=GROUP_G, p=0.4)

    for site in instance.sites:
        assert can_serve(instance, light, site) is (site.i == "I4")
        assert can_serve(instance, umke, site) is True
        assert can_serve(instance, volunteer, site) is True
        assert can_serve(instance, machine, site) is (site.E == 1)
    assert can_serve(instance, medium, sites["I1"]) is False
    assert can_serve(instance, medium, sites["I5"]) is False
    assert can_serve(instance, medium, sites["I2"]) is True
    assert can_serve(instance, medium, sites["I4"]) is True
    assert can_serve(instance, heavy, sites["I1"]) is True
    assert can_serve(instance, heavy, sites["I4"]) is True
    assert can_serve(instance, machine, sites["I3"]) is False
    assert can_serve(instance, machine, sites["I4"]) is False
    assert can_serve(instance, machine, sites["I1"]) is True
