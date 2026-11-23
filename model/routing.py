"""Bireysel ekip zinciri. Rapor (4.18)–(4.23), Bölüm 4.3, 4.4, 4.6(iii), 4.7.

Her ekip r ve senaryo s için σ'dan ω'ya tek zincir vardır. Tahsis edilmeyen
ekip σ → ω seçer. (4.21) ve (4.22) başlangıç merkezini V_{j,k} ile ve
senaryolar arasında ortak tutar. (4.23) aynı enkaza ikinci fiziksel girişi
kapatır; (i, t) → (i, t+1) bu toplama girmez.

Yer tutucular (sonraki maddeler):

- Çözülen ufuk ``PLACEHOLDER_PERIODS`` = 1. Düğüm kurucusu genel |T| alır;
  36 periyot, periyot aşan yol ve Bas/Bit madde 3 ve 4'tür.
- İş, (4.23)'ün saydığı her giriş için p_k · L saattir. Devam yayı ek iş
  yazmaz. q = p(Bit − Bas) madde 4, Z1 (4.2) madde 5'tir.
- Amaç hâlâ Σ_s P_s Σ_i u_{i,s} ve u, madde 1'deki gibi işten türetilir.
- Çevrimleri süre kısıtı (4.29)–(4.30) kesecektir. Burada A_s, enkaz
  sırasına göre yönlenir; graf çevrimsizdir ve ayrıca potansiyel yazılmaz.
- a_{i,k} = 0 ise o ekip o enkaza giremez. (4.45)'in X biçimi madde 10'dadır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from model.instance import Instance, competency, validate
from model.network import Arc, Network, build_network, is_site_entry

PLACEHOLDER_PERIODS = 1
PRIMARY_LOCK_TOL = 1e-4

CHAIN_CAPTION = (
    "Rapor (4.18)–(4.23): her ekip σ'dan ω'ya tek zincir izler. "
    "Başlangıç merkezi V_{j,k} ile ortaktır; σ → ω tahsis edilmeyen ekiptir. "
    f"Yer tutucu ufuk {PLACEHOLDER_PERIODS} periyottur. Her fiziksel enkaz girişi "
    "L saat iş sayılır; devam yayı ikinci giriş değildir. "
    "Bas/Bit, 36 periyot ve q sonraki maddelerdir. Bu zincir Supabase kaydını değiştirmez."
)


@dataclass(frozen=True)
class Team:
    """R_k içindeki ekip. k(r) mevcut türüdür."""

    r: str
    k: str
    ordinal: int


@dataclass
class TeamChainSolution:
    status: str
    objective: float
    unmet_cost: float
    solver_unmet: float
    G: dict[str, int]
    V: dict[tuple[str, str], int]
    VU: dict[str, int]
    VW: dict[str, int]
    unmet: dict[tuple[str, str], float]
    periods: int
    reentry_ban: bool
    reference_scenario: str
    teams: list[Team]
    chains: dict[tuple[str, str], list[str]]
    arcs: dict[tuple[str, str], list[tuple[str, str]]] = field(default_factory=dict)
    entries: dict[tuple[str, str, str], int] = field(default_factory=dict)


def roster(instance: Instance) -> list[Team]:
    """R = ⋃_k R_k. Türler ayrık kalır; |R_k| = A_k."""

    teams: list[Team] = []
    ordinal = 1
    for spec in instance.team_types:
        for index in range(1, spec.A + 1):
            teams.append(Team(r=f"{spec.k}-{index}", k=spec.k, ordinal=ordinal))
            ordinal += 1
    return teams


def default_solver(time_limit: int | None = None) -> pulp.LpSolver:
    kwargs: dict = {"msg": False, "gapRel": 0, "threads": 1}
    if time_limit is not None:
        kwargs["timeLimit"] = time_limit
    return pulp.PULP_CBC_CMD(**kwargs)


def solve_team_chains(
    instance: Instance,
    solver: pulp.LpSolver | None = None,
    periods: int | None = None,
    reentry_ban: bool = True,
    time_limit: int | None = None,
) -> TeamChainSolution:
    """Zincirli modeli çözer. periods verilmezse yer tutucu ufuk kullanılır."""

    validate(instance)
    periods = PLACEHOLDER_PERIODS if periods is None else periods
    network = build_network(instance, periods)
    solver = solver or default_solver(time_limit)
    primary = _optimize(instance, network, solver, primary_cap=None, reentry_ban=reentry_ban)
    if primary.status != "Optimal":
        return primary
    refined = _optimize(
        instance,
        network,
        solver,
        primary_cap=primary.objective,
        reentry_ban=reentry_ban,
    )
    if refined.status != "Optimal" or refined.objective > primary.objective + 1e-3:
        return primary
    return refined


def constraint_names(
    instance: Instance,
    periods: int | None = None,
    reentry_ban: bool = True,
) -> set[str]:
    periods = PLACEHOLDER_PERIODS if periods is None else periods
    problem, _bundle, _primary, _secondary = _build(
        instance, build_network(instance, periods), reentry_ban=reentry_ban
    )
    return set(problem.constraints)


def format_routing(instance: Instance, solution: TeamChainSolution) -> str:
    lines = [
        f"Durum: {solution.status}",
        f"Amaç: {solution.objective:.4f}  (beklenen karşılanmayan talep, yer tutucu iş)",
        f"Periyot yer tutucusu: {solution.periods}",
        "Merkezler:",
    ]
    for center in instance.centers:
        teams = ", ".join(
            f"{spec.k}={solution.V[(center.j, spec.k)]}" for spec in instance.team_types
        )
        lines.append(
            f"  {center.j}: G={solution.G[center.j]}  V[{teams}]  "
            f"VU={solution.VU[center.j]}  VW={solution.VW[center.j]}"
        )
    lines.append("Zincirler:")
    for scenario in instance.scenarios:
        lines.append(f"  {scenario.s} {scenario.name}:")
        for team in solution.teams:
            chain = " → ".join(solution.chains.get((team.r, scenario.s), []))
            lines.append(f"    {team.r}: {chain}")
    lines.append("Senaryo karşılanmayan talep:")
    for scenario in instance.scenarios:
        bits = ", ".join(
            f"{site.i}={solution.unmet[(site.i, scenario.s)]:.2f}" for site in instance.sites
        )
        total = sum(solution.unmet[(site.i, scenario.s)] for site in instance.sites)
        lines.append(f"  {scenario.name} P={scenario.P}: {total:.4f}  ({bits})")
    return "\n".join(lines)


def chain_rows(instance: Instance, solution: TeamChainSolution) -> list[dict[str, str]]:
    names = {scenario.s: scenario.name for scenario in instance.scenarios}
    rows = []
    for scenario in instance.scenarios:
        for team in solution.teams:
            rows.append(
                {
                    "Senaryo": names[scenario.s],
                    "Ekip": team.r,
                    "Tür": team.k,
                    "Zincir": " → ".join(solution.chains.get((team.r, scenario.s), [])),
                }
            )
    return rows


def _optimize(
    instance: Instance,
    network: Network,
    solver: pulp.LpSolver,
    primary_cap: float | None,
    reentry_ban: bool,
) -> TeamChainSolution:
    problem, bundle, primary, secondary = _build(instance, network, reentry_ban=reentry_ban)
    if primary_cap is None:
        problem.setObjective(primary)
    else:
        problem += primary <= primary_cap + PRIMARY_LOCK_TOL, "primary_lock"
        problem.setObjective(secondary)
    status_code = problem.solve(solver)
    status = pulp.LpStatus.get(status_code, str(status_code))
    return _extract(instance, network, bundle, status, reentry_ban)


def _build(instance: Instance, network: Network, reentry_ban: bool):
    centers = instance.centers
    types = instance.team_types
    sites = instance.sites
    scenarios = instance.scenarios
    teams = roster(instance)
    teams_of = {spec.k: [team for team in teams if team.k == spec.k] for spec in types}
    j_index = {center.j: index for index, center in enumerate(centers)}
    k_index = {spec.k: index for index, spec in enumerate(types)}
    type_count = max(len(types), 1)
    site_rank = {site.i: index + 1 for index, site in enumerate(sites)}
    center_rank = {center.j: index + 1 for index, center in enumerate(centers)}
    p_of = {spec.k: spec.p for spec in types}
    reference = scenarios[0].s if scenarios else ""

    problem = pulp.LpProblem("Deprem_EkipZinciri", pulp.LpMinimize)
    G = {center.j: pulp.LpVariable(f"G_{center.j}", cat="Binary") for center in centers}
    V = {
        (center.j, spec.k): pulp.LpVariable(f"V_{center.j}_{spec.k}", lowBound=0, cat="Integer")
        for center in centers
        for spec in types
    }
    VU = {center.j: pulp.LpVariable(f"VU_{center.j}", lowBound=0, cat="Integer") for center in centers}
    VW = {center.j: pulp.LpVariable(f"VW_{center.j}", lowBound=0, cat="Integer") for center in centers}
    Y: dict[tuple[str, str, str, str], pulp.LpVariable] = {}
    for scenario in scenarios:
        for team in teams:
            for arc in network.arcs[scenario.s]:
                Y[(team.r, arc.u.key, arc.v.key, scenario.s)] = pulp.LpVariable(
                    f"Y_{team.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    cat="Binary",
                )

    _add_first_stage(problem, instance, G, V, VU, VW)
    _add_competency_blocks(problem, instance, network, teams, Y)
    _add_chain_equations(
        problem,
        instance,
        network,
        teams,
        teams_of,
        Y,
        V,
        reference,
        reentry_ban,
    )

    unmet = {
        (site.i, scenario.s): pulp.LpVariable(
            f"u_{site.i}_{scenario.s}",
            lowBound=0,
            upBound=scenario.D[site.i],
        )
        for site in sites
        for scenario in scenarios
    }
    for site in sites:
        for scenario in scenarios:
            incoming = []
            for team in teams:
                for arc in network.arcs[scenario.s]:
                    if is_site_entry(arc, site.i):
                        incoming.append(
                            Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                            * p_of[team.k]
                            * instance.L
                            * competency(instance, site.i, team.k)
                        )
            work = pulp.lpSum(incoming) if incoming else 0
            people_per_hour = scenario.D[site.i] / site.m
            problem += (
                unmet[(site.i, scenario.s)] >= scenario.D[site.i] - people_per_hour * work,
                f"unmet_{site.i}_{scenario.s}",
            )

    primary_terms = [
        scenario.P * unmet[(site.i, scenario.s)] for scenario in scenarios for site in sites
    ]
    primary = pulp.lpSum(primary_terms) if primary_terms else 0

    secondary_terms = [G[center.j] * (j_index[center.j] + 1) for center in centers]
    secondary_terms += [
        V[(center.j, spec.k)] * (8 ** (j_index[center.j] * type_count + k_index[spec.k]))
        for center in centers
        for spec in types
    ]
    secondary_terms += [(VU[center.j] + VW[center.j]) * (j_index[center.j] + 1) for center in centers]
    for team in teams:
        for scenario in scenarios:
            for arc in network.arcs[scenario.s]:
                penalty = _arc_penalty(arc, team, site_rank, center_rank, len(sites))
                if penalty:
                    secondary_terms.append(
                        penalty * Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                    )
    secondary_terms += [unmet[key] * 1e-6 for key in unmet]
    secondary = pulp.lpSum(secondary_terms) if secondary_terms else 0
    bundle = {
        "G": G,
        "V": V,
        "VU": VU,
        "VW": VW,
        "Y": Y,
        "u": unmet,
        "teams": teams,
        "reference": reference,
    }
    return problem, bundle, primary, secondary


def _add_first_stage(problem, instance: Instance, G, V, VU, VW) -> None:
    """(4.4)–(4.10). Madde 1 ile aynı blok; V burada zincire bağlanır."""

    centers = instance.centers
    types = instance.team_types
    for center in centers:
        for spec in types:
            problem += (
                V[(center.j, spec.k)] <= center.C[spec.k] * G[center.j],
                f"eq_4_4_{center.j}_{spec.k}",
            )
        problem += VU[center.j] <= center.U_max * G[center.j], f"eq_4_5_{center.j}"
        problem += VW[center.j] <= center.W_max * G[center.j], f"eq_4_6_{center.j}"
    if centers:
        problem += pulp.lpSum(G[center.j] for center in centers) <= instance.N_max, "eq_4_7_Nmax"
    for spec in types:
        problem += (
            pulp.lpSum(V[(center.j, spec.k)] for center in centers) <= spec.A,
            f"eq_4_8_{spec.k}",
        )
    if centers:
        problem += pulp.lpSum(VU[center.j] for center in centers) <= instance.U_top, "eq_4_9_Utop"
        problem += pulp.lpSum(VW[center.j] for center in centers) <= instance.W_top, "eq_4_10_Wtop"


def _add_competency_blocks(problem, instance: Instance, network: Network, teams: list[Team], Y) -> None:
    """a_{i,k}=0 ise o tür o enkaza giren yayları kullanamaz. (4.45) madde 10'dadır."""

    for scenario in instance.scenarios:
        for team in teams:
            for site in instance.sites:
                if competency(instance, site.i, team.k) == 1:
                    continue
                for arc in network.arcs[scenario.s]:
                    if arc.v.kind != "debris" or arc.v.i != site.i:
                        continue
                    problem += (
                        Y[(team.r, arc.u.key, arc.v.key, scenario.s)] == 0,
                        f"link_a_{team.r}_{site.i}_{scenario.s}_{arc.u.key}",
                    )


