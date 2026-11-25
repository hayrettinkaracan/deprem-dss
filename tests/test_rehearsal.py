"""Saat provası. Tablo kilitli; çözücü yalnız bir periyot ve 15 saniye."""

from __future__ import annotations

from data.rehearsal import LABEL, entry_period, generate_rehearsal, triangle_bounds
from data.section_5_3 import section_5_3
from scripts.run_5_3 import main


def test_events_enter_next_period_and_keep_the_triangle():
    instance = section_5_3()
    events = generate_rehearsal(instance)
    assert [event.hour for event in events] == [1, 3, 5, 7, 9, 11]
    assert [event.entry_period for event in events] == [2, 3, 4, 5, 6, 7]
    assert [event.theta for event in events] == [2, 4, 6, 8, 10, 12]
    assert all(event.label == LABEL for event in events)
    centers = [center.j for center in instance.centers]
    known = {site.i: {center.j: instance.tau[(center.j, site.i)] for center in instance.centers} for site in instance.sites}
    for event in events:
        assert event.volunteer_center in {"J1", "J2"}
        assert 0.2 <= event.volunteer_p <= 0.6
        assert event.E == (1 if event.damage == "Ağır" else 0)
        assert event.gamma == {"Ağır": 3, "Orta": 2, "Hafif": 1}[event.damage]
        for site_i, distance in event.tau_site.items():
            merged = { (center, site_i): known[site_i][center] for center in centers }
            for center, value in event.tau_center.items():
                merged[(center, "NEW")] = value
            lower, upper = triangle_bounds(merged, centers, site_i, "NEW")
            assert lower - 1e-9 <= distance <= upper + 1e-9
        known[event.site_id] = dict(event.tau_center)
    first = events[0]
    assert (first.site_id, first.damage, first.tau_center["J1"], first.tau_center["J2"], first.volunteer_center) == (
        "I6",
        "Hafif",
        0.8,
        1.0,
        "J1",
    )
    assert abs(first.volunteer_p - 0.3437) < 5e-4
    last = events[-1]
    assert (last.site_id, last.damage, last.E, last.m_W, last.volunteer_center) == ("I11", "Ağır", 1, 2.0, "J2")
    assert entry_period(1) == 2 and entry_period(11) == 7


def test_rehearsal_cli_runs_one_short_period(tmp_path):
    out = tmp_path / "prova.md"
    main(
        [
            "--mode",
            "rehearsal",
            "--time-limit",
            "15",
            "--threads",
            "1",
            "--periods",
            "2",
            "--max-events",
            "1",
            "--out",
            str(out),
        ]
    )
    text = out.read_text(encoding="utf-8")
    assert LABEL in text
    assert "I6" in text
    assert "durum" in text
