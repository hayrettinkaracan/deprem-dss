"""Planlama modeli. Amaç yalnız Z1 (4.2).

Kısıtlar (4.7)–(4.27), (4.30)–(4.32) ve (4.34). (4.1) ve (4.29) yayların
süresi ve h süzgecidir; (4.33) M_uv olarak yaydadır. (4.32) yalnız alt
sınırdır. (4.28), Z2 ve ε bu çözümde yoktur.

Eski u amacı, p·L işi, f/I envanteri ve lex sıra bozma burada yoktur.
Arayüz hâlâ eski çözücüyü çağırır; canlı veride grup işi ve kadro yoktur.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field

import pulp

from model.instance import Instance, validate
from model.network import Arc
from model.planning_network import PlanningNetwork, build_planning_network, has_time
from model.staff import (
    GROUP_A,
    GROUP_U,
    GROUP_W,
    GROUPS,
    Resource,
    Staff,
    group_load,
    planning_staff,
)

ETA = 0.2
TIME_TOL = 1e-6


@dataclass
class PlanningSolution:
    status: str
    objective: float | None
    z1_by_scenario: dict[str, float]
    gap: float | None
    lower_bound: float | None
    seconds: float | None
    G: dict[str, int]
    V: dict[tuple[str, str], int]
    VU: dict[str, int]
    VW: dict[str, int]
    periods: int
    horizon: float
    teams: list[Resource]
    chains: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    arcs: dict[tuple[str, str], list[tuple[str, str]]] = field(default_factory=dict)
    bas: dict[tuple[str, str, str], float] = field(default_factory=dict)
    bit: dict[tuple[str, str, str], float] = field(default_factory=dict)
    q: dict[tuple[str, str, int, str], float] = field(default_factory=dict)
    R: dict[tuple[str, str, int, str], float] = field(default_factory=dict)
    log_excerpt: str = ""


def solve_planning(
    instance: Instance,
    periods: int = 36,
    time_limit: int = 120,
    vartheta: float = 0.01,
    eta: float = ETA,
    solver: pulp.LpSolver | None = None,
) -> PlanningSolution:
    """Üç senaryolu planlama. time_limit saniye; boşluk gizlenmez."""

    validate(instance)
    staff = planning_staff(instance)
    network = build_planning_network(instance, periods, staff)
    problem = _build(instance, network, staff, vartheta, eta)
    own_solver = solver is None
    if solver is None:
        log_path = "/tmp/cbc-plan.log"
        solver = pulp.PULP_CBC_CMD(
            msg=False,
            timeLimit=time_limit,
            gapRel=0,
            threads=1,
            warmStart=True,
            logPath=log_path,
            options=["cuts off", "preprocess off", "heuristics on"],
        )
    else:
        log_path = ""
    status_code = problem.solve(solver)
    status = pulp.LpStatus.get(status_code, str(status_code))
    log_text = ""
    if own_solver and log_path:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as handle:
                log_text = handle.read()
        except OSError:
            log_text = ""
    return _extract(instance, network, staff, problem, status, log_text)


def constraint_names(
    instance: Instance,
    periods: int = 1,
    vartheta: float = 0.01,
    eta: float = ETA,
) -> set[str]:
    staff = planning_staff(instance)
    network = build_planning_network(instance, periods, staff)
    problem = _build(instance, network, staff, vartheta, eta)
    return set(problem.constraints)


def _build(
    instance: Instance,
    network: PlanningNetwork,
    staff: Staff,
    vartheta: float,
    eta: float,
) -> pulp.LpProblem:
    problem = pulp.LpProblem("Deprem_Z1", pulp.LpMinimize)
    length = instance.L
    horizon = network.horizon
    periods = network.periods
    reference = instance.scenarios[0].s
    sigma = network.sigma.key
    omega = network.omega.key
    afad = {
        spec.k: tuple(resource for resource in staff.of(GROUP_A) if resource.k == spec.k)
        for spec in instance.team_types
    }
    by_group = {group: staff.of(group) for group in GROUPS}

    G = {center.j: pulp.LpVariable(f"G_{center.j}", cat="Binary") for center in instance.centers}
    V = {
        (center.j, spec.k): pulp.LpVariable(f"V_{center.j}_{spec.k}", lowBound=0, cat="Integer")
        for center in instance.centers
        for spec in instance.team_types
    }
    VU = {center.j: pulp.LpVariable(f"VU_{center.j}", lowBound=0, cat="Integer") for center in instance.centers}
    VW = {center.j: pulp.LpVariable(f"VW_{center.j}", lowBound=0, cat="Integer") for center in instance.centers}

    Y: dict[tuple[str, str, str, str], pulp.LpVariable] = {}
    incoming: dict[tuple[str, str, str], list[Arc]] = {}
    outgoing: dict[tuple[str, str, str], list[Arc]] = {}
    for scenario in instance.scenarios:
        for resource in staff.resources:
            for arc in network.team_arcs[scenario.s][resource.r]:
                Y[(resource.r, arc.u.key, arc.v.key, scenario.s)] = pulp.LpVariable(
                    f"Y_{resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    cat="Binary",
                )
                incoming.setdefault((resource.r, arc.v.key, scenario.s), []).append(arc)
                outgoing.setdefault((resource.r, arc.u.key, scenario.s), []).append(arc)

    clock: dict[tuple[str, str, str], tuple[pulp.LpVariable, pulp.LpVariable]] = {}
    for scenario in instance.scenarios:
        for resource in staff.resources:
            keys = set()
            for arc in network.team_arcs[scenario.s][resource.r]:
                if has_time(arc.u):
                    keys.add(arc.u.key)
                if has_time(arc.v):
                    keys.add(arc.v.key)
            for key in keys:
                visit = network.by_key[key]
                bas = pulp.LpVariable(f"Bas_{resource.r}_{key}_{scenario.s}", lowBound=0)
                bit = pulp.LpVariable(f"Bit_{resource.r}_{key}_{scenario.s}", lowBound=0)
                clock[(resource.r, key, scenario.s)] = (bas, bit)
                if visit.kind in {"debris", "center"}:
                    lo, hi = length * (visit.period() - 1), length * visit.period()
                    problem += bas >= lo, f"eq_4_30_lo_{resource.r}_{key}_{scenario.s}"
                    problem += bas <= bit, f"eq_4_30_order_{resource.r}_{key}_{scenario.s}"
                    problem += bit <= hi, f"eq_4_30_hi_{resource.r}_{key}_{scenario.s}"
                    arrived = incoming.get((resource.r, key, scenario.s), [])
                    problem += (
                        bit - bas
                        <= length * pulp.lpSum(Y[(resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in arrived),
                        f"eq_4_30_dur_{resource.r}_{key}_{scenario.s}",
                    )

    R = {
        (group, site.i, t, scenario.s): pulp.LpVariable(
            f"R_{group}_{site.i}_t{t}_{scenario.s}", lowBound=0
        )
        for group in GROUPS
        for site in instance.sites
        for t in range(1, periods + 1)
        for scenario in instance.scenarios
    }
    q = {
        (group, site.i, t, scenario.s): pulp.LpVariable(
            f"q_{group}_{site.i}_t{t}_{scenario.s}", lowBound=0
        )
        for group in GROUPS
        for site in instance.sites
        for t in range(1, periods + 1)
        for scenario in instance.scenarios
    }

    for center in instance.centers:
        for spec in instance.team_types:
            problem += (
                V[(center.j, spec.k)] <= center.C[spec.k] * G[center.j],
                f"eq_4_7_{center.j}_{spec.k}",
            )
        problem += VU[center.j] <= center.U_max * G[center.j], f"eq_4_8_{center.j}"
        problem += VW[center.j] <= center.W_max * G[center.j], f"eq_4_9_{center.j}"
    problem += pulp.lpSum(G[center.j] for center in instance.centers) <= instance.N_max, "eq_4_10_Nmax"
    for spec in instance.team_types:
        problem += (
            pulp.lpSum(V[(center.j, spec.k)] for center in instance.centers) <= spec.A,
            f"eq_4_11_{spec.k}",
        )
    problem += pulp.lpSum(VU[center.j] for center in instance.centers) <= instance.U_top, "eq_4_12_U"
    problem += pulp.lpSum(VW[center.j] for center in instance.centers) <= instance.W_top, "eq_4_13_W"

    for scenario in instance.scenarios:
        for site in instance.sites:
            for group in GROUPS:
                problem += (
                    R[(group, site.i, 1, scenario.s)] == group_load(site, group),
                    f"eq_4_14_{group}_{site.i}_{scenario.s}",
                )
                for t in range(1, periods):
                    problem += (
                        R[(group, site.i, t + 1, scenario.s)]
                        == R[(group, site.i, t, scenario.s)] - q[(group, site.i, t, scenario.s)],
                        f"eq_4_15_{group}_{site.i}_t{t}_{scenario.s}",
                    )
                for t in range(1, periods + 1):
                    problem += (
                        q[(group, site.i, t, scenario.s)] <= R[(group, site.i, t, scenario.s)],
                        f"eq_4_16_{group}_{site.i}_t{t}_{scenario.s}",
                    )
                    terms = []
                    record = f"d_{site.i}_t{t}"
                    for resource in by_group[group]:
                        stamp = clock.get((resource.r, record, scenario.s))
                        if stamp is None:
                            continue
                        bas, bit = stamp
                        terms.append(resource.p * (bit - bas))
                    problem += (
                        q[(group, site.i, t, scenario.s)] == (pulp.lpSum(terms) if terms else 0),
                        f"eq_4_17_{group}_{site.i}_t{t}_{scenario.s}",
                    )

        for resource in staff.resources:
            outs = outgoing.get((resource.r, sigma, scenario.s), [])
            problem += (
                pulp.lpSum(Y[(resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in outs) == 1,
                f"eq_4_20_{resource.r}_{scenario.s}",
            )
            ins = incoming.get((resource.r, omega, scenario.s), [])
            problem += (
                pulp.lpSum(Y[(resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in ins) == 1,
                f"eq_4_21_{resource.r}_{scenario.s}",
            )
            touched = set()
            for arc in network.team_arcs[scenario.s][resource.r]:
                touched.add(arc.u.key)
                touched.add(arc.v.key)
            touched.discard(sigma)
            touched.discard(omega)
            for key in touched:
                arrived = incoming.get((resource.r, key, scenario.s), [])
                left = outgoing.get((resource.r, key, scenario.s), [])
                arrived_sum = pulp.lpSum(
                    Y[(resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in arrived
                )
                left_sum = pulp.lpSum(Y[(resource.r, arc.u.key, arc.v.key, scenario.s)] for arc in left)
                problem += arrived_sum == left_sum, f"eq_4_22_{resource.r}_{key}_{scenario.s}"
                problem += arrived_sum <= 1, f"eq_4_22_le_{resource.r}_{key}_{scenario.s}"

            for site in instance.sites:
                entries = [
                    Y[(resource.r, arc.u.key, arc.v.key, scenario.s)]
                    for arc in network.team_arcs[scenario.s][resource.r]
                    if _is_physical_entry(arc, site.i)
                ]
                if entries:
                    problem += (
                        pulp.lpSum(entries) <= 1,
                        f"eq_4_26_{resource.r}_{site.i}_{scenario.s}",
                    )
                for t in range(1, periods + 1):
                    record = f"d_{site.i}_t{t}"
                    har = [
                        Y[(resource.r, arc.u.key, arc.v.key, scenario.s)]
                        for arc in outgoing.get((resource.r, record, scenario.s), [])
                        if _is_har(arc)
                    ]
                    if not har:
                        continue
                    load = group_load(site, resource.group)
                    problem += (
                        R[(resource.group, site.i, t, scenario.s)] - q[(resource.group, site.i, t, scenario.s)]
                        <= load * (1 - pulp.lpSum(har)),
                        f"eq_4_27_{resource.r}_{site.i}_t{t}_{scenario.s}",
                    )

        for center in instance.centers:
            origin = f"o_{center.j}"
            for spec in instance.team_types:
                problem += (
                    V[(center.j, spec.k)]
                    == pulp.lpSum(
                        Y[(resource.r, sigma, origin, scenario.s)]
                        for resource in afad[spec.k]
                        if (resource.r, sigma, origin, scenario.s) in Y
                    ),
                    f"eq_4_23_{center.j}_{spec.k}_{scenario.s}",
                )
            problem += (
                VU[center.j]
                == pulp.lpSum(
                    Y[(resource.r, sigma, origin, scenario.s)]
                    for resource in by_group[GROUP_U]
                    if (resource.r, sigma, origin, scenario.s) in Y
                ),
                f"eq_4_24_U_{center.j}_{scenario.s}",
            )
            problem += (
                VW[center.j]
                == pulp.lpSum(
                    Y[(resource.r, sigma, origin, scenario.s)]
                    for resource in by_group[GROUP_W]
                    if (resource.r, sigma, origin, scenario.s) in Y
                ),
                f"eq_4_24_W_{center.j}_{scenario.s}",
            )
            if scenario.s != reference:
                for resource in staff.resources:
                    if (resource.r, sigma, origin, scenario.s) not in Y:
                        continue
                    problem += (
                        Y[(resource.r, sigma, origin, scenario.s)]
                        == Y[(resource.r, sigma, origin, reference)],
                        f"eq_4_25_{resource.r}_{center.j}_{scenario.s}",
                    )

        for resource in staff.resources:
            for arc in network.team_arcs[scenario.s][resource.r]:
                y = Y[(resource.r, arc.u.key, arc.v.key, scenario.s)]
                if arc.v.kind == "debris" and arc.u.kind != "sigma":
                    problem += (
                        vartheta * y <= R[(resource.group, arc.v.i, arc.v.t, scenario.s)],
                        f"eq_4_18_{resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    )
                if (
                    resource.group == GROUP_U
                    and arc.v.kind == "debris"
                    and arc.u.kind != "sigma"
                    and arc.u.physical() != arc.v.i
                ):
                    initial = group_load(next(site for site in instance.sites if site.i == arc.v.i), GROUP_A)
                    gate = min(eta, initial)
                    problem += (
                        initial - R[(GROUP_A, arc.v.i, arc.v.t, scenario.s)] >= gate * y,
                        f"eq_4_19_{resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                    )
                if arc.kind != "travel" or arc.m_uv is None:
                    continue
                tail = clock.get((resource.r, arc.u.key, scenario.s))
                head = clock.get((resource.r, arc.v.key, scenario.s))
                if tail is None or head is None:
                    continue
                problem += (
                    head[0] >= tail[1] + arc.sey - arc.m_uv * (1 - y),
                    f"eq_4_32_{resource.r}_{arc.u.key}_{arc.v.key}_{scenario.s}",
                )
            for site in instance.sites:
                last = f"d_{site.i}_t{periods}"
                end = (resource.r, last, omega, scenario.s)
                stamp = clock.get((resource.r, last, scenario.s))
                if end not in Y or stamp is None:
                    continue
                problem += (
                    stamp[1] >= horizon * Y[end],
                    f"eq_4_34_{resource.r}_{site.i}_{scenario.s}",
                )
            for center in instance.centers:
                origin = f"o_{center.j}"
                stamp = clock.get((resource.r, origin, scenario.s))
                link = (resource.r, sigma, origin, scenario.s)
                if stamp is None or link not in Y:
                    continue
                bas, bit = stamp
                problem += bas == 0, f"eq_4_31_bas_{resource.r}_{origin}_{scenario.s}"
                problem += bit >= bas, f"eq_4_31_order_{resource.r}_{origin}_{scenario.s}"
                problem += (
                    bit <= length * Y[link],
                    f"eq_4_31_bit_{resource.r}_{origin}_{scenario.s}",
                )

    objective = []
    for scenario in instance.scenarios:
        for site in instance.sites:
            if site.gamma is None:
                raise ValueError(f"γ_{site.i} yok")
            for t in range(1, periods + 1):
                for group in GROUPS:
                    objective.append(
                        scenario.P
                        * site.gamma
                        * (R[(group, site.i, t, scenario.s)] - q[(group, site.i, t, scenario.s)])
                    )
    problem += pulp.lpSum(objective)
    bundle = {
        "G": G,
        "V": V,
        "VU": VU,
        "VW": VW,
        "Y": Y,
        "clock": clock,
        "R": R,
        "q": q,
    }
    if network.periods >= 8:
        _worked_start(instance, network, staff, bundle)
    else:
        _idle_start(instance, network, staff, bundle)
    problem._z1_bundle = bundle
    return problem


def _idle_start(instance: Instance, network: PlanningNetwork, staff: Staff, bundle: dict) -> None:
    """Kısa ufukta kapalı merkez ve σ→ω. Yalnız CBC başlangıcıdır."""

    for var in list(bundle["G"].values()) + list(bundle["V"].values()) + list(bundle["VU"].values()) + list(bundle["VW"].values()):
        var.setInitialValue(0)
    active = {
        (resource.r, network.sigma.key, network.omega.key, scenario.s)
        for scenario in instance.scenarios
        for resource in staff.resources
    }
    for key, var in bundle["Y"].items():
        var.setInitialValue(1 if key in active else 0)
    for key, (bas, bit) in bundle["clock"].items():
        visit = network.by_key[key[1]]
        start = 0.0 if visit.kind == "origin" else instance.L * (visit.period() - 1)
        bas.setInitialValue(start)
        bit.setInitialValue(start)
    loads = {(group, site.i): group_load(site, group) for group in GROUPS for site in instance.sites}
    for (group, site_i, _t, scenario_s), var in bundle["R"].items():
        var.setInitialValue(loads[(group, site_i)])
    for var in bundle["q"].values():
        var.setInitialValue(0)


def _worked_start(instance: Instance, network: PlanningNetwork, staff: Staff, bundle: dict) -> None:
    """5.3 için elle kurulmuş geçerli plan. Amaç değildir.

    Süreler en kötü β=0,50 ile sığar; üç senaryoda aynı saatler kullanılır.
    CBC daha iyi bir tamsayı çözüm bulursa onu kullanır.
    """

    visits = _manual_visits()
    placement = {
        "hafif-1": "J2",
        "orta-1": "J1",
        "orta-2": "J2",
        "agir-1": "J1",
        "umke-1": "J1",
        "umke-2": "J2",
        "umke-3": "J2",
        "makine-1": "J1",
        "makine-2": "J2",
    }
    for center in instance.centers:
        bundle["G"][center.j].setInitialValue(1)
    for key, var in bundle["V"].items():
        var.setInitialValue(0)
    for var in bundle["VU"].values():
        var.setInitialValue(0)
    for var in bundle["VW"].values():
        var.setInitialValue(0)
    counts = {("J1", "hafif"): 0, ("J1", "orta"): 1, ("J1", "agir"): 1, ("J2", "hafif"): 1, ("J2", "orta"): 1, ("J2", "agir"): 0}
    for key, count in counts.items():
        bundle["V"][key].setInitialValue(count)
    bundle["VU"]["J1"].setInitialValue(1)
    bundle["VU"]["J2"].setInitialValue(2)
    bundle["VW"]["J1"].setInitialValue(1)
    bundle["VW"]["J2"].setInitialValue(1)

    active: set[tuple[str, str, str, str]] = set()
    clock_value: dict[tuple[str, str, str], tuple[float, float]] = {}
    for scenario in instance.scenarios:
        arcs = network.by_arc[scenario.s]
        for resource in staff.resources:
            steps = visits[resource.r]
            origin = f"o_{placement[resource.r]}"
            active.add((resource.r, network.sigma.key, origin, scenario.s))
            previous = origin
            clock_value[(resource.r, origin, scenario.s)] = (steps[0][2], steps[0][3])
            for kind, ident, bas, bit in steps[1:]:
                head = _visit_key(kind, ident)
                if (previous, head) not in arcs:
                    raise RuntimeError(f"başlangıç yayı yok {resource.r} {previous}->{head} {scenario.s}")
                active.add((resource.r, previous, head, scenario.s))
                clock_value[(resource.r, head, scenario.s)] = (bas, bit)
                previous = head
            if (previous, network.omega.key) not in arcs:
                raise RuntimeError(f"bitiş yayı yok {resource.r} {previous}")
            active.add((resource.r, previous, network.omega.key, scenario.s))

    for key, var in bundle["Y"].items():
        var.setInitialValue(1 if key in active else 0)
    for key, (bas, bit) in bundle["clock"].items():
        if key in clock_value:
            start, end = clock_value[key]
        else:
            visit = network.by_key[key[1]]
            start = 0.0 if visit.kind == "origin" else instance.L * (visit.period() - 1)
            end = start
        bas.setInitialValue(start)
        bit.setInitialValue(end)

    done = {
        (group, site.i, t): 0.0
        for group in GROUPS
        for site in instance.sites
        for t in range(1, network.periods + 1)
    }
    by_id = {resource.r: resource for resource in staff.resources}
    reference = instance.scenarios[0].s
    for resource_r, key, scenario_s in clock_value:
        if scenario_s != reference:
            continue
        visit = network.by_key[key]
        if visit.kind != "debris":
            continue
        resource = by_id[resource_r]
        start, end = clock_value[(resource_r, key, scenario_s)]
        done[(resource.group, visit.i, visit.t)] += resource.p * (end - start)
    loads = {(group, site.i): group_load(site, group) for group in GROUPS for site in instance.sites}
    running = dict(loads)
    for t in range(1, network.periods + 1):
        for group in GROUPS:
            for site in instance.sites:
                work = min(max(0.0, done[(group, site.i, t)]), running[(group, site.i)])
                for scenario in instance.scenarios:
                    bundle["R"][(group, site.i, t, scenario.s)].setInitialValue(running[(group, site.i)])
                    bundle["q"][(group, site.i, t, scenario.s)].setInitialValue(work)
                running[(group, site.i)] -= work


def _visit_key(kind: str, ident: tuple) -> str:
    if kind == "debris":
        site_i, t = ident
        return f"d_{site_i}_t{t}"
    if kind == "center":
        center, t, ell = ident
        return f"c_{center}_t{t}_l{ell}"
    raise ValueError(kind)


def _manual_visits() -> dict[str, list[tuple]]:
    """(kind, ident, bas, bit). İlk kayıt başlangıç merkezidir."""

    return {
        "hafif-1": [
            ("origin", ("J2",), 0.0, 0.0),
            ("debris", ("I4", 1), 1.2, 2.0),
            ("debris", ("I4", 2), 2.0, 2.7),
            ("center", ("J2", 2, 1), 3.9, 3.9),
        ],
        "orta-1": [
            ("origin", ("J1",), 0.0, 0.0),
            ("debris", ("I2", 1), 0.75, 2.0),
            ("debris", ("I2", 2), 2.0, 3.75),
            ("center", ("J1", 3, 1), 4.5, 4.5),
        ],
        "orta-2": [
            ("origin", ("J2",), 0.0, 0.0),
            ("debris", ("I3", 1), 0.75, 2.0),
            ("debris", ("I3", 2), 2.0, 3.25),
            ("center", ("J2", 2, 1), 4.0, 4.0),
        ],
        "agir-1": [
            ("origin", ("J1",), 0.0, 0.0),
            ("debris", ("I1", 1), 1.2, 2.0),
            ("debris", ("I1", 2), 2.0, 4.0),
            ("debris", ("I1", 3), 4.0, 5.2),
            ("debris", ("I5", 4), 7.15, 8.0),
            ("debris", ("I5", 5), 8.0, 10.0),
            ("debris", ("I5", 6), 10.0, 11.65),
            ("center", ("J1", 7, 1), 13.6, 13.6),
        ],
        "umke-1": [
            ("origin", ("J1",), 0.0, 2.0),
            ("debris", ("I1", 2), 3.2, 4.0),
            ("debris", ("I1", 3), 4.0, 4.4),
            ("center", ("J1", 3, 1), 5.6, 5.6),
            ("debris", ("I2", 4), 6.35, 7.25),
            ("center", ("J1", 4, 1), 8.0, 8.0),
        ],
        "umke-2": [
            ("origin", ("J2",), 0.0, 2.0),
            ("debris", ("I3", 2), 2.75, 3.5),
            ("center", ("J2", 3, 1), 4.25, 4.25),
            ("debris", ("I4", 3), 5.45, 5.9),
            ("center", ("J2", 4, 1), 7.1, 7.1),
        ],
        "umke-3": [
            ("origin", ("J2",), 0.0, 0.0),
            ("center", ("J2", 1, 1), 0.0, 2.0),
            ("center", ("J2", 2, 1), 2.0, 4.0),
            ("center", ("J2", 3, 1), 4.0, 6.0),
            ("center", ("J2", 4, 1), 6.0, 8.0),
            ("debris", ("I5", 5), 9.5, 10.0),
            ("debris", ("I5", 6), 10.0, 10.85),
            ("center", ("J2", 7, 1), 12.35, 12.35),
        ],
        "makine-1": [
            ("origin", ("J1",), 0.0, 0.0),
            ("debris", ("I1", 1), 1.2, 2.0),
            ("debris", ("I1", 2), 2.0, 3.2),
            ("center", ("J1", 3, 1), 4.4, 4.4),
            ("debris", ("I2", 3), 5.15, 6.0),
            ("debris", ("I2", 4), 6.0, 6.65),
            ("center", ("J1", 4, 1), 7.4, 7.4),
        ],
        "makine-2": [
            ("origin", ("J2",), 0.0, 0.0),
            ("debris", ("I5", 1), 1.5, 2.0),
            ("debris", ("I5", 2), 2.0, 3.75),
            ("center", ("J2", 3, 1), 5.25, 5.25),
        ],
    }


def _is_physical_entry(arc: Arc, site_i: str) -> bool:
    if arc.v.kind != "debris" or arc.v.i != site_i:
        return False
    origin = arc.u.physical()
    return origin is not None and origin != site_i


def _is_har(arc: Arc) -> bool:
    if arc.u.physical() is None or arc.v.kind == "omega":
        return False
    if arc.kind == "enroute":
        return True
    head = arc.v.physical()
    return head is not None and head != arc.u.physical()


def _extract(
    instance: Instance,
    network: PlanningNetwork,
    staff: Staff,
    problem: pulp.LpProblem,
    status: str,
    log_text: str,
) -> PlanningSolution:
    bundle = problem._z1_bundle
    if "stopped on time limit" in log_text.lower():
        status = "Time limit"
    if "no feasible solution found" in log_text.lower():
        status = "Time limit"
        seconds, gap, lower_bound = _log_stats(log_text, status)
        return PlanningSolution(
            status=status,
            objective=None,
            z1_by_scenario={},
            gap=gap,
            lower_bound=lower_bound,
            seconds=seconds,
            G={},
            V={},
            VU={},
            VW={},
            periods=network.periods,
            horizon=network.horizon,
            teams=list(staff.resources),
            log_excerpt=_excerpt(log_text),
        )
    seconds, gap, lower_bound = _log_stats(log_text, status)
    objective = pulp.value(problem.objective)
    if objective is None:
        return PlanningSolution(
            status=status,
            objective=None,
            z1_by_scenario={},
            gap=gap,
            lower_bound=lower_bound,
            seconds=seconds,
            G={},
            V={},
            VU={},
            VW={},
            periods=network.periods,
            horizon=network.horizon,
            teams=list(staff.resources),
            log_excerpt=_excerpt(log_text),
        )

    def num(var: pulp.LpVariable) -> float:
        value = pulp.value(var)
        return 0.0 if value is None else float(value)

    def whole(var: pulp.LpVariable) -> int:
        return int(round(num(var)))

    G = {key: whole(var) for key, var in bundle["G"].items()}
    V = {key: whole(var) for key, var in bundle["V"].items()}
    VU = {key: whole(var) for key, var in bundle["VU"].items()}
    VW = {key: whole(var) for key, var in bundle["VW"].items()}
    bas: dict[tuple[str, str, str], float] = {}
    bit: dict[tuple[str, str, str], float] = {}
    for key, (bas_var, bit_var) in bundle["clock"].items():
        bas[key] = num(bas_var)
        bit[key] = num(bit_var)
    q = {key: num(var) for key, var in bundle["q"].items()}
    R = {key: num(var) for key, var in bundle["R"].items()}
    z1_by_scenario = {}
    for scenario in instance.scenarios:
        total = 0.0
        for site in instance.sites:
            for t in range(1, network.periods + 1):
                for group in GROUPS:
                    total += site.gamma * (
                        R[(group, site.i, t, scenario.s)] - q[(group, site.i, t, scenario.s)]
                    )
        z1_by_scenario[scenario.s] = total

    chosen: dict[tuple[str, str], list[tuple[str, str]]] = {}
    chains: dict[tuple[str, str], list[str]] = {}
    for scenario in instance.scenarios:
        for resource in staff.resources:
            pairs = []
            for arc in network.team_arcs[scenario.s][resource.r]:
                var = bundle["Y"].get((resource.r, arc.u.key, arc.v.key, scenario.s))
                if var is not None and num(var) > 0.5:
                    pairs.append((arc.u.key, arc.v.key))
            chosen[(resource.r, scenario.s)] = pairs
            keys = _trace(pairs)
            if keys is None:
                chains[(resource.r, scenario.s)] = []
            else:
                chains[(resource.r, scenario.s)] = [network.by_key[key].label for key in keys]
    return PlanningSolution(
        status=status,
        objective=float(objective),
        z1_by_scenario=z1_by_scenario,
        gap=gap,
        lower_bound=lower_bound,
        seconds=seconds,
        G=G,
        V=V,
        VU=VU,
        VW=VW,
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
    )


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


def _log_stats(log_text: str, status: str) -> tuple[float | None, float | None, float | None]:
    seconds = None
    gap = 0.0 if status == "Optimal" else None
    lower_bound = None
    upper = None
    for line in log_text.splitlines():
        folded = line.lower().strip()
        if "wallclock seconds" in folded:
            seconds = _last_float(line)
        if folded.startswith("lower bound"):
            lower_bound = _last_float(line)
        if folded.startswith("objective value"):
            upper = _last_float(line)
        if folded.startswith("gap"):
            gap = _last_float(line)
    if gap is None and lower_bound not in (None, 0) and upper is not None:
        gap = (upper - lower_bound) / abs(lower_bound)
    return seconds, gap, lower_bound


def _last_float(line: str) -> float | None:
    token = line.replace(":", " ").split()[-1]
    try:
        return float(token)
    except ValueError:
        return None


def _excerpt(log_text: str) -> str:
    lines = [line.strip() for line in log_text.splitlines() if line.strip()]
    return "\n".join(lines[-30:])