def _add_chain_equations(
    problem,
    instance: Instance,
    network: Network,
    teams: list[Team],
    teams_of: dict[str, list[Team]],
    Y,
    V,
    reference: str,
    reentry_ban: bool,
) -> None:
    sigma = network.sigma.key
    omega = network.omega.key
    for scenario in instance.scenarios:
        arcs = network.arcs[scenario.s]
        out_of: dict[str, list[Arc]] = {}
        into: dict[str, list[Arc]] = {}
        for arc in arcs:
            out_of.setdefault(arc.u.key, []).append(arc)
            into.setdefault(arc.v.key, []).append(arc)
        for team in teams:
            problem += (
                pulp.lpSum(
                    Y[(team.r, arc.u.key, arc.v.key, scenario.s)] for arc in out_of.get(sigma, [])
                )
                == 1,
                f"eq_4_18_{team.r}_{scenario.s}",
            )
            problem += (
                pulp.lpSum(
                    Y[(team.r, arc.u.key, arc.v.key, scenario.s)] for arc in into.get(omega, [])
                )
                == 1,
                f"eq_4_19_{team.r}_{scenario.s}",
            )
            for visit in network.visits:
                arrived = pulp.lpSum(
                    Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                    for arc in into.get(visit.key, [])
                )
                left = pulp.lpSum(
                    Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                    for arc in out_of.get(visit.key, [])
                )
                problem += arrived == left, f"eq_4_20_{team.r}_{visit.key}_{scenario.s}"
                problem += arrived <= 1, f"eq_4_20_le1_{team.r}_{visit.key}_{scenario.s}"

        for center in instance.centers:
            origin = f"o_{center.j}"
            for spec in instance.team_types:
                problem += (
                    V[(center.j, spec.k)]
                    == pulp.lpSum(
                        Y[(team.r, sigma, origin, scenario.s)]
                        for team in teams_of[spec.k]
                        if (team.r, sigma, origin, scenario.s) in Y
                    ),
                    f"eq_4_21_{center.j}_{spec.k}_{scenario.s}",
                )

        if scenario.s != reference:
            for team in teams:
                for center in instance.centers:
                    origin = f"o_{center.j}"
                    problem += (
                        Y[(team.r, sigma, origin, scenario.s)]
                        == Y[(team.r, sigma, origin, reference)],
                        f"eq_4_22_{team.r}_{center.j}_{scenario.s}",
                    )

        if reentry_ban:
            for team in teams:
                for site in instance.sites:
                    entries = [
                        Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                        for arc in arcs
                        if is_site_entry(arc, site.i)
                    ]
                    problem += (
                        pulp.lpSum(entries) <= 1,
                        f"eq_4_23_{team.r}_{site.i}_{scenario.s}",
                    )


