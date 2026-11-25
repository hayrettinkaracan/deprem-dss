"""Bireysel ekip zinciri ve periyot aşan yolculuk.

Rapor (4.18)–(4.23), (4.1), (4.24)–(4.33), (4.36)–(4.39).
T = {1, …, 36}, L = 2, H = L|T| varsayılan ufuktur. Küçük örnekler kendi |T|
değerini geçebilir; H her zaman L|T|'dir.

β ve h çıkış periyoduna aittir. Seyahat sınırı aşabilir; ekip varışa kadar
yoldadır ve aynı sürenin tamamı bir kez yazılır. Varış kaydı, varış saatinin
düştüğü periyottur. ω^yol_j, H anına yetişmeyen dönüştür; (4.38) onu stoka
eklemez.

Geçici yer tutucular (rapor denklemi değildir):

- İş hâlâ (4.23)'ün saydığı her fiziksel giriş için p·L saattir. (4.34) ve
  (4.11)–(4.14) madde 4 ve 7'dedir; Bit−Bas henüz işe yazılmaz.
- Amaç Σ_s P_s Σ_i u_{i,s}'dir. Z1'in Δ toplamı (4.2) madde 5, Z2 madde 6'dır.
- CBC'ye verilen başlangıç turu model amacı değildir. Eşit talep içinde madde 1'deki
  merkez sırasını seçer; çözücü daha iyi bir tur bulursa onu kullanır.
- a_{i,k}=0 o ekibin yayını kapatır. (4.45) madde 10, yeniden planlama madde 9'dadır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp

from model.instance import Instance, competency, require_legacy_demand, validate
from model.seed import apply_seed, build_seed
from model.network import (
    REPORT_PERIODS,
    Arc,
    Network,
    build_network,
    is_site_entry,
    route_h,
    time_window,
)

CHAIN_CAPTION = (
    "Rapor T={1..36}, L=2, H=L|T|. Her ekip σ'dan ω'ya tek zincir izler (4.18)–(4.23). "
    "β ve h çıkış periyoduna aittir; yolculuk sınır aşabilir, süre bir sonraki periyoda "
    "yeniden yazılmaz. Ekip varışa kadar yoldadır. ω^yol ufuk sonuna yetişmeyen dönüştür "
    "ve merkez stokuna girmez. İş yer tutucusu hâlâ giriş başına L saattir; "
    "q=p(Bit−Bas) sonraki maddedir. Bu zincir Supabase kaydını değiştirmez."
)


@dataclass(frozen=True)
class Team:
    """R_k içindeki ekip. k(r) mevcut türüdür."""

    r: str
    k: str
    ordinal: int


@dataclass(frozen=True)
class Crossing:
    """Periyot sınırı aşan veya ufuk sonunda yolda kalan bir yolculuk."""

    team: str
    scenario: str
    origin: str
    dest: str
    depart_h: float
    arrive_h: float
    sey: float
    departure_period: int
    arrival_period: int | None
    beta: float
    horizon: bool


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
    horizon: float
    reentry_ban: bool
    reference_scenario: str
    teams: list[Team]
    chains: dict[tuple[str, str], list[str]]
    arcs: dict[tuple[str, str], list[tuple[str, str]]] = field(default_factory=dict)
    entries: dict[tuple[str, str, str], int] = field(default_factory=dict)
    bas: dict[tuple[str, str, str], float] = field(default_factory=dict)
    bit: dict[tuple[str, str, str], float] = field(default_factory=dict)
    clock: dict[tuple[str, str], list[tuple[str, float | None, float | None]]] = field(
        default_factory=dict
    )
    crossings: list[Crossing] = field(default_factory=list)
    inventory: dict[tuple[str, str, int, str], int] = field(default_factory=dict)


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
    kwargs: dict = {"msg": False, "gapRel": 0, "threads": 1, "warmStart": True}
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
    """Zincirli modeli çözer. periods verilmezse rapor ufku |T|=36 kullanılır."""

    validate(instance)
    periods = REPORT_PERIODS if periods is None else periods
    network = build_network(instance, periods)
    solver = solver or default_solver(time_limit)
    return _optimize(instance, network, solver, reentry_ban=reentry_ban)


def constraint_names(
    instance: Instance,
    periods: int | None = None,
    reentry_ban: bool = True,
) -> set[str]:
    periods = REPORT_PERIODS if periods is None else periods
    problem, _bundle, _primary = _build(
        instance, build_network(instance, periods), reentry_ban=reentry_ban
    )
    return set(problem.constraints)


def format_routing(instance: Instance, solution: TeamChainSolution) -> str:
    lines = [
        f"Durum: {solution.status}",
        f"Amaç: {solution.objective:.4f}  (beklenen karşılanmayan talep, giriş başına L saat)",
        f"Ufuk: |T|={solution.periods}, L={instance.L:g}, H={solution.horizon:g}",
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
    lines.append("Zincirler ve saatler:")
    for scenario in instance.scenarios:
        lines.append(f"  {scenario.s} {scenario.name}:")
        for team in solution.teams:
            lines.append(f"    {team.r}: {clock_text(solution.clock.get((team.r, scenario.s), []))}")
    if solution.crossings:
        lines.append("Sınır aşan yolculuklar:")
        for trip in solution.crossings:
            dest = "ufuk sonrası" if trip.horizon else f"periyot {trip.arrival_period}"
            lines.append(
                f"  {trip.scenario} {trip.team}: {trip.origin} → {trip.dest}  "
                f"kalkış {trip.depart_h:.2f} (t={trip.departure_period}, β={trip.beta:g})  "
                f"Sey={trip.sey:.2f}  varış kaydı {trip.arrive_h:.2f} ({dest})"
            )
    lines.append("Senaryo karşılanmayan talep:")
    for scenario in instance.scenarios:
        bits = ", ".join(
            f"{site.i}={solution.unmet[(site.i, scenario.s)]:.2f}" for site in instance.sites
        )
        total = sum(solution.unmet[(site.i, scenario.s)] for site in instance.sites)
        lines.append(f"  {scenario.name} P={scenario.P}: {total:.4f}  ({bits})")
    return "\n".join(lines)


def clock_text(clock: list[tuple[str, float | None, float | None]]) -> str:
    parts = []
    for label, bas, bit in clock:
        if bas is None or bit is None:
            parts.append(label)
        else:
            parts.append(f"{label} [{bas:.2f}–{bit:.2f}]")
    return " → ".join(parts)


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
                    "Zaman": clock_text(solution.clock.get((team.r, scenario.s), [])),
                }
            )
    return rows


def _optimize(
    instance: Instance,
    network: Network,
    solver: pulp.LpSolver,
    reentry_ban: bool,
) -> TeamChainSolution:
    problem, bundle, primary = _build(instance, network, reentry_ban=reentry_ban)
    apply_seed(problem, bundle, build_seed(instance, network), instance, network)
    if getattr(solver, "optionsDict", None) is not None:
        solver.optionsDict["warmStart"] = True
    problem.setObjective(primary)
    status_code = problem.solve(solver)
    status = pulp.LpStatus.get(status_code, str(status_code))
    return _extract(instance, network, bundle, status, reentry_ban)


def _build(instance: Instance, network: Network, reentry_ban: bool):
    # Eski amaç Σ P u. Yeni Z1 (4.2) sonraki kalemde bunu değiştirir.
    require_legacy_demand(instance)
    centers = instance.centers
    types = instance.team_types
    sites = instance.sites
    scenarios = instance.scenarios
    teams = roster(instance)
    teams_of = {spec.k: [team for team in teams if team.k == spec.k] for spec in types}
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
    bas, bit = _time_variables(network, teams, scenarios)

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
    _add_timing(problem, instance, network, teams, scenarios, Y, bas, bit)
    flow = _add_inventory(problem, instance, network, teams_of, Y, V)

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
    bundle = {
        "G": G,
        "V": V,
        "VU": VU,
        "VW": VW,
        "Y": Y,
        "u": unmet,
        "bas": bas,
        "bit": bit,
        "I": flow,
        "teams": teams,
        "reference": reference,
    }
    return problem, bundle, primary


def _time_variables(network: Network, teams: list[Team], scenarios):
    upper = network.horizon
    bas: dict[tuple[str, str, str], pulp.LpVariable] = {}
    bit: dict[tuple[str, str, str], pulp.LpVariable] = {}
    for scenario in scenarios:
        for team in teams:
            for visit in network.visits:
                bas[(team.r, visit.key, scenario.s)] = pulp.LpVariable(
                    f"Bas_{team.r}_{visit.key}_{scenario.s}",
                    lowBound=0,
                    upBound=upper,
                )
                bit[(team.r, visit.key, scenario.s)] = pulp.LpVariable(
                    f"Bit_{team.r}_{visit.key}_{scenario.s}",
                    lowBound=0,
                    upBound=upper,
                )
    return bas, bit


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
                        f"link_a_{team.r}_{site.i}_{scenario.s}_{arc.u.key}_{arc.v.key}",
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


def _add_timing(problem, instance: Instance, network: Network, teams, scenarios, Y, bas, bit) -> None:
    """Varış periyodu ve yolda meşguliyet. (4.24), (4.25), (4.28)–(4.33).

    (4.24) ve (4.29)–(4.30) saati periyot kaydına bağlar ve pozitif seyirli
    çevrimi bozar. İş üretimi (4.34) burada kurulmaz. M = H+L.
    """

    length = instance.L
    horizon = network.horizon
    report_m = network.big_m
    into: dict[str, dict[str, list[Arc]]] = {}
    for scenario in scenarios:
        bucket: dict[str, list[Arc]] = {}
        for arc in network.arcs[scenario.s]:
            bucket.setdefault(arc.v.key, []).append(arc)
        into[scenario.s] = bucket

    for scenario in scenarios:
        arcs = network.arcs[scenario.s]
        scenario_into = into[scenario.s]
        for team in teams:
            for visit in network.visits:
                key = (team.r, visit.key, scenario.s)
                yin_arcs = scenario_into.get(visit.key, [])
                yin = pulp.lpSum(
                    Y[(team.r, arc.u.key, arc.v.key, scenario.s)] for arc in yin_arcs
                )
                if visit.kind in {"debris", "center"}:
                    lo, hi = time_window(visit, length)
                    problem += bas[key] >= lo * yin, f"eq_4_24_lo_{team.r}_{visit.key}_{scenario.s}"
                    problem += bas[key] <= bit[key], f"eq_4_24_span_{team.r}_{visit.key}_{scenario.s}"
                    problem += bit[key] <= hi * yin, f"eq_4_24_hi_{team.r}_{visit.key}_{scenario.s}"
                elif visit.kind == "origin":
                    problem += bas[key] == 0, f"eq_4_25_bas_{team.r}_{visit.j}_{scenario.s}"
                    opened = Y.get((team.r, network.sigma.key, visit.key, scenario.s))
                    if opened is not None:
                        problem += (
                            bit[key] <= length * opened,
                            f"eq_4_25_bit_{team.r}_{visit.j}_{scenario.s}",
                        )
                elif visit.kind == "enroute":
                    problem += (
                        bas[key] == horizon * yin,
                        f"eq_4_32_bas_{team.r}_{visit.j}_{scenario.s}",
                    )
                    problem += (
                        bit[key] == horizon * yin,
                        f"eq_4_32_bit_{team.r}_{visit.j}_{scenario.s}",
                    )

            for arc in arcs:
                y = Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                if arc.kind in {"travel", "enroute"}:
                    problem += (
                        y <= route_h(
                            instance,
                            arc.u.physical() or "",
                            arc.v.j if arc.kind == "enroute" else (arc.v.physical() or ""),
                            arc.departure_t or 1,
                            scenario,
                        ),
                        f"eq_4_28_{team.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    )
                if not arc.tam:
                    if arc.kind == "enroute":
                        problem += (
                            bit[(team.r, arc.u.key, scenario.s)] + arc.sey
                            >= horizon - report_m * (1 - y),
                            f"eq_4_33_{team.r}_{arc.u.key}_{arc.v.j}_{scenario.s}",
                        )
                    continue
                if time_window(arc.u, length) is None or time_window(arc.v, length) is None:
                    continue
                tail = (team.r, arc.u.key, scenario.s)
                head = (team.r, arc.v.key, scenario.s)
                problem += (
                    bas[head] >= bit[tail] + arc.sey - report_m * (1 - y),
                    f"eq_4_29_{team.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                )
                problem += (
                    bas[head] <= bit[tail] + arc.sey + report_m * (1 - y),
                    f"eq_4_30_{team.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                )

            for site in instance.sites:
                last = f"d_{site.i}_t{network.periods}"
                end = (team.r, last, network.omega.key, scenario.s)
                if end not in Y or (team.r, last, scenario.s) not in bit:
                    continue
                problem += (
                    bit[(team.r, last, scenario.s)] >= horizon * Y[end],
                    f"eq_4_31_{team.r}_{site.i}_{scenario.s}",
                )


def _add_inventory(problem, instance: Instance, network: Network, teams_of, Y, V):
    """(4.36)–(4.39). Varıştan önce ve ω^yol ile biten dönüş stoka yazılmaz."""

    flow: dict[tuple[str, str, int, str], pulp.LpVariable] = {}
    f_vars: dict[tuple[str, str, str, int, str], pulp.LpVariable] = {}
    centers = [center.j for center in instance.centers]
    sites = [site.i for site in instance.sites]
    for scenario in instance.scenarios:
        har = network.har[scenario.s]
        for (n, n2, t_dep), arc_list in har.items():
            for spec in instance.team_types:
                f_var = pulp.LpVariable(
                    f"f_{spec.k}_{n}_{n2}_t{t_dep}_{scenario.s}",
                    lowBound=0,
                    cat="Integer",
                )
                f_vars[(n, n2, spec.k, t_dep, scenario.s)] = f_var
                problem += (
                    f_var
                    == pulp.lpSum(
                        Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                        for arc in arc_list
                        for team in teams_of[spec.k]
                    ),
                    f"eq_4_36_{spec.k}_{n}_{n2}_{t_dep}_{scenario.s}",
                )
                problem += (
                    f_var <= network.big_m,
                    f"eq_4_27_{spec.k}_{n}_{n2}_{t_dep}_{scenario.s}",
                )
        for left in centers:
            for right in centers:
                if left == right:
                    continue
                for spec in instance.team_types:
                    for t_dep in range(1, network.periods + 1):
                        closed = pulp.LpVariable(
                            f"f_{spec.k}_{left}_{right}_t{t_dep}_{scenario.s}",
                            lowBound=0,
                            upBound=0,
                            cat="Integer",
                        )
                        problem += (
                            closed == 0,
                            f"eq_4_37_{left}_{right}_{spec.k}_{t_dep}_{scenario.s}",
                        )
                        problem += (
                            closed <= 0,
                            f"eq_4_27_{spec.k}_{left}_{right}_{t_dep}_{scenario.s}",
                        )

        for center in instance.centers:
            for spec in instance.team_types:
                flow[(center.j, spec.k, 0, scenario.s)] = pulp.LpVariable(
                    f"I_{spec.k}_{center.j}_t0_{scenario.s}",
                    lowBound=0,
                    cat="Integer",
                )
                problem += (
                    flow[(center.j, spec.k, 0, scenario.s)] == V[(center.j, spec.k)],
                    f"eq_4_39_{center.j}_{spec.k}_{scenario.s}",
                )
                for t_now in range(1, network.periods + 1):
                    flow[(center.j, spec.k, t_now, scenario.s)] = pulp.LpVariable(
                        f"I_{spec.k}_{center.j}_t{t_now}_{scenario.s}",
                        lowBound=0,
                        cat="Integer",
                    )
                    arrived = [
                        Y[(team.r, arc.u.key, arc.v.key, scenario.s)]
                        for ell in range(1, t_now + 1)
                        for arc in network.arrivals[scenario.s].get((center.j, ell), [])
                        for team in teams_of[spec.k]
                    ]
                    left = [
                        f_vars[(center.j, site_i, spec.k, ell, scenario.s)]
                        for site_i in sites
                        for ell in range(1, t_now + 1)
                        if (center.j, site_i, spec.k, ell, scenario.s) in f_vars
                    ]
                    problem += (
                        flow[(center.j, spec.k, t_now, scenario.s)]
                        == V[(center.j, spec.k)]
                        + (pulp.lpSum(arrived) if arrived else 0)
                        - (pulp.lpSum(left) if left else 0),
                        f"eq_4_38_{center.j}_{spec.k}_{t_now}_{scenario.s}",
                    )
    return flow


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
    bas = {key: _as_float(var) for key, var in bundle["bas"].items()}
    bit = {key: _as_float(var) for key, var in bundle["bit"].items()}
    inventory = {key: _as_int(var) for key, var in bundle["I"].items()}
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
    clock: dict[tuple[str, str], list[tuple[str, float | None, float | None]]] = {}
    crossings: list[Crossing] = []
    scenario_of = {scenario.s: scenario for scenario in instance.scenarios}
    for scenario in instance.scenarios:
        for team in teams:
            pairs = chosen.get((team.r, scenario.s), [])
            keys = _trace(pairs)
            if keys is None:
                chains[(team.r, scenario.s)] = []
                clock[(team.r, scenario.s)] = []
            else:
                chains[(team.r, scenario.s)] = [network.by_key[key].label for key in keys]
                row, trips = _clock_and_crossings(
                    instance,
                    network,
                    scenario_of[scenario.s],
                    team.r,
                    keys,
                    pairs,
                    bas,
                    bit,
                )
                clock[(team.r, scenario.s)] = row
                crossings.extend(trips)
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
        horizon=network.horizon,
        reentry_ban=reentry_ban,
        reference_scenario=bundle["reference"],
        teams=teams,
        chains=chains,
        arcs=chosen,
        entries=entries,
        bas=bas,
        bit=bit,
        clock=clock,
        crossings=crossings,
        inventory=inventory,
    )


def _clock_and_crossings(instance, network, scenario, team_r, keys, pairs, bas, bit):
    arc_of = {
        (tail, head): network.by_arc[scenario.s][(tail, head)]
        for tail, head in pairs
    }
    clock = []
    crossings = []
    for index, key in enumerate(keys):
        visit = network.by_key[key]
        if visit.kind in {"sigma", "omega"}:
            clock.append((visit.label, None, None))
        else:
            clock.append(
                (
                    visit.label,
                    bas[(team_r, key, scenario.s)],
                    bit[(team_r, key, scenario.s)],
                )
            )
        if index == 0:
            continue
        arc = arc_of.get((keys[index - 1], key))
        if arc is None or arc.kind not in {"travel", "enroute"}:
            continue
        depart = bit[(team_r, arc.u.key, scenario.s)]
        if arc.kind == "enroute":
            arrive = network.horizon
            arrival_period = None
            horizon = True
            dest = visit.label
        else:
            arrive = bas[(team_r, arc.v.key, scenario.s)]
            arrival_period = arc.v.period()
            horizon = False
            dest = visit.label
        if horizon or arc.crosses:
            beta = _beta_used(instance, scenario, arc)
            crossings.append(
                Crossing(
                    team=team_r,
                    scenario=scenario.s,
                    origin=arc.u.label,
                    dest=dest,
                    depart_h=depart,
                    arrive_h=arrive,
                    sey=arc.sey,
                    departure_period=arc.departure_t or 0,
                    arrival_period=arrival_period,
                    beta=beta,
                    horizon=horizon,
                )
            )
    return clock, crossings


def _beta_used(instance: Instance, scenario, arc: Arc) -> float:
    from model.network import beta_at

    tail = arc.u.physical() or ""
    head = arc.v.j if arc.kind == "enroute" else (arc.v.physical() or "")
    beta = beta_at(instance, scenario, tail, head, arc.departure_t or 1)
    return 0.0 if beta is None else beta


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
