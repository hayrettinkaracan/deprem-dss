"""(4.18)–(4.33) ve (4.36)–(4.39) çözümün üzerinde yeniden sayılır.

İş hâlâ giriş başına L saattir. (4.34) bu kontrolde yoktur.
"""

from __future__ import annotations

from model.instance import Instance, competency
from model.network import (
    beta_at,
    build_network,
    is_site_entry,
    route_h,
    time_window,
    travel_sey,
)
from model.routing import TeamChainSolution, _tight_unmet, _trace

TOL = 1e-3


def chain_violations(instance: Instance, solution: TeamChainSolution) -> list[str]:
    problems: list[str] = []
    if solution.status != "Optimal":
        problems.append(f"durum Optimal değil: {solution.status}")
        return problems

    network = build_network(instance, solution.periods)
    _check_first_stage(instance, solution, problems)
    _check_chains(instance, solution, network, problems)
    _check_times(instance, solution, network, problems)
    _check_inventory(instance, solution, network, problems)
    _check_unmet(instance, solution, problems)
    return problems


def _check_first_stage(instance: Instance, solution: TeamChainSolution, problems: list[str]) -> None:
    opened = 0
    for center in instance.centers:
        opened += solution.G[center.j]
        if solution.G[center.j] not in (0, 1):
            problems.append(f"(4.51) G_{center.j}")
        for spec in instance.team_types:
            placed = solution.V[(center.j, spec.k)]
            if placed < 0 or placed > center.C[spec.k] * solution.G[center.j]:
                problems.append(f"(4.4) V_{center.j}_{spec.k}={placed}")
        if not 0 <= solution.VU[center.j] <= center.U_max * solution.G[center.j]:
            problems.append(f"(4.5) VU_{center.j}")
        if not 0 <= solution.VW[center.j] <= center.W_max * solution.G[center.j]:
            problems.append(f"(4.6) VW_{center.j}")
    if opened > instance.N_max:
        problems.append(f"(4.7) açık merkez {opened}")
    for spec in instance.team_types:
        fleet = sum(solution.V[(center.j, spec.k)] for center in instance.centers)
        if fleet > spec.A:
            problems.append(f"(4.8) {spec.k} filo {fleet}")
    if sum(solution.VU.values()) > instance.U_top:
        problems.append("(4.9) UMKE filosu")
    if sum(solution.VW.values()) > instance.W_top:
        problems.append("(4.10) iş makinesi filosu")
    expected_h = instance.L * solution.periods
    if abs(solution.horizon - expected_h) > TOL:
        problems.append(f"H={solution.horizon} != L|T|={expected_h}")


