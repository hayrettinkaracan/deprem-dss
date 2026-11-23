"""Operasyonel atamanın eski hedef ve β tanımını koruduğunu kilitler."""

from model.legacy_assignment import solve_team_to_site


def test_single_team_goes_to_larger_demand_and_beta_halves_capacity():
    teams = [{"id": 1, "kapasite": 10}]
    sites = [{"id": 1, "talep": 4}, {"id": 2, "talep": 100}]

    optimistic = solve_team_to_site(teams, sites, beta=0.0)
    assert optimistic.status == "Optimal"
    assert [(item.ekip_id, item.enkaz_id) for item in optimistic.assignments] == [(1, 2)]
    assert optimistic.objective == 94.0
    assert optimistic.unmet[2] == 90.0
    assert optimistic.unmet[1] == 4.0

    pessimistic = solve_team_to_site(teams, sites, beta=1.0)
    assert pessimistic.status == "Optimal"
    assert [(item.ekip_id, item.enkaz_id) for item in pessimistic.assignments] == [(1, 2)]
    assert pessimistic.assignments[0].etkin_kapasite == 5.0
    assert pessimistic.objective == 99.0
    assert pessimistic.unmet[2] == 95.0


def test_team_is_assigned_to_at_most_one_site():
    teams = [{"id": 1, "kapasite": 10}, {"id": 2, "kapasite": 10}]
    sites = [{"id": 5, "talep": 100}, {"id": 6, "talep": 3}]
    result = solve_team_to_site(teams, sites, beta=0.0)
    assert result.status == "Optimal"
    used = [item.ekip_id for item in result.assignments]
    assert len(used) == len(set(used))
    assert {item.enkaz_id for item in result.assignments} == {5}
    assert result.objective == 83.0
