"""(4.18)–(4.23) ve zincir yapısını çözümün üzerinde yeniden sayar."""

from __future__ import annotations

from model.instance import Instance, competency
from model.network import build_network, is_site_entry, route_h
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
                _check_arc_rule(instance, scenario, arc, network.periods, problems)
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


def _check_arc_rule(instance, scenario, arc, periods: int, problems: list[str]) -> None:
    if arc.kind == "travel":
        opened = route_h(
            instance,
            arc.u.physical() or "",
            arc.v.physical() or "",
            arc.u.period() or 1,
            scenario,
        )
        if opened != 1:
            problems.append(f"h=0 yay {arc.u.label}->{arc.v.label} {scenario.s}")
        if arc.u.period() != arc.v.period():
            problems.append(f"periyot aşan yay {arc.u.label}->{arc.v.label}")
        if arc.u.physical() == arc.v.physical():
            problems.append(f"aynı noktada gerçek hareket {arc.u.label}")
        ends = {arc.u.kind, arc.v.kind}
        debris_ends = (arc.u.kind == "debris") + (arc.v.kind == "debris")
        if debris_ends != 1:
            problems.append(f"merkezler arası veya enkazlar arası yay {arc.u.label}->{arc.v.label}")
        if ends <= {"origin", "center"}:
            problems.append(f"merkezler arası yay {arc.u.label}->{arc.v.label}")
    if arc.kind == "continue":
        if arc.u.i != arc.v.i or arc.v.t != arc.u.t + 1:
            problems.append(f"devam yayı bozuk {arc.u.label}->{arc.v.label}")
    if arc.kind == "end" and arc.u.kind == "debris" and arc.u.t != periods:
        problems.append(f"erken enkaz bitişi {arc.u.label}")


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