def _check_chains(instance: Instance, solution: TeamChainSolution, network, problems: list[str]) -> None:
    sigma = network.sigma.key
    omega = network.omega.key
    starts: dict[tuple[str, str], str | None] = {}
    for scenario in instance.scenarios:
        graph = network.by_arc[scenario.s]
        for team in solution.teams:
            pairs = solution.arcs.get((team.r, scenario.s), [])
            for tail, head in pairs:
                arc = graph.get((tail, head))
                if arc is None:
                    problems.append(f"izinli olmayan yay {team.r} {scenario.s} {tail}->{head}")
                    continue
                _check_arc_rule(instance, scenario, arc, network.periods, network.horizon, problems)
            keys = _trace(pairs)
            labels = solution.chains.get((team.r, scenario.s), [])
            if keys is None:
                problems.append(f"(4.18) {team.r} {scenario.s} tek σ–ω zinciri değil")
                starts[(team.r, scenario.s)] = None
                continue
            expected = [network.by_key[key].label for key in keys]
            if labels != expected:
                problems.append(f"zincir kaydı {team.r} {scenario.s}: {labels} != {expected}")
            if keys[0] != sigma or keys[-1] != omega:
                problems.append(f"(4.18) {team.r} {scenario.s} σ veya ω eksik")
            out_count: dict[str, int] = {}
            in_count: dict[str, int] = {}
            for tail, head in pairs:
                out_count[tail] = out_count.get(tail, 0) + 1
                in_count[head] = in_count.get(head, 0) + 1
            if out_count.get(sigma, 0) != 1 or in_count.get(sigma, 0) != 0:
                problems.append(f"(4.18) {team.r} {scenario.s} σ çıkışı {out_count.get(sigma, 0)}")
            if in_count.get(omega, 0) != 1 or out_count.get(omega, 0) != 0:
                problems.append(f"(4.19) {team.r} {scenario.s} ω girişi {in_count.get(omega, 0)}")
            for visit in network.visits:
                arrived = in_count.get(visit.key, 0)
                left = out_count.get(visit.key, 0)
                if arrived != left or arrived > 1:
                    problems.append(
                        f"(4.20) {team.r} {visit.key} {scenario.s} giriş {arrived} çıkış {left}"
                    )
            head = network.by_key[keys[1]]
            if head.kind == "omega":
                starts[(team.r, scenario.s)] = None
            elif head.kind == "origin":
                starts[(team.r, scenario.s)] = head.j
            else:
                problems.append(f"(4.18) {team.r} {scenario.s} σ sonrası {head.label}")
                starts[(team.r, scenario.s)] = None

            for site in instance.sites:
                count = sum(1 for tail, head_key in pairs if _entry(graph, tail, head_key, site.i))
                recorded = solution.entries[(team.r, site.i, scenario.s)]
                if count != recorded:
                    problems.append(
                        f"(4.23) kayıt {team.r} {site.i} {scenario.s}: {recorded} != {count}"
                    )
                if solution.reentry_ban and count > 1:
                    problems.append(f"(4.23) {team.r} {site.i} {scenario.s} giriş {count}")

    for scenario in instance.scenarios:
        for center in instance.centers:
            for spec in instance.team_types:
                total = sum(
                    1
                    for team in solution.teams
                    if team.k == spec.k and starts.get((team.r, scenario.s)) == center.j
                )
                if total != solution.V[(center.j, spec.k)]:
                    problems.append(
                        f"(4.21) {center.j} {spec.k} {scenario.s}: zincir {total} "
                        f"V {solution.V[(center.j, spec.k)]}"
                    )
        if scenario.s == solution.reference_scenario:
            continue
        for team in solution.teams:
            current = starts.get((team.r, scenario.s))
            reference = starts.get((team.r, solution.reference_scenario))
            if current != reference:
                problems.append(
                    f"(4.22) {team.r} {center_name(current)} != {center_name(reference)} ({scenario.s})"
                )


def _check_arc_rule(instance, scenario, arc, periods: int, horizon: float, problems: list[str]) -> None:
    if arc.kind == "travel":
        opened = route_h(
            instance,
            arc.u.physical() or "",
            arc.v.physical() or "",
            arc.departure_t or 1,
            scenario,
        )
        if opened != 1:
            problems.append(f"(4.28) h=0 yay {arc.u.label}->{arc.v.label} {scenario.s}")
        start = arc.u.period()
        end = arc.v.period()
        if start is None or end is None or end < start:
            problems.append(f"geçmiş periyot {arc.u.label}->{arc.v.label}")
        if arc.u.physical() == arc.v.physical():
            problems.append(f"aynı noktada gerçek hareket {arc.u.label}")
        debris_ends = (arc.u.kind == "debris") + (arc.v.kind == "debris")
        if debris_ends != 1:
            problems.append(f"(4.37) merkezler veya enkazlar arası {arc.u.label}->{arc.v.label}")
        sey = travel_sey(
            instance,
            arc.u.physical() or "",
            arc.v.physical() or "",
            arc.departure_t or 1,
            scenario,
        )
        if sey is None or abs(sey - arc.sey) > TOL:
            problems.append(f"(4.1) Sey {arc.u.label}->{arc.v.label} {arc.sey} != {sey}")
    if arc.kind == "enroute":
        opened = route_h(
            instance,
            arc.u.physical() or "",
            arc.v.j,
            arc.departure_t or 1,
            scenario,
        )
        if opened != 1:
            problems.append(f"(4.28) h=0 ω^yol {arc.u.label} {scenario.s}")
        sey = travel_sey(instance, arc.u.physical() or "", arc.v.j, arc.departure_t or 1, scenario)
        if sey is None or abs(sey - arc.sey) > TOL:
            problems.append(f"(4.1) ω^yol Sey {arc.sey} != {sey}")
        latest = instance.L * (arc.departure_t or 1) + arc.sey
        if latest + TOL < horizon:
            problems.append(f"(4.33) erken ω^yol {arc.u.label} {scenario.s}")
    if arc.kind in {"continue", "wait"} and abs(arc.sey) > TOL:
        problems.append(f"(4.1) sıfır seyir değil {arc.u.label}->{arc.v.label}")
    if arc.kind == "continue":
        if arc.u.i != arc.v.i or arc.v.t != arc.u.t + 1:
            problems.append(f"devam yayı bozuk {arc.u.label}->{arc.v.label}")
    if arc.kind == "end" and arc.u.kind == "debris" and arc.u.t != periods:
        problems.append(f"erken enkaz bitişi {arc.u.label}")


