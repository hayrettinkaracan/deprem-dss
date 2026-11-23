"""Çözümün birinci aşama kısıtlarını ve ikinci aşama bağlantısını denetler."""

from __future__ import annotations

from model.instance import Instance, capacity_factor, competency
from model.problem import Solution


TOL = 1e-4


def violations(instance: Instance, solution: Solution) -> list[str]:
    problems: list[str] = []
    if solution.status != "Optimal":
        problems.append(f"durum Optimal değil: {solution.status}")

    opening = 0.0
    opened = 0
    for center in instance.centers:
        g = solution.G[center.j]
        opening += center.f * g
        opened += g
        if g not in (0, 1):
            problems.append(f"G_{center.j} ikili değil: {g}")

        team_sum = 0
        for team in instance.team_types:
            placed = solution.V[(center.j, team.k)]
            team_sum += placed
            if placed < 0:
                problems.append(f"V_{center.j}_{team.k} negatif")
            if placed > center.cap[team.k] * g:
                problems.append(
                    f"V_{center.j}_{team.k}={placed} > Cap {center.cap[team.k]} * G {g}"
                )
            if g == 0 and placed != 0:
                problems.append(f"Kapalı merkez {center.j} tip {team.k} ekip barındırıyor")
        if team_sum > center.cap_tot * g:
            problems.append(f"Merkez {center.j} toplam ekip {team_sum} > CapTot {center.cap_tot} * G")

        if solution.VU[center.j] < 0 or solution.VU[center.j] > center.cap_u * g:
            problems.append(f"VU_{center.j} kapasite dışında: {solution.VU[center.j]}")
        if solution.VW[center.j] < 0 or solution.VW[center.j] > center.cap_w * g:
            problems.append(f"VW_{center.j} kapasite dışında: {solution.VW[center.j]}")
        if g == 0 and (solution.VU[center.j] or solution.VW[center.j]):
            problems.append(f"Kapalı merkez {center.j} yardımcı birim barındırıyor")

    if opening > instance.B + TOL:
        problems.append(f"Bütçe aşıldı: {opening} > {instance.B}")
    if opened > instance.N_max:
        problems.append(f"Merkez sayısı aşıldı: {opened} > {instance.N_max}")

    for team in instance.team_types:
        fleet = sum(solution.V[(center.j, team.k)] for center in instance.centers)
        if fleet > team.N:
            problems.append(f"Tip {team.k} filo aşıldı: {fleet} > {team.N}")

    if sum(solution.VU.values()) > instance.N_U:
        problems.append("UMKE filosu aşıldı")
    if sum(solution.VW.values()) > instance.N_W:
        problems.append("İş makinesi filosu aşıldı")

    for center in instance.centers:
        for team in instance.team_types:
            for scenario in instance.scenarios:
                dispatched = 0
                for site in instance.sites:
                    key = (center.j, team.k, site.i, scenario.s)
                    flow = solution.y[key]
                    dispatched += flow
                    if flow < 0:
                        problems.append(f"y_{key} negatif")
                    reachable = solution.coverage[(center.j, site.i)] == 1 and scenario.h[site.i] == 1
                    if not reachable and flow != 0:
                        problems.append(f"Erişilemeyen atama y_{key}={flow}")
                    if solution.G[center.j] == 0 and flow != 0:
                        problems.append(f"Kapalı merkezden atama y_{key}={flow}")
                placed = solution.V[(center.j, team.k)]
                if dispatched > placed:
                    problems.append(
                        f"Senaryo {scenario.s} merkez {center.j} tip {team.k}: "
                        f"gönderilen {dispatched} > ön konum {placed}"
                    )

    weighted = 0.0
    for scenario in instance.scenarios:
        for site in instance.sites:
            service = 0.0
            for center in instance.centers:
                for team in instance.team_types:
                    flow = solution.y[(center.j, team.k, site.i, scenario.s)]
                    service += (
                        flow
                        * team.q
                        * capacity_factor(scenario.beta)
                        * competency(instance, site.i, team.k)
                    )
            recorded = solution.unmet[(site.i, scenario.s)]
            lower = max(0.0, site.d - service)
            if recorded + TOL < lower:
                problems.append(
                    f"u_{site.i}_{scenario.s}={recorded} < talep-hizmet {lower}"
                )
            if recorded > site.d + TOL:
                problems.append(f"u_{site.i}_{scenario.s} talebi aşıyor")
            weighted += scenario.pi * recorded

    recomputed = opening + weighted
    if abs(recomputed - solution.objective) > 1e-3:
        problems.append(f"Amaç tutmuyor: kayıt {solution.objective} hesap {recomputed}")
    if abs(opening - solution.opening_cost) > TOL:
        problems.append("Açma maliyeti tutmuyor")
    if abs(weighted - solution.unmet_cost) > 1e-3:
        problems.append("Karşılanmayan talep tutmuyor")
    return problems
