"""(4.4)–(4.10) ve ikinci aşama bağlantısının çözümde tuttuğunu denetler."""

from __future__ import annotations

from model.instance import Instance, competency
from model.problem import Solution

TOL = 1e-4


def violations(instance: Instance, solution: Solution) -> list[str]:
    problems: list[str] = []
    if solution.status != "Optimal":
        problems.append(f"durum Optimal değil: {solution.status}")

    opened = 0
    for center in instance.centers:
        g = solution.G[center.j]
        opened += g
        if g not in (0, 1):
            problems.append(f"(4.51) G_{center.j} ikili değil: {g}")
        for team in instance.team_types:
            placed = solution.V[(center.j, team.k)]
            if placed < 0 or placed > center.C[team.k] * g:
                problems.append(
                    f"(4.4) V_{center.j}_{team.k}={placed} > C {center.C[team.k]} * G {g}"
                )
        if solution.VU[center.j] < 0 or solution.VU[center.j] > center.U_max * g:
            problems.append(f"(4.5) VU_{center.j}={solution.VU[center.j]}")
        if solution.VW[center.j] < 0 or solution.VW[center.j] > center.W_max * g:
            problems.append(f"(4.6) VW_{center.j}={solution.VW[center.j]}")

    if opened > instance.N_max:
        problems.append(f"(4.7) açık merkez {opened} > N_max {instance.N_max}")

    for team in instance.team_types:
        fleet = sum(solution.V[(center.j, team.k)] for center in instance.centers)
        if fleet > team.A:
            problems.append(f"(4.8) {team.k} filo {fleet} > A {team.A}")
    if sum(solution.VU.values()) > instance.U_top:
        problems.append("(4.9) UMKE filosu aşıldı")
    if sum(solution.VW.values()) > instance.W_top:
        problems.append("(4.10) iş makinesi filosu aşıldı")

    for scenario in instance.scenarios:
        for center in instance.centers:
            for team in instance.team_types:
                dispatched = sum(
                    solution.y[(center.j, team.k, site.i, scenario.s)] for site in instance.sites
                )
                if dispatched > solution.V[(center.j, team.k)]:
                    problems.append(f"gönderilen {dispatched} > V_{center.j}_{team.k} ({scenario.s})")

    weighted = 0.0
    for scenario in instance.scenarios:
        for site in instance.sites:
            work = 0.0
            for center in instance.centers:
                for team in instance.team_types:
                    flow = solution.y[(center.j, team.k, site.i, scenario.s)]
                    if flow < 0:
                        problems.append("y negatif")
                    reachable = solution.h[(center.j, site.i, scenario.s)] == 1
                    allowed = competency(instance, site.i, team.k) == 1
                    if flow and not reachable:
                        problems.append(f"h=0 iken atama {center.j},{team.k},{site.i},{scenario.s}")
                    if flow and not allowed:
                        problems.append(f"a=0 iken atama {center.j},{team.k},{site.i}")
                    if solution.G[center.j] == 0 and flow:
                        problems.append(f"kapalı merkezden atama {center.j}")
                    work += flow * team.p * instance.L * competency(instance, site.i, team.k)
            demand = scenario.D[site.i]
            lower = max(0.0, demand - (demand / site.m) * work)
            recorded = solution.unmet[(site.i, scenario.s)]
            if recorded + TOL < lower:
                problems.append(f"u_{site.i}_{scenario.s}={recorded} < {lower}")
            if recorded > demand + TOL:
                problems.append(f"u_{site.i}_{scenario.s} talebi aşıyor")
            if scenario.P > 0 and recorded > lower + 1e-3:
                problems.append(f"u_{site.i}_{scenario.s} sıkı değil: {recorded} > {lower}")
            weighted += scenario.P * recorded

    if abs(weighted - solution.objective) > 1e-3:
        problems.append(f"amaç tutmuyor: {solution.objective} vs {weighted}")
    if abs(weighted - solution.unmet_cost) > 1e-3:
        problems.append("karşılanmayan talep kaydı tutmuyor")
    return problems