def _check_times(instance, solution: TeamChainSolution, network, problems: list[str]) -> None:
    length = instance.L
    horizon = network.horizon
    for scenario in instance.scenarios:
        graph = network.by_arc[scenario.s]
        for team in solution.teams:
            pairs = solution.arcs.get((team.r, scenario.s), [])
            keys = _trace(pairs)
            if keys is None:
                continue
            on_chain = set(keys)
            for visit in network.visits:
                bas = solution.bas.get((team.r, visit.key, scenario.s), 0.0)
                bit = solution.bit.get((team.r, visit.key, scenario.s), 0.0)
                if visit.key not in on_chain:
                    if abs(bas) > TOL or abs(bit) > TOL:
                        problems.append(f"(4.24) boş {visit.label} {team.r} {bas},{bit}")
                    continue
                if visit.kind in {"debris", "center"}:
                    lo, hi = time_window(visit, length)
                    if bas < lo - TOL or bit > hi + TOL or bit + TOL < bas:
                        problems.append(
                            f"(4.24) {team.r} {visit.label} [{bas:.3f},{bit:.3f}] "
                            f"pencere [{lo:.3f},{hi:.3f}]"
                        )
                elif visit.kind == "origin":
                    if abs(bas) > TOL or bit < -TOL or bit > length + TOL:
                        problems.append(f"(4.25) {team.r} {visit.label} Bas={bas} Bit={bit}")
                elif visit.kind == "enroute":
                    if abs(bas - horizon) > TOL or abs(bit - horizon) > TOL:
                        problems.append(f"(4.32) {team.r} {visit.label} {bas},{bit}")
            arc_of = {(tail, head): graph[(tail, head)] for tail, head in pairs}
            for index in range(1, len(keys)):
                arc = arc_of.get((keys[index - 1], keys[index]))
                if arc is None or arc.u.kind in {"sigma"}:
                    continue
                bit_u = solution.bit.get((team.r, arc.u.key, scenario.s), 0.0)
                if arc.tam:
                    bas_v = solution.bas.get((team.r, arc.v.key, scenario.s), 0.0)
                    if abs(bas_v - (bit_u + arc.sey)) > TOL:
                        problems.append(
                            f"(4.29) {team.r} {arc.u.label}->{arc.v.label} "
                            f"{bas_v:.3f} != {bit_u:.3f}+{arc.sey:.3f}"
                        )
                if arc.kind == "enroute":
                    if bit_u + arc.sey + TOL < horizon:
                        problems.append(
                            f"(4.33) {team.r} {arc.u.label} {bit_u:.3f}+{arc.sey:.3f} < {horizon}"
                        )
                if arc.kind == "end" and arc.u.kind == "debris" and bit_u + TOL < horizon:
                    problems.append(f"(4.31) {team.r} {arc.u.label} Bit={bit_u:.3f}")
            _check_one_activity(solution, team.r, scenario.s, keys, arc_of, problems)


def _check_one_activity(solution, team_r, scenario_s, keys, arc_of, problems: list[str]) -> None:
    """Zincir saatleri artar. Yol aralığının içine başka ziyaret girmez."""

    visits = []
    for key in keys:
        if key in {"sigma", "omega"}:
            continue
        bas = solution.bas.get((team_r, key, scenario_s), 0.0)
        bit = solution.bit.get((team_r, key, scenario_s), 0.0)
        visits.append((key, bas, bit))
    for index in range(1, len(visits)):
        if visits[index][1] + TOL < visits[index - 1][2]:
            problems.append(
                f"çakışan faaliyet {team_r} {scenario_s} "
                f"{visits[index - 1][0]} ve {visits[index][0]}"
            )
    for index in range(1, len(keys)):
        arc = arc_of.get((keys[index - 1], keys[index]))
        if arc is None or arc.kind not in {"travel", "enroute"} or arc.sey <= TOL:
            continue
        depart = solution.bit.get((team_r, arc.u.key, scenario_s), 0.0)
        arrive = solution.bas.get((team_r, arc.v.key, scenario_s), 0.0)
        for key, bas, bit in visits:
            if key in {arc.u.key, arc.v.key}:
                continue
            if bas < arrive - TOL and bit > depart + TOL:
                problems.append(f"yolda ikinci faaliyet {team_r} {key}")


