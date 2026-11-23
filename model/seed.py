"""CBC için uygun bir başlangıç çözümü.

Bu dosya kısıt veya amaç eklemez. Raporun modeli aynı kalır. Başlangıç,
açık güzergâhlarda erken hareket eden bir turdur; çözücü onu iyileştirebilir
veya aynı maliyette bırakabilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from model.instance import Instance
from model.network import Arc, Network, time_window

TOL = 1e-8


@dataclass
class Seed:
    assignment: dict[str, str | None]
    arcs: dict[tuple[str, str], list[Arc]] = field(default_factory=dict)
    bas: dict[tuple[str, str, str], float] = field(default_factory=dict)
    bit: dict[tuple[str, str, str], float] = field(default_factory=dict)
    unmet: dict[tuple[str, str], float] = field(default_factory=dict)
    objective: float = 0.0


def build_seed(instance: Instance, network: Network) -> Seed:
    """Eşitlikleri sağlayan bir tur. En iyi karşılanmayan talep, sonra küçük V."""

    from model.routing import roster

    teams = roster(instance)
    best: tuple[float, float, Seed] | None = None
    centers = [center.j for center in instance.centers]
    choices = [None, *centers]
    for picks in product(choices, repeat=len(teams)):
        assignment = {team.r: center for team, center in zip(teams, picks)}
        if not _placement_ok(instance, teams, assignment):
            continue
        seed = _simulate(instance, network, teams, assignment)
        rank = (seed.objective, _weight(instance, teams, assignment))
        if best is None or rank < best[0:2]:
            best = (rank[0], rank[1], seed)
    if best is None:
        return _simulate(instance, network, teams, {team.r: None for team in teams})
    return best[2]


def apply_seed(problem, bundle: dict, seed: Seed, instance: Instance, network: Network) -> None:
    """Değişkenlere başlangıç değeri yazar. warmStart bunu CBC'ye iletir."""

    teams: list[Team] = bundle["teams"]
    values: dict[str, float] = {}
    for center, var in bundle["G"].items():
        used = any(seed.assignment.get(team.r) == center for team in teams)
        values[var.name] = 1.0 if used else 0.0
    counts: dict[tuple[str, str], int] = {}
    for team in teams:
        center = seed.assignment.get(team.r)
        if center is not None:
            counts[(center, team.k)] = counts.get((center, team.k), 0) + 1
    for (center, kind), var in bundle["V"].items():
        values[var.name] = float(counts.get((center, kind), 0))
    for var in bundle["VU"].values():
        values[var.name] = 0.0
    for var in bundle["VW"].values():
        values[var.name] = 0.0
    chosen = {
        (team.r, scenario_s, arc.u.key, arc.v.key)
        for (team_r, scenario_s), arcs in seed.arcs.items()
        for arc in arcs
        for team in teams
        if team.r == team_r
    }
    for (team_r, u_key, v_key, scenario_s), var in bundle["Y"].items():
        values[var.name] = 1.0 if (team_r, scenario_s, u_key, v_key) in chosen else 0.0
    for key, var in bundle["bas"].items():
        values[var.name] = float(seed.bas.get(key, 0.0))
    for key, var in bundle["bit"].items():
        values[var.name] = float(seed.bit.get(key, 0.0))
    for key, var in bundle["u"].items():
        values[var.name] = float(seed.unmet.get(key, 0.0))
    _flow_values(instance, network, teams, seed, values, bundle)
    for var in problem.variables():
        if var.name in values:
            var.setInitialValue(values[var.name])


def _flow_values(instance, network: Network, teams, seed: Seed, values: dict, bundle) -> None:
    """(4.36) ve (4.38) başlangıcı, seçilen yaylarla aynı sayımı kullanır."""

    chosen = {
        (team.r, scenario.s): {(arc.u.key, arc.v.key) for arc in seed.arcs.get((team.r, scenario.s), [])}
        for team in teams
        for scenario in instance.scenarios
    }
    teams_of = {spec.k: [team for team in teams if team.k == spec.k] for spec in instance.team_types}
    for scenario in instance.scenarios:
        for (n, n2, t_dep), arc_list in network.har[scenario.s].items():
            for spec in instance.team_types:
                count = sum(
                    1
                    for arc in arc_list
                    for team in teams_of[spec.k]
                    if (arc.u.key, arc.v.key) in chosen[(team.r, scenario.s)]
                )
                name = f"f_{spec.k}_{n}_{n2}_t{t_dep}_{scenario.s}"
                values[name] = float(count)
        for center in instance.centers:
            for spec in instance.team_types:
                placed = int(values.get(bundle["V"][(center.j, spec.k)].name, 0))
                values[f"I_{spec.k}_{center.j}_t0_{scenario.s}"] = float(placed)
                for t_now in range(1, network.periods + 1):
                    arrived = sum(
                        1
                        for ell in range(1, t_now + 1)
                        for arc in network.arrivals[scenario.s].get((center.j, ell), [])
                        for team in teams_of[spec.k]
                        if (arc.u.key, arc.v.key) in chosen[(team.r, scenario.s)]
                    )
                    left = sum(
                        1
                        for site in instance.sites
                        for ell in range(1, t_now + 1)
                        for arc in network.har[scenario.s].get((center.j, site.i, ell), [])
                        for team in teams_of[spec.k]
                        if (arc.u.key, arc.v.key) in chosen[(team.r, scenario.s)]
                    )
                    values[f"I_{spec.k}_{center.j}_t{t_now}_{scenario.s}"] = float(placed + arrived - left)


