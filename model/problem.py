"""Birinci aşama MILP, rapor (4.4)–(4.10).

Amaç bu kalemde tam Z1 değildir. Z1, 36 periyot boyunca Δ toplar; Z2 seyahat
ve yardımcı tahsis cezasıdır. İkisi de sonraki maddeler. Burada her ekip bir
senaryoda en fazla bir enkazda tek periyot (L saat) çalışır:

    iş_{i,s} = Σ_{j,k} y_{j,k,i,s} · p_k · L · a_{i,k}
    u_{i,s} ≥ D_{i,s} - (D_{i,s}/m_i) · iş_{i,s} ,   0 ≤ u_{i,s} ≤ D_{i,s}

ve amaç Σ_s P_s Σ_i u_{i,s}. Yol ancak h_{j,i,s}=1 ise kullanılır.
Birincil amaç sabitlendikten sonra boş merkez, fazla ekip ve yardımcı tahsis
sıfırlanır. Bu ikinci geçiş (4.3) cezasını koymaz; yalnızca aynı maliyetteki
çözümlerden birini seçer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from model.instance import Instance, competency, h_matrix, validate

PRIMARY_LOCK_TOL = 1e-4


@dataclass
class Solution:
    status: str
    objective: float
    unmet_cost: float
    G: dict[str, int]
    V: dict[tuple[str, str], int]
    VU: dict[str, int]
    VW: dict[str, int]
    y: dict[tuple[str, str, str, str], int]
    unmet: dict[tuple[str, str], float]
    h: dict[tuple[str, str, str], int] = field(default_factory=dict)


def default_solver() -> pulp.LpSolver:
    return pulp.PULP_CBC_CMD(msg=False, gapRel=0, threads=1)


def solve_first_stage(instance: Instance, solver: pulp.LpSolver | None = None) -> Solution:
    validate(instance)
    solver = solver or default_solver()
    usable = h_matrix(instance)
    primary = _optimize(instance, usable, solver, primary_cap=None)
    if primary.status != "Optimal":
        return primary
    refined = _optimize(instance, usable, solver, primary_cap=primary.objective)
    if refined.status != "Optimal" or refined.objective > primary.objective + 1e-3:
        return primary
    return refined


def constraint_names(instance: Instance) -> set[str]:
    problem, _variables, _primary, _secondary = _build(instance, h_matrix(instance))
    return set(problem.constraints)


def format_solution(instance: Instance, solution: Solution) -> str:
    lines = [
        f"Durum: {solution.status}",
        f"Amaç: {solution.objective:.4f}  (beklenen karşılanmayan talep)",
        "Merkezler:",
    ]
    for center in instance.centers:
        teams = ", ".join(
            f"{team.k}={solution.V[(center.j, team.k)]}" for team in instance.team_types
        )
        lines.append(
            f"  {center.j}: G={solution.G[center.j]}  V[{teams}]  "
            f"VU={solution.VU[center.j]}  VW={solution.VW[center.j]}"
        )
    lines.append("Senaryo karşılanmayan talep:")
    for scenario in instance.scenarios:
        total = sum(solution.unmet[(site.i, scenario.s)] for site in instance.sites)
        lines.append(f"  {scenario.name} P={scenario.P}: {total:.4f}")
    return "\n".join(lines)


def _optimize(
    instance: Instance,
    usable: dict[tuple[str, str, str], int],
    solver: pulp.LpSolver,
    primary_cap: float | None,
) -> Solution:
    problem, variables, primary, secondary = _build(instance, usable)
    if primary_cap is None:
        problem.setObjective(primary)
    else:
        problem += primary <= primary_cap + PRIMARY_LOCK_TOL, "primary_lock"
        problem.setObjective(secondary)
    status_code = problem.solve(solver)
    status = pulp.LpStatus.get(status_code, str(status_code))
    return _extract(instance, variables, usable, status)


def _build(instance: Instance, usable: dict[tuple[str, str, str], int]):
    centers = instance.centers
    types = instance.team_types
    sites = instance.sites
    scenarios = instance.scenarios
    j_index = {center.j: index for index, center in enumerate(centers)}
    k_index = {team.k: index for index, team in enumerate(types)}
    i_index = {site.i: index for index, site in enumerate(sites)}
    type_count = max(len(types), 1)

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
        (site.i, scenario.s): pulp.LpVariable(
            f"u_{site.i}_{scenario.s}", lowBound=0, upBound=scenario.D[site.i]
        )
        for site in sites
        for scenario in scenarios
    }

    # (4.4) kapalı veya kapasitesi yetmeyen merkezde ekip yok
    for center in centers:
        for team in types:
            problem += (
                V[(center.j, team.k)] <= center.C[team.k] * G[center.j],
                f"eq_4_4_{center.j}_{team.k}",
            )
        # (4.5) UMKE yalnızca açık merkezde ve U_{j,max} içinde
        problem += VU[center.j] <= center.U_max * G[center.j], f"eq_4_5_{center.j}"
        # (4.6) iş makinesi aynı biçimde
        problem += VW[center.j] <= center.W_max * G[center.j], f"eq_4_6_{center.j}"

    # (4.7) merkez sayısı; parasal bütçe değil
    if centers:
        problem += pulp.lpSum(G[center.j] for center in centers) <= instance.N_max, "eq_4_7_Nmax"
    # (4.8) filo
    for team in types:
        problem += (
            pulp.lpSum(V[(center.j, team.k)] for center in centers) <= team.A,
            f"eq_4_8_{team.k}",
        )
    # (4.9) (4.10) yardımcı filolar
    if centers:
        problem += pulp.lpSum(VU[center.j] for center in centers) <= instance.U_top, "eq_4_9_Utop"
        problem += pulp.lpSum(VW[center.j] for center in centers) <= instance.W_top, "eq_4_10_Wtop"

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
                    key = (center.j, team.k, site.i, scenario.s)
                    if usable[(center.j, site.i, scenario.s)] == 0:
                        problem += y[key] == 0, f"link_h_{center.j}_{team.k}_{site.i}_{scenario.s}"
                    if competency(instance, site.i, team.k) == 0:
                        problem += y[key] == 0, f"link_a_{center.j}_{team.k}_{site.i}_{scenario.s}"

    for site in sites:
        for scenario in scenarios:
            work = pulp.lpSum(
                y[(center.j, team.k, site.i, scenario.s)]
                * team.p
                * instance.L
                * competency(instance, site.i, team.k)
                for center in centers
                for team in types
            )
            people_per_hour = scenario.D[site.i] / site.m
            problem += (
                unmet[(site.i, scenario.s)] >= scenario.D[site.i] - people_per_hour * work,
                f"unmet_{site.i}_{scenario.s}",
            )

    primary_terms = [
        scenario.P * unmet[(site.i, scenario.s)] for scenario in scenarios for site in sites
    ]
    primary = pulp.lpSum(primary_terms) if primary_terms else 0

    # Lexicographic tie-break: earlier center and type are cheaper by powers of 8.
    secondary_terms = [G[center.j] * (j_index[center.j] + 1) for center in centers]
    secondary_terms += [
        V[(center.j, team.k)] * (8 ** (j_index[center.j] * type_count + k_index[team.k]))
        for center in centers
        for team in types
    ]
    secondary_terms += [(VU[center.j] + VW[center.j]) * (j_index[center.j] + 1) for center in centers]
    secondary_terms += [
        y[(center.j, team.k, site.i, scenario.s)] * 0.001 * (i_index[site.i] + 1)
        for center in centers
        for team in types
        for site in sites
        for scenario in scenarios
    ]
    secondary = pulp.lpSum(secondary_terms) if secondary_terms else 0
    variables = {"G": G, "V": V, "VU": VU, "VW": VW, "y": y, "u": unmet}
    return problem, variables, primary, secondary


def _extract(
    instance: Instance,
    variables: dict,
    usable: dict[tuple[str, str, str], int],
    status: str,
) -> Solution:
    G = {j: _as_int(var) for j, var in variables["G"].items()}
    V = {key: _as_int(var) for key, var in variables["V"].items()}
    VU = {j: _as_int(var) for j, var in variables["VU"].items()}
    VW = {j: _as_int(var) for j, var in variables["VW"].items()}
    y = {key: _as_int(var) for key, var in variables["y"].items()}
    unmet = {key: _as_float(var) for key, var in variables["u"].items()}
    unmet_cost = sum(
        scenario.P * unmet[(site.i, scenario.s)]
        for scenario in instance.scenarios
        for site in instance.sites
    )
    return Solution(
        status=status,
        objective=unmet_cost,
        unmet_cost=unmet_cost,
        G=G,
        V=V,
        VU=VU,
        VW=VW,
        y=y,
        unmet=unmet,
        h=usable,
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