def _check_inventory(instance, solution: TeamChainSolution, network, problems: list[str]) -> None:
    """(4.36) çıkış sayımı ve (4.38) yalnız gerçekleşen varışı ekler. ω^yol varış değildir."""

    chosen = {
        (team.r, scenario.s): set(solution.arcs.get((team.r, scenario.s), []))
        for team in solution.teams
        for scenario in instance.scenarios
    }
    for scenario in instance.scenarios:
        har = network.har[scenario.s]
        arrivals = network.arrivals[scenario.s]
        for (n, n2, t_dep), arc_list in har.items():
            if n in {center.j for center in instance.centers} and n2 in {
                center.j for center in instance.centers
            }:
                problems.append(f"(4.37) {n}->{n2} t={t_dep}")
        for center in instance.centers:
            for spec in instance.team_types:
                teams = [team for team in solution.teams if team.k == spec.k]
                for t_now in range(0, network.periods + 1):
                    if t_now == 0:
                        expected = solution.V[(center.j, spec.k)]
                    else:
                        arrived = 0
                        for ell in range(1, t_now + 1):
                            for arc in arrivals.get((center.j, ell), []):
                                for team in teams:
                                    if (arc.u.key, arc.v.key) in chosen[(team.r, scenario.s)]:
                                        arrived += 1
                        left = 0
                        for site in instance.sites:
                            for ell in range(1, t_now + 1):
                                for arc in har.get((center.j, site.i, ell), []):
                                    for team in teams:
                                        if (arc.u.key, arc.v.key) in chosen[(team.r, scenario.s)]:
                                            left += 1
                        expected = solution.V[(center.j, spec.k)] + arrived - left
                    recorded = solution.inventory.get((center.j, spec.k, t_now, scenario.s))
                    if recorded is None or recorded != expected:
                        label = "(4.39)" if t_now == 0 else "(4.38)"
                        problems.append(
                            f"{label} I_{center.j}_{spec.k}_t{t_now}_{scenario.s} "
                            f"{recorded} != {expected}"
                        )


def _entry(graph, tail: str, head: str, site_i: str) -> bool:
    arc = graph.get((tail, head))
    return arc is not None and is_site_entry(arc, site_i)


def _check_unmet(instance: Instance, solution: TeamChainSolution, problems: list[str]) -> None:
    tight = _tight_unmet(instance, solution.teams, solution.entries)
    weighted = 0.0
    for scenario in instance.scenarios:
        for site in instance.sites:
            recorded = solution.unmet[(site.i, scenario.s)]
            if abs(recorded - tight[(site.i, scenario.s)]) > TOL:
                problems.append(
                    f"u_{site.i}_{scenario.s}={recorded} beklenen {tight[(site.i, scenario.s)]}"
                )
            if recorded < -TOL or recorded > scenario.D[site.i] + TOL:
                problems.append(f"u_{site.i}_{scenario.s} aralık dışı")
            weighted += scenario.P * recorded
    if abs(weighted - solution.objective) > TOL:
        problems.append(f"amaç {solution.objective} != {weighted}")
    if abs(solution.solver_unmet - solution.objective) > 1e-2:
        problems.append(f"çözücü u {solution.solver_unmet} != {solution.objective}")
    for site in instance.sites:
        for scenario in instance.scenarios:
            for team in solution.teams:
                count = solution.entries[(team.r, site.i, scenario.s)]
                if count and competency(instance, site.i, team.k) == 0:
                    problems.append(f"a=0 iken giriş {team.r} {site.i}")


def center_name(center: str | None) -> str:
    return "ω" if center is None else center


def departure_beta(instance: Instance, scenario, arc) -> float | None:
    """Çözümdeki yayın β'si çıkış periyodundan okunur."""

    tail = arc.u.physical() or ""
    head = arc.v.j if arc.kind == "enroute" else (arc.v.physical() or "")
    return beta_at(instance, scenario, tail, head, arc.departure_t or 1)
