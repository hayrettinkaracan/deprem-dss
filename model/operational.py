"""Operasyonel yeniden çözüm. Rapor (4.5) ve (4.35).

G sabittir. (4.7)–(4.13), (4.23)–(4.25) ve (4.28) kurulmaz. Dönüş yayı yalnız
en yakın açık ve ulaşılabilir merkeze konur. Serbest ekibin çıkış saati ve
başlangıç kaydından ilk gerçek hedefi senaryolar arasında ortaktır. Geçmiş yay
değişken değildir; grafik t0'da başlar.
"""

from __future__ import annotations

import tempfile

import pulp

from model.instance import Instance
from model.network import Arc, Visit, horizon_hours, route_h, travel_sey
from model.planning import (
    ETA,
    PlanningSolution,
    _excerpt,
    _is_har,
    _log_stats,
    _trace,
)
from model.planning_network import PlanningNetwork, has_time, movement_m, planning_arrivals
from model.staff import GROUPS, Resource, Staff, can_serve, group_load

TIME_TOL = 1e-6


class TeamState:
    """Ekibin yeniden çözüm anındaki hali. b_key ziyaret anahtarıdır."""

    def __init__(
        self,
        resource: Resource,
        b_key: str,
        e_r: float,
        free: bool,
        left_sites: frozenset[str] | set[str] = frozenset(),
    ):
        self.resource = resource
        self.b_key = b_key
        self.e_r = e_r
        self.free = free
        self.left_sites = frozenset(left_sites)


class OperationalState:
    """t0, θ, sabit açık merkezler, ekip başlangıcı ve R̄."""

    def __init__(
        self,
        t0: int,
        theta: float,
        open_centers: frozenset[str] | set[str],
        teams: list[TeamState],
        remaining: dict[tuple[str, str, str], float],
    ):
        self.t0 = t0
        self.theta = theta
        self.open_centers = frozenset(open_centers)
        self.teams = teams
        self.remaining = remaining


def nearest_open_center(
    instance: Instance,
    scenario,
    site_i: str,
    t: int,
    open_centers: frozenset[str],
) -> tuple[str, float] | None:
    """En yakın açık ve h=1 merkez. Eşit sürede küçük indis önce."""

    index = {center.j: place for place, center in enumerate(instance.centers)}
    best: tuple[tuple[float, int], str, float] | None = None
    for center_j in open_centers:
        if route_h(instance, site_i, center_j, t, scenario) != 1:
            continue
        sey = travel_sey(instance, site_i, center_j, t, scenario)
        if sey is None:
            continue
        rank = (sey, index[center_j])
        if best is None or rank < best[0]:
            best = (rank, center_j, sey)
    if best is None:
        return None
    return best[1], best[2]