def _arc_penalty(
    arc: Arc,
    team: Team,
    site_rank: dict[str, int],
    center_rank: dict[str, int],
    site_count: int,
) -> float:
    """Aynı karşılanmayan talep içinden tek zincir seçer. Rapor amacı değildir.

    Katsayılar V ağırlığının (8'in kuvvetleri) altında kalır; ön konumlandırmayı
    değiştirmez. Küçük enkaz indisi önce ziyaret edilir, dönüş en küçük ℓ'ye gider.
    """

    if arc.kind == "start" and arc.v.kind == "origin":
        return team.ordinal * center_rank[arc.v.j] * 1e-4
    if arc.kind == "travel" and arc.v.kind == "debris":
        rank = site_rank[arc.v.i]
        team_cost = team.ordinal * 1e-4
        if arc.u.kind == "origin":
            return rank * 1e-3 + team_cost
        ell = arc.u.ell if arc.u.kind == "center" else 1
        breadth = site_count + 1
        return 1e-2 + rank * 1e-4 + ell * (breadth - rank) * 1e-4 + team_cost
    if arc.kind == "travel" and arc.v.kind == "center":
        return arc.v.ell * 1e-4
    if arc.kind == "continue":
        return 1e-5
    if arc.kind == "wait":
        return 1e-4
    if arc.kind in {"enroute", "enroute_end"}:
        return 1e-2
    return 0.0