def _placement_ok(instance: Instance, teams, assignment: dict[str, str | None]) -> bool:
    opened = {center for center in assignment.values() if center is not None}
    if len(opened) > instance.N_max:
        return False
    counts: dict[tuple[str, str], int] = {}
    for team in teams:
        center = assignment[team.r]
        if center is None:
            continue
        counts[(center, team.k)] = counts.get((center, team.k), 0) + 1
    caps = {center.j: center.C for center in instance.centers}
    for (center, kind), count in counts.items():
        if count > caps[center][kind]:
            return False
    return True


def _weight(instance: Instance, teams, assignment: dict[str, str | None]) -> float:
    j_index = {center.j: index for index, center in enumerate(instance.centers)}
    k_index = {spec.k: index for index, spec in enumerate(instance.team_types)}
    type_count = max(len(instance.team_types), 1)
    opened = {center for center in assignment.values() if center is not None}
    weight = float(sum(j_index[center] + 1 for center in opened))
    counts: dict[tuple[str, str], int] = {}
    for team in teams:
        center = assignment[team.r]
        if center is not None:
            counts[(center, team.k)] = counts.get((center, team.k), 0) + 1
    for (center, kind), count in counts.items():
        weight += count * (8 ** (j_index[center] * type_count + k_index[kind]))
    return weight


def _simulate(
    instance: Instance,
    network: Network,
    teams,
    assignment: dict[str, str | None],
) -> Seed:
    from model.routing import _tight_unmet
    outgoing: dict[str, dict[str, list[Arc]]] = {}
    for scenario in instance.scenarios:
        bucket: dict[str, list[Arc]] = {}
        for arc in network.arcs[scenario.s]:
            bucket.setdefault(arc.u.key, []).append(arc)
        outgoing[scenario.s] = bucket
    seed = Seed(assignment=dict(assignment))
    entries = {
        (team.r, site.i, scenario.s): 0
        for team in teams
        for site in instance.sites
        for scenario in instance.scenarios
    }
    for scenario in instance.scenarios:
        arcs_from = outgoing[scenario.s]
        for team in teams:
            center = assignment[team.r]
            taken, times, visited = _tour(
                instance, network, arcs_from, team.r, team.k, center, scenario.s
            )
            seed.arcs[(team.r, scenario.s)] = taken
            for key, (bas, bit) in times.items():
                seed.bas[(team.r, key, scenario.s)] = bas
                seed.bit[(team.r, key, scenario.s)] = bit
            for site_i in visited:
                entries[(team.r, site_i, scenario.s)] = 1
    seed.unmet = _tight_unmet(instance, teams, entries)
    seed.objective = sum(
        scenario.P * seed.unmet[(site.i, scenario.s)]
        for scenario in instance.scenarios
        for site in instance.sites
    )
    return seed