def build_operational_network(
    instance: Instance,
    last_period: int,
    state: OperationalState,
) -> PlanningNetwork:
    """σ yalnız b_r'ye gider. Ayrılmış enkaza yay yok. Dönüş tek merkeze."""

    if state.t0 < 1 or state.t0 > last_period:
        raise ValueError("t0 ufuk içinde olmalı")
    if abs(state.theta - instance.L * (state.t0 - 1)) > 1e-6:
        raise ValueError("θ = L(t0−1) olmalı")
    length = instance.L
    horizon = horizon_hours(last_period, length)
    sigma = Visit("sigma")
    omega = Visit("omega")
    debris = [
        Visit("debris", i=site.i, t=t)
        for site in instance.sites
        for t in range(state.t0, last_period + 1)
    ]
    debris_at = {(visit.i, visit.t): visit for visit in debris}
    center_visits = [
        Visit("center", j=center_j, t=t, ell=1)
        for center_j in state.open_centers
        for t in range(state.t0, last_period + 1)
    ]
    center_at = {(visit.j, visit.t): visit for visit in center_visits}
    visits = debris + center_visits
    by_key = {sigma.key: sigma, omega.key: omega}
    for visit in visits:
        by_key[visit.key] = visit
    site_of = {site.i: site for site in instance.sites}
    by_arc: dict[str, dict[tuple[str, str], Arc]] = {}
    team_arcs: dict[str, dict[str, list[Arc]]] = {}

    for scenario in instance.scenarios:
        found: dict[tuple[str, str], Arc] = {}
        chosen: dict[str, list[Arc]] = {}

        def allow(resource: Resource, arc: Arc) -> None:
            existing = found.get(arc.key)
            if existing is None:
                found[arc.key] = arc
                existing = arc
            bucket = chosen.setdefault(resource.r, [])
            if existing.key not in {item.key for item in bucket}:
                bucket.append(existing)

        for team in state.teams:
            if team.b_key not in by_key:
                raise ValueError(f"başlangıç kaydı yok: {team.b_key}")
            start = by_key[team.b_key]
            window = _window(start, length)
            if window is None or not window[0] - 1e-6 <= team.e_r <= window[1] + 1e-6:
                raise ValueError(f"{team.resource.r} e_r pencerenin dışında")
            allow(team.resource, Arc(sigma, start, "start"))
            stack = [start]
            seen = {start.key}
            while stack:
                node = stack.pop()
                if node.kind == "center" or (node.kind == "debris" and node.t == last_period):
                    allow(team.resource, Arc(node, omega, "end", departure_t=node.period()))
                if node.kind == "center" and node.t < last_period:
                    nxt = center_at[(node.j, node.t + 1)]
                    allow(
                        team.resource,
                        Arc(node, nxt, "wait", sey=0.0, departure_t=node.t, m_uv=0.0),
                    )
                    if nxt.key not in seen:
                        seen.add(nxt.key)
                        stack.append(nxt)
                if node.kind == "debris" and node.t < last_period:
                    nxt = debris_at[(node.i, node.t + 1)]
                    allow(
                        team.resource,
                        Arc(node, nxt, "continue", sey=0.0, departure_t=node.t, m_uv=0.0),
                    )
                    if nxt.key not in seen:
                        seen.add(nxt.key)
                        stack.append(nxt)
                origin = node.physical()
                t_dep = node.period()
                if origin is None or t_dep is None:
                    continue
                for site in instance.sites:
                    if site.i in team.left_sites or site.i == origin:
                        continue
                    if not can_serve(instance, team.resource, site):
                        continue
                    if route_h(instance, origin, site.i, t_dep, scenario) != 1:
                        continue
                    sey = travel_sey(instance, origin, site.i, t_dep, scenario)
                    if sey is None:
                        continue
                    for t_arr in planning_arrivals(t_dep, last_period):
                        if t_arr < state.t0:
                            continue
                        head = debris_at[(site.i, t_arr)]
                        allow(
                            team.resource,
                            Arc(
                                node,
                                head,
                                "travel",
                                sey=sey,
                                departure_t=t_dep,
                                m_uv=movement_m(node, head, sey, length),
                            ),
                        )
                        if head.key not in seen:
                            seen.add(head.key)
                            stack.append(head)
                if node.kind == "debris":
                    nearest = nearest_open_center(
                        instance, scenario, node.i, node.t, state.open_centers
                    )
                    if nearest is None:
                        continue
                    center_j, sey = nearest
                    for t_arr in planning_arrivals(node.t, last_period):
                        head = center_at[(center_j, t_arr)]
                        allow(
                            team.resource,
                            Arc(
                                node,
                                head,
                                "travel",
                                sey=sey,
                                departure_t=node.t,
                                m_uv=movement_m(node, head, sey, length),
                            ),
                        )
                        if head.key not in seen:
                            seen.add(head.key)
                            stack.append(head)

        by_arc[scenario.s] = found
        team_arcs[scenario.s] = chosen

    return PlanningNetwork(
        periods=last_period,
        horizon=horizon,
        sigma=sigma,
        omega=omega,
        visits=visits,
        by_key=by_key,
        by_arc=by_arc,
        team_arcs=team_arcs,
    )


def solve_operational(
    instance: Instance,
    last_period: int,
    state: OperationalState,
    time_limit: int = 15,
    delta: float = 0.001,
    vartheta: float = 0.01,
    eta: float = ETA,
    threads: int = 1,
) -> PlanningSolution:
    """(4.5): min Z1 + δ Σ P Sey Y. ε yok."""

    network = build_operational_network(instance, last_period, state)
    staff = Staff(tuple(team.resource for team in state.teams))
    problem = _build(instance, network, state, staff, delta, vartheta, eta)
    log_path = tempfile.NamedTemporaryFile(prefix="cbc-op-", suffix=".log", delete=False).name
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=0, threads=threads, logPath=log_path)
    status_code = problem.solve(solver)
    status = pulp.LpStatus.get(status_code, str(status_code))
    try:
        log_text = open(log_path, encoding="utf-8", errors="replace").read()
    except OSError:
        log_text = ""
    if "stopped on time limit" in log_text.lower():
        status = "Time limit"
    return _extract(instance, network, staff, state, problem, status, log_text)