def _extract(
    instance: Instance,
    network: Network,
    bundle: dict,
    status: str,
    reentry_ban: bool,
) -> TeamChainSolution:
    teams: list[Team] = bundle["teams"]
    G = {j: _as_int(var) for j, var in bundle["G"].items()}
    V = {key: _as_int(var) for key, var in bundle["V"].items()}
    VU = {j: _as_int(var) for j, var in bundle["VU"].items()}
    VW = {j: _as_int(var) for j, var in bundle["VW"].items()}
    chosen: dict[tuple[str, str], list[tuple[str, str]]] = {}
    entries = {
        (team.r, site.i, scenario.s): 0
        for team in teams
        for site in instance.sites
        for scenario in instance.scenarios
    }
    for (team_r, u_key, v_key, scenario_s), var in bundle["Y"].items():
        if _as_float(var) <= 0.5:
            continue
        chosen.setdefault((team_r, scenario_s), []).append((u_key, v_key))
        arc = network.by_arc[scenario_s][(u_key, v_key)]
        for site in instance.sites:
            if is_site_entry(arc, site.i):
                entries[(team_r, site.i, scenario_s)] += 1

    chains: dict[tuple[str, str], list[str]] = {}
    for scenario in instance.scenarios:
        for team in teams:
            pairs = chosen.get((team.r, scenario.s), [])
            keys = _trace(pairs)
            if keys is None:
                chains[(team.r, scenario.s)] = []
            else:
                chains[(team.r, scenario.s)] = [network.by_key[key].label for key in keys]
            chosen.setdefault((team.r, scenario.s), [])

    unmet = _tight_unmet(instance, teams, entries)
    unmet_cost = sum(
        scenario.P * unmet[(site.i, scenario.s)]
        for scenario in instance.scenarios
        for site in instance.sites
    )
    solver_unmet = sum(
        scenario.P * _as_float(bundle["u"][(site.i, scenario.s)])
        for scenario in instance.scenarios
        for site in instance.sites
    )
    return TeamChainSolution(
        status=status,
        objective=unmet_cost,
        unmet_cost=unmet_cost,
        solver_unmet=solver_unmet,
        G=G,
        V=V,
        VU=VU,
        VW=VW,
        unmet=unmet,
        periods=network.periods,
        reentry_ban=reentry_ban,
        reference_scenario=bundle["reference"],
        teams=teams,
        chains=chains,
        arcs=chosen,
        entries=entries,
    )