def _tour(instance, network: Network, arcs_from, team_r: str, team_k: str, center: str | None, scenario_s: str):
    if center is None:
        omega = next(arc for arc in arcs_from["sigma"] if arc.v.kind == "omega")
        return [omega], {}, []
    origin_key = f"o_{center}"
    start = next(arc for arc in arcs_from["sigma"] if arc.v.key == origin_key)
    times = {origin_key: (0.0, 0.0)}
    used = {origin_key}
    taken = [start]
    current = origin_key
    bas_here = 0.0
    visited: list[str] = []
    length = instance.L
    horizon = network.horizon

    while len(visited) < len(instance.sites):
        hop = _best_site(
            instance,
            team_k,
            arcs_from.get(current, []),
            used,
            visited,
            bas_here,
            length,
        )
        if hop is None:
            break
        bit, arc, arrive = hop
        times[current] = (times[current][0], bit)
        times[arc.v.key] = (arrive, arrive)
        used.add(arc.v.key)
        taken.append(arc)
        visited.append(arc.v.i)
        current = arc.v.key
        bas_here = arrive
        back = _best_return(
            arcs_from.get(current, []),
            times,
            used,
            bas_here,
            length,
            horizon,
            center,
        )
        if back is None:
            break
        bit, arc, arrive = back
        times[current] = (times[current][0], bit)
        if arc.kind == "enroute":
            times[arc.v.key] = (horizon, horizon)
            taken.append(arc)
            current = arc.v.key
            bas_here = horizon
            break
        times[arc.v.key] = (arrive, arrive)
        used.add(arc.v.key)
        taken.append(arc)
        current = arc.v.key
        bas_here = arrive

    end = _end_arc(arcs_from.get(current, []), times, bas_here, length, horizon)
    if end is None:
        back = _best_return(
            arcs_from.get(current, []),
            times,
            used,
            bas_here,
            length,
            horizon,
            center,
        )
        if back is not None:
            bit, arc, arrive = back
            times[current] = (times[current][0], bit)
            if arc.kind == "enroute":
                times[arc.v.key] = (horizon, horizon)
            else:
                times[arc.v.key] = (arrive, arrive)
            taken.append(arc)
            current = arc.v.key
            bas_here = horizon if arc.kind == "enroute" else arrive
        end = _end_arc(arcs_from.get(current, []), times, bas_here, length, horizon)
    if end is not None:
        if end.u.kind == "debris":
            times[current] = (times[current][0], horizon)
        taken.append(end)
    return taken, times, visited


def _best_site(instance, team_k, arcs, used, visited, bas_here, length):
    from model.instance import competency

    best = None
    current = arcs[0].u if arcs else None
    if current is None:
        return None
    for arc in arcs:
        if arc.kind != "travel" or arc.v.kind != "debris":
            continue
        if arc.v.i in visited or arc.v.key in used:
            continue
        if competency(instance, arc.v.i, team_k) == 0:
            continue
        slot = _departure(current, bas_here, arc, length, None)
        if slot is None:
            continue
        bit, arrive = slot
        rank = (arc.v.i, arrive, arc.v.t, arc.v.ell, bit)
        if best is None or rank < best[0]:
            best = (rank, bit, arc, arrive)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _best_return(arcs, times, used, bas_here, length, horizon, home: str):
    best = None
    current = arcs[0].u if arcs else None
    if current is None or current.kind != "debris":
        return None
    for arc in arcs:
        if arc.kind == "travel" and arc.v.kind == "center" and arc.v.key not in used:
            slot = _departure(current, bas_here, arc, length, None)
            if slot is None:
                continue
            bit, arrive = slot
            rank = (0 if arc.v.j == home else 1, arc.v.t, arc.v.ell, arrive)
            if best is None or rank < best[0]:
                best = (rank, bit, arc, arrive)
        elif arc.kind == "enroute":
            slot = _departure(current, bas_here, arc, length, horizon)
            if slot is None:
                continue
            bit, _arrive = slot
            rank = (2, horizon, 0, horizon)
            if best is None or rank < best[0]:
                best = (rank, bit, arc, horizon)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _end_arc(arcs, times, bas_here, length, horizon):
    for arc in arcs:
        if arc.v.kind != "omega" or arc.kind not in {"end", "enroute_end"}:
            continue
        if arc.u.kind == "debris":
            if bas_here <= horizon + TOL and _window_hi(arc.u, length) + TOL >= horizon:
                return arc
            continue
        return arc
    return None


def _departure(node, bas_here: float, arc: Arc, length: float, horizon: float | None):
    hi_u = _window_hi(node, length)
    if arc.kind == "enroute":
        if horizon is None:
            return None
        bit = max(bas_here, horizon - arc.sey)
        if bit <= hi_u + TOL and bit + arc.sey >= horizon - TOL:
            return bit, horizon
        return None
    window = time_window(arc.v, length)
    if window is None:
        return None
    lo_v, hi_v = window
    lo = max(bas_here, lo_v - arc.sey)
    hi = min(hi_u, hi_v - arc.sey)
    if lo <= hi + TOL:
        bit = lo
        return bit, bit + arc.sey
    return None


def _window_hi(node, length: float) -> float:
    window = time_window(node, length)
    if window is None:
        return 0.0
    return window[1]