def _window(visit: Visit, length: float) -> tuple[float, float] | None:
    period = visit.period()
    if period is None:
        return None
    return (length * (period - 1), length * period)


def _build(instance, network, state: OperationalState, staff: Staff, delta, vartheta, eta):
    problem = pulp.LpProblem("Deprem_Operasyonel", pulp.LpMinimize)
    length = instance.L
    horizon = network.horizon
    t0 = state.t0
    last = network.periods
    reference = instance.scenarios[0].s
    sigma = network.sigma.key
    omega = network.omega.key
    team_of = {team.resource.r: team for team in state.teams}
    Y: dict[tuple[str, str, str, str], pulp.LpVariable] = {}
    incoming: dict[tuple[str, str, str], list[Arc]] = {}
    outgoing: dict[tuple[str, str, str], list[Arc]] = {}
    for scenario in instance.scenarios:
        for team in state.teams:
            for arc in network.team_arcs[scenario.s].get(team.resource.r, []):
                Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)] = pulp.LpVariable(
                    f"Y_{team.resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    cat="Binary",
                )
                incoming.setdefault((team.resource.r, arc.v.key, scenario.s), []).append(arc)
                outgoing.setdefault((team.resource.r, arc.u.key, scenario.s), []).append(arc)

    clock: dict[tuple[str, str, str], tuple[pulp.LpVariable, pulp.LpVariable]] = {}
    for scenario in instance.scenarios:
        for team in state.teams:
            keys = set()
            for arc in network.team_arcs[scenario.s].get(team.resource.r, []):
                if has_time(arc.u):
                    keys.add(arc.u.key)
                if has_time(arc.v):
                    keys.add(arc.v.key)
            for key in keys:
                visit = network.by_key[key]
                bas = pulp.LpVariable(f"Bas_{team.resource.r}_{key}_{scenario.s}", lowBound=0)
                bit = pulp.LpVariable(f"Bit_{team.resource.r}_{key}_{scenario.s}", lowBound=0)
                clock[(team.resource.r, key, scenario.s)] = (bas, bit)
                if key == team.b_key:
                    hi = length * visit.period()
                    problem += bas == team.e_r, f"eq_4_31_bas_{team.resource.r}_{key}_{scenario.s}"
                    problem += bit >= team.e_r, f"eq_4_31_lo_{team.resource.r}_{key}_{scenario.s}"
                    problem += bit <= hi, f"eq_4_31_hi_{team.resource.r}_{key}_{scenario.s}"
                elif visit.kind in {"debris", "center"}:
                    lo, hi = _window(visit, length)
                    problem += bas >= lo, f"eq_4_30_lo_{team.resource.r}_{key}_{scenario.s}"
                    problem += bas <= bit, f"eq_4_30_order_{team.resource.r}_{key}_{scenario.s}"
                    problem += bit <= hi, f"eq_4_30_hi_{team.resource.r}_{key}_{scenario.s}"
                    arrived = incoming.get((team.resource.r, key, scenario.s), [])
                    problem += (
                        bit - bas
                        <= length
                        * pulp.lpSum(Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in arrived),
                        f"eq_4_30_dur_{team.resource.r}_{key}_{scenario.s}",
                    )

    R = {}
    q = {}
    for scenario in instance.scenarios:
        for site in instance.sites:
            for group in GROUPS:
                R[(group, site.i, t0, scenario.s)] = pulp.LpVariable(
                    f"R_{group}_{site.i}_t{t0}_{scenario.s}", lowBound=0
                )
                problem += (
                    R[(group, site.i, t0, scenario.s)]
                    == state.remaining.get((group, site.i, scenario.s), 0.0),
                    f"eq_4_14_{group}_{site.i}_{scenario.s}",
                )
                for t in range(t0, last + 1):
                    q[(group, site.i, t, scenario.s)] = pulp.LpVariable(
                        f"q_{group}_{site.i}_t{t}_{scenario.s}", lowBound=0
                    )
                    if t > t0:
                        R[(group, site.i, t, scenario.s)] = pulp.LpVariable(
                            f"R_{group}_{site.i}_t{t}_{scenario.s}", lowBound=0
                        )
                        problem += (
                            R[(group, site.i, t, scenario.s)]
                            == R[(group, site.i, t - 1, scenario.s)]
                            - q[(group, site.i, t - 1, scenario.s)],
                            f"eq_4_15_{group}_{site.i}_t{t-1}_{scenario.s}",
                        )
                    problem += (
                        q[(group, site.i, t, scenario.s)] <= R[(group, site.i, t, scenario.s)],
                        f"eq_4_16_{group}_{site.i}_t{t}_{scenario.s}",
                    )
                    record = f"d_{site.i}_t{t}"
                    terms = []
                    for team in state.teams:
                        if team.resource.group != group:
                            continue
                        stamp = clock.get((team.resource.r, record, scenario.s))
                        if stamp is None:
                            continue
                        terms.append(team.resource.p * (stamp[1] - stamp[0]))
                    problem += (
                        q[(group, site.i, t, scenario.s)] == (pulp.lpSum(terms) if terms else 0),
                        f"eq_4_17_{group}_{site.i}_t{t}_{scenario.s}",
                    )

        for team in state.teams:
            outs = outgoing.get((team.resource.r, sigma, scenario.s), [])
            problem += (
                pulp.lpSum(Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in outs) == 1,
                f"eq_4_20_{team.resource.r}_{scenario.s}",
            )
            ins = incoming.get((team.resource.r, omega, scenario.s), [])
            problem += (
                pulp.lpSum(Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in ins) == 1,
                f"eq_4_21_{team.resource.r}_{scenario.s}",
            )
            touched = set()
            for arc in network.team_arcs[scenario.s].get(team.resource.r, []):
                touched.add(arc.u.key)
                touched.add(arc.v.key)
            touched.discard(sigma)
            touched.discard(omega)
            for key in touched:
                arrived = incoming.get((team.resource.r, key, scenario.s), [])
                left = outgoing.get((team.resource.r, key, scenario.s), [])
                arrived_sum = pulp.lpSum(
                    Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in arrived
                )
                left_sum = pulp.lpSum(
                    Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in left
                )
                problem += arrived_sum == left_sum, f"eq_4_22_{team.resource.r}_{key}_{scenario.s}"
                problem += arrived_sum <= 1, f"eq_4_22_le_{team.resource.r}_{key}_{scenario.s}"

        for team in state.teams:
            if not team.free or scenario.s == reference:
                continue
            bas_ref, bit_ref = clock[(team.resource.r, team.b_key, reference)]
            _bas, bit_s = clock[(team.resource.r, team.b_key, scenario.s)]
            problem += bit_s == bit_ref, f"eq_4_35_bit_{team.resource.r}_{scenario.s}"
            destinations = set()
            for arc in outgoing.get((team.resource.r, team.b_key, reference), []):
                if _is_har(arc) and arc.v.physical():
                    destinations.add(arc.v.physical())
            for arc in outgoing.get((team.resource.r, team.b_key, scenario.s), []):
                if _is_har(arc) and arc.v.physical():
                    destinations.add(arc.v.physical())
            home = network.by_key[team.b_key].physical()
            for dest in destinations:
                if dest == home:
                    continue
                left_sum = _har_to(Y, outgoing, team.resource.r, team.b_key, reference, dest)
                right_sum = _har_to(Y, outgoing, team.resource.r, team.b_key, scenario.s, dest)
                problem += (
                    left_sum == right_sum,
                    f"eq_4_35_dest_{team.resource.r}_{dest}_{scenario.s}",
                )

        for team in state.teams:
            for arc in network.team_arcs[scenario.s].get(team.resource.r, []):
                y = Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)]
                if arc.v.kind == "debris" and arc.u.kind != "sigma":
                    problem += (
                        vartheta * y <= R[(team.resource.group, arc.v.i, arc.v.t, scenario.s)],
                        f"eq_4_18_{team.resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    )
                if arc.kind != "travel" or arc.m_uv is None:
                    continue
                tail = clock.get((team.resource.r, arc.u.key, scenario.s))
                head = clock.get((team.resource.r, arc.v.key, scenario.s))
                if tail is None or head is None:
                    continue
                problem += (
                    head[0] >= tail[1] + arc.sey - arc.m_uv * (1 - y),
                    f"eq_4_32_{team.resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                )

    z1_terms = []
    for scenario in instance.scenarios:
        for site in instance.sites:
            for t in range(t0, last + 1):
                for group in GROUPS:
                    z1_terms.append(
                        scenario.P
                        * site.gamma
                        * (R[(group, site.i, t, scenario.s)] - q[(group, site.i, t, scenario.s)])
                    )
    travel_terms = []
    for scenario in instance.scenarios:
        for team in state.teams:
            for arc in network.team_arcs[scenario.s].get(team.resource.r, []):
                if _is_har(arc):
                    y = Y[(team.resource.r, arc.u.key, arc.v.key, scenario.s)]
                    travel_terms.append(scenario.P * arc.sey * y)
    z1_expr = pulp.lpSum(z1_terms) if z1_terms else 0
    travel_expr = pulp.lpSum(travel_terms) if travel_terms else 0
    problem += z1_expr + delta * travel_expr
    problem._op_bundle = {
        "Y": Y,
        "clock": clock,
        "R": R,
        "q": q,
        "z1": z1_expr,
    }
    return problem


def _har_to(Y, outgoing, resource_r, origin, scenario_s, dest):
    terms = []
    for arc in outgoing.get((resource_r, origin, scenario_s), []):
        if _is_har(arc) and arc.v.physical() == dest:
            terms.append(Y[(resource_r, arc.u.key, arc.v.key, scenario_s)])
    return pulp.lpSum(terms) if terms else 0


def _extract(instance, network, staff, state, problem, status, log_text) -> PlanningSolution:
    bundle = problem._op_bundle
    seconds, gap, lower_bound = _log_stats(log_text, status)
    objective = pulp.value(problem.objective)
    if objective is None or "no feasible solution found" in log_text.lower():
        return PlanningSolution(
            status=status,
            objective=None,
            z1_by_scenario={},
            gap=gap,
            lower_bound=lower_bound,
            seconds=seconds,
            G={center: 1 if center in state.open_centers else 0 for center in (c.j for c in instance.centers)},
            V={},
            VU={},
            VW={},
            periods=network.periods,
            horizon=network.horizon,
            teams=list(staff.resources),
            log_excerpt=_excerpt(log_text),
        )

    def num(var):
        value = pulp.value(var)
        return 0.0 if value is None else float(value)

    bas, bit = {}, {}
    for key, (bas_var, bit_var) in bundle["clock"].items():
        bas[key] = num(bas_var)
        bit[key] = num(bit_var)
    q = {key: num(var) for key, var in bundle["q"].items()}
    R = {key: num(var) for key, var in bundle["R"].items()}
    z1_by = {}
    for scenario in instance.scenarios:
        total = 0.0
        for site in instance.sites:
            for t in range(state.t0, network.periods + 1):
                for group in GROUPS:
                    total += site.gamma * (
                        R[(group, site.i, t, scenario.s)] - q[(group, site.i, t, scenario.s)]
                    )
        z1_by[scenario.s] = total
    chosen, chains = {}, {}
    for scenario in instance.scenarios:
        for team in state.teams:
            pairs = []
            for arc in network.team_arcs[scenario.s].get(team.resource.r, []):
                var = bundle["Y"].get((team.resource.r, arc.u.key, arc.v.key, scenario.s))
                if var is not None and num(var) > 0.5:
                    pairs.append((arc.u.key, arc.v.key))
            chosen[(team.resource.r, scenario.s)] = pairs
            keys = _trace(pairs)
            chains[(team.resource.r, scenario.s)] = (
                [] if keys is None else [network.by_key[key].label for key in keys]
            )
    z1_value = pulp.value(bundle["z1"])
    return PlanningSolution(
        status=status,
        objective=float(objective),
        z1_by_scenario=z1_by,
        gap=gap,
        lower_bound=lower_bound,
        seconds=seconds,
        G={center.j: 1 if center.j in state.open_centers else 0 for center in instance.centers},
        V={},
        VU={},
        VW={},
        periods=network.periods,
        horizon=network.horizon,
        teams=list(staff.resources),
        chains=chains,
        arcs=chosen,
        bas=bas,
        bit=bit,
        q=q,
        R=R,
        log_excerpt=_excerpt(log_text),
        z1=None if z1_value is None else float(z1_value),
    )