def _tight_unmet(
    instance: Instance,
    teams: list[Team],
    entries: dict[tuple[str, str, str], int],
) -> dict[tuple[str, str], float]:
    p_of = {spec.k: spec.p for spec in instance.team_types}
    unmet: dict[tuple[str, str], float] = {}
    for site in instance.sites:
        for scenario in instance.scenarios:
            work = 0.0
            for team in teams:
                work += (
                    entries[(team.r, site.i, scenario.s)]
                    * p_of[team.k]
                    * instance.L
                    * competency(instance, site.i, team.k)
                )
            demand = scenario.D[site.i]
            lower = demand - (demand / site.m) * work
            unmet[(site.i, scenario.s)] = max(0.0, lower)
    return unmet


def _trace(pairs: list[tuple[str, str]]) -> list[str] | None:
    succ: dict[str, str] = {}
    for tail, head in pairs:
        if tail in succ:
            return None
        succ[tail] = head
    if "sigma" not in succ:
        return None
    chain = ["sigma"]
    seen = {"sigma"}
    node = "sigma"
    while node != "omega":
        if node not in succ:
            return None
        node = succ[node]
        if node in seen:
            return None
        seen.add(node)
        chain.append(node)
        if len(chain) > len(pairs) + 1:
            return None
    if len(chain) - 1 != len(pairs):
        return None
    return chain


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
