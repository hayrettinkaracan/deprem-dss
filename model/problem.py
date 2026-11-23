"""Birinci aşama (here-and-now) MILP.

Rapor metni elimizde olmadığı için (4.4)–(4.10) eşlemesi varsayımdır.
İkinci aşama yalnızca ön konumlandırılmış ekibin enkazlara dağıtımı ve
karşılanmayan taleptir. Beklenti, Z2, rotalama ve zaman periyodu yoktur;
senaryo ağırlığı ``Scenario.pi`` ve yetkinlik ``a_{i,k}`` sonraki maddeler
için parametre olarak durur.

Amaç (birincil):
    min  Σ_j f_j G_j  +  Σ_s π_s Σ_i u_{i,s}

Birincil amaç sabitlendikten sonra, aynı maliyetteki çözümler arasında
yardımcı birimler doldurulur ve kullanılmayan ekip stoklanmaz. Bu ikinci
geçiş açma kararını ve karşılanmayan talebi değiştirmez.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from model.instance import (
    Instance,
    capacity_factor,
    competency,
    coverage_matrix,
    validate,
)

PRIMARY_LOCK_TOL = 1e-4


@dataclass
class Solution:
    status: str
    objective: float
    opening_cost: float
    unmet_cost: float
    G: dict[str, int]
    V: dict[tuple[str, str], int]
    VU: dict[str, int]
    VW: dict[str, int]
    y: dict[tuple[str, str, str, str], int]
    unmet: dict[tuple[str, str], float]
    coverage: dict[tuple[str, str], int] = field(default_factory=dict)


def default_solver() -> pulp.LpSolver:
    return pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1)


def solve_first_stage(instance: Instance, solver: pulp.LpSolver | None = None) -> Solution:
    """(4.4)–(4.10) ve ikinci aşama bağlantısını CBC ile çözer."""

    validate(instance)
    solver = solver or default_solver()
    coverage = coverage_matrix(instance)

    primary = _optimize(instance, coverage, solver, primary_cap=None)
    if primary.status != "Optimal":
        return primary

    refined = _optimize(
        instance,
        coverage,
        solver,
        primary_cap=primary.objective,
    )
    if refined.status != "Optimal":
        return primary
    if refined.objective > primary.objective + 1e-3:
        return primary
    return refined


def format_solution(instance: Instance, solution: Solution) -> str:
    lines = [
        f"Durum: {solution.status}",
        (
            f"Amaç: {solution.objective:.4f}  "
            f"(açma {solution.opening_cost:.4f} + karşılanmayan talep {solution.unmet_cost:.4f})"
        ),
        "Merkezler:",
    ]
    for center in instance.centers:
        teams = ", ".join(
            f"{team.k}={solution.V[(center.j, team.k)]}" for team in instance.team_types
        )
        lines.append(
            f"  {center.j} {center.name}: G={solution.G[center.j]}  "
            f"V[{teams}]  VU={solution.VU[center.j]}  VW={solution.VW[center.j]}"
        )
    lines.append("Senaryo karşılanmayan talep:")
    for scenario in instance.scenarios:
        total = sum(solution.unmet[(site.i, scenario.s)] for site in instance.sites)
        lines.append(f"  {scenario.name} (β={scenario.beta}): {total:.4f}")
    return "\n".join(lines)


def _optimize(
    instance: Instance,
    coverage: dict[tuple[str, str], int],
    solver: pulp.LpSolver,
    primary_cap: float | None,
) -> Solution:
    problem, variables, primary, secondary = _build(instance, coverage)
    if primary_cap is None:
        problem.setObjective(primary)
    else:
        problem += primary <= primary_cap + PRIMARY_LOCK_TOL, "primary_lock"
        problem.setObjective(secondary)

    status_code = problem.solve(solver)
    status = pulp.LpStatus.get(status_code, str(status_code))
    return _extract(instance, variables, coverage, status)


def _build(instance: Instance, coverage: dict[tuple[str, str], int]):
    centers = instance.centers
    types = instance.team_types
    sites = instance.sites
    scenarios = instance.scenarios
    j_index = {center.j: index for index, center in enumerate(centers)}
    k_index = {team.k: index for index, team in enumerate(types)}

    problem = pulp.LpProblem("Deprem_BirinciAsama", pulp.LpMinimize)

    G = {center.j: pulp.LpVariable(f"G_{center.j}", cat="Binary") for center in centers}
    V = {
        (center.j, team.k): pulp.LpVariable(f"V_{center.j}_{team.k}", lowBound=0, cat="Integer")
        for center in centers
        for team in types
    }
    VU = {center.j: pulp.LpVariable(f"VU_{center.j}", lowBound=0, cat="Integer") for center in centers}
    VW = {center.j: pulp.LpVariable(f"VW_{center.j}", lowBound=0, cat="Integer") for center in centers}
    y = {
        (center.j, team.k, site.i, scenario.s): pulp.LpVariable(
            f"y_{center.j}_{team.k}_{site.i}_{scenario.s}",
            lowBound=0,
            cat="Integer",
        )
        for center in centers
        for team in types
        for site in sites
        for scenario in scenarios
    }
    unmet = {
        (site.i, scenario.s): pulp.LpVariable(f"u_{site.i}_{scenario.s}", lowBound=0)
        for site in sites
        for scenario in scenarios
    }

    # (4.4) G_j ikili — değişken kategorisi.
    # (4.5) Açma bütçesi.
    if centers:
        problem += (
            pulp.lpSum(center.f * G[center.j] for center in centers) <= instance.B,
            "eq_4_5_budget",
        )
    # (4.6) Açılabilecek merkez sayısı.
    if centers:
        problem += pulp.lpSum(G[center.j] for center in centers) <= instance.N_max, "eq_4_6_nmax"

    # (4.7) Kapalı merkezde ekip yok; tip kapasitesi.
    for center in centers:
        for team in types:
            problem += (
                V[(center.j, team.k)] <= center.cap[team.k] * G[center.j],
                f"eq_4_7_cap_{center.j}_{team.k}",
            )
        # (4.8) Merkez toplam ekip yuvası. Yardımcı birimler bu yuvaya girmez.
        problem += (
            pulp.lpSum(V[(center.j, team.k)] for team in types) <= center.cap_tot * G[center.j],
            f"eq_4_8_cap_tot_{center.j}",
        )

    # (4.8) Filo: eldeki ekipten fazlası ön konumlanamaz.
    for team in types:
        problem += (
            pulp.lpSum(V[(center.j, team.k)] for center in centers) <= team.N,
            f"eq_4_8_fleet_{team.k}",
        )

    # (4.9) UMKE.
    for center in centers:
        problem += VU[center.j] <= center.cap_u * G[center.j], f"eq_4_9_cap_{center.j}"
    if centers:
        problem += pulp.lpSum(VU[center.j] for center in centers) <= instance.N_U, "eq_4_9_fleet"

    # (4.10) İş makinesi.
    for center in centers:
        problem += VW[center.j] <= center.cap_w * G[center.j], f"eq_4_10_cap_{center.j}"
    if centers:
        problem += pulp.lpSum(VW[center.j] for center in centers) <= instance.N_W, "eq_4_10_fleet"

    # İkinci aşama bağlantısı: senaryoda gönderilen ekip, ön konumlananı aşamaz
    # ve yalnızca açık yolu olan, kapsanan enkazlara gider.
    for center in centers:
        for team in types:
            for scenario in scenarios:
                problem += (
                    pulp.lpSum(y[(center.j, team.k, site.i, scenario.s)] for site in sites)
                    <= V[(center.j, team.k)],
                    f"link_dispatch_{center.j}_{team.k}_{scenario.s}",
                )
            for site in sites:
                for scenario in scenarios:
                    reachable = coverage[(center.j, site.i)] == 1 and scenario.h[site.i] == 1
                    if not reachable:
                        problem += (
                            y[(center.j, team.k, site.i, scenario.s)] == 0,
                            f"link_reach_{center.j}_{team.k}_{site.i}_{scenario.s}",
                        )

    for site in sites:
        for scenario in scenarios:
            service = pulp.lpSum(
                y[(center.j, team.k, site.i, scenario.s)]
                * team.q
                * capacity_factor(scenario.beta)
                * competency(instance, site.i, team.k)
                for center in centers
                for team in types
            )
            problem += unmet[(site.i, scenario.s)] >= site.d - service, f"unmet_{site.i}_{scenario.s}"
            problem += unmet[(site.i, scenario.s)] <= site.d, f"unmet_cap_{site.i}_{scenario.s}"

    primary_terms = [center.f * G[center.j] for center in centers]
    primary_terms += [
        scenario.pi * unmet[(site.i, scenario.s)] for scenario in scenarios for site in sites
    ]
    primary = pulp.lpSum(primary_terms) if primary_terms else 0

    # İkincil amaç yalnızca birincil kilit altındadır.
    # Düşük indeksli merkez ve tip, eşit hizmette tercih edilir.
    # Yüksek katsayı, UMKE ve iş makinesini kapasite dolana kadar doldurur.
    secondary_terms = [
        V[(center.j, team.k)] * (10 * j_index[center.j] + k_index[team.k] + 1)
        for center in centers
        for team in types
    ]
    secondary_terms += [
        -(VU[center.j] + VW[center.j]) * (1000 - j_index[center.j]) for center in centers
    ]
    secondary = pulp.lpSum(secondary_terms) if secondary_terms else 0

    variables = {"G": G, "V": V, "VU": VU, "VW": VW, "y": y, "u": unmet}
    return problem, variables, primary, secondary


def _extract(instance: Instance, variables: dict, coverage: dict[tuple[str, str], int], status: str) -> Solution:
    G = {j: _as_int(var) for j, var in variables["G"].items()}
    V = {key: _as_int(var) for key, var in variables["V"].items()}
    VU = {j: _as_int(var) for j, var in variables["VU"].items()}
    VW = {j: _as_int(var) for j, var in variables["VW"].items()}
    y = {key: _as_int(var) for key, var in variables["y"].items()}
    unmet = {key: _as_float(var) for key, var in variables["u"].items()}

    opening = sum(center.f * G[center.j] for center in instance.centers)
    unmet_cost = sum(
        scenario.pi * unmet[(site.i, scenario.s)]
        for scenario in instance.scenarios
        for site in instance.sites
    )
    return Solution(
        status=status,
        objective=opening + unmet_cost,
        opening_cost=opening,
        unmet_cost=unmet_cost,
        G=G,
        V=V,
        VU=VU,
        VW=VW,
        y=y,
        unmet=unmet,
        coverage=coverage,
    )


def _as_int(var: pulp.LpVariable) -> int:
    value = pulp.value(var)
    if value is None:
        return 0
    return int(round(float(value)))


def _as_float(var: pulp.LpVariable) -> float:
    value = pulp.value(var)
    if value is None:
        return 0.0
    return float(value)
