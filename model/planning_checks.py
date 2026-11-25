"""5.3.2 denetimleri, planlama çözümünün bu dilimine düşenler.

Süreler çakışmaz. Hafif ekip orta veya ağır enkazda yoktur. Makine I3 ve I4'te
yoktur. İkinci fiziksel giriş yoktur; devam ikinci giriş sayılmaz. q sürelerden
bir kez gelir. UMKE, 0,2 AFAD-saat birikmeden girmez. Grup işi bitmeden ayrılış
yoktur.
"""

from __future__ import annotations

from model.instance import Instance
from model.planning import ETA, PlanningSolution, _is_har, _is_physical_entry
from model.planning_network import build_planning_network
from model.staff import GROUP_A, GROUP_U, GROUP_W, GROUPS, Staff, group_load, planning_staff

TOL = 1e-3


def planning_violations(
    instance: Instance,
    solution: PlanningSolution,
    staff: Staff | None = None,
    eta: float = ETA,
    vartheta: float = 0.01,
) -> list[str]:
    problems: list[str] = []
    if solution.objective is None:
        problems.append(f"çözüm yok: {solution.status}")
        return problems
    staff = staff or planning_staff(instance)
    network = build_planning_network(instance, solution.periods, staff)
    by_id = {resource.r: resource for resource in staff.resources}
    _balance(instance, solution, problems)
    _durations(instance, solution, staff, network, problems)
    _chains(instance, solution, staff, network, by_id, eta, vartheta, problems)
    expected = sum(scenario.P * solution.z1_by_scenario[scenario.s] for scenario in instance.scenarios)
    if abs(expected - solution.objective) > 1e-2:
        problems.append(f"Z1 {solution.objective} formül {expected}")
    return problems


def _balance(instance: Instance, solution: PlanningSolution, problems: list[str]) -> None:
    for scenario in instance.scenarios:
        for site in instance.sites:
            for group in GROUPS:
                start = solution.R[(group, site.i, 1, scenario.s)]
                if abs(start - group_load(site, group)) > TOL:
                    problems.append(f"R0 {group} {site.i} {scenario.s}")
                for t in range(1, solution.periods + 1):
                    remaining = solution.R[(group, site.i, t, scenario.s)]
                    done = solution.q[(group, site.i, t, scenario.s)]
                    if done < -TOL or done - remaining > TOL:
                        problems.append(f"q>R {group} {site.i} t{t} {scenario.s}")
                    if t < solution.periods:
                        nxt = solution.R[(group, site.i, t + 1, scenario.s)]
                        if abs(nxt - (remaining - done)) > TOL:
                            problems.append(f"denge {group} {site.i} t{t} {scenario.s}")


def _durations(instance, solution, staff, network, problems: list[str]) -> None:
    for scenario in instance.scenarios:
        for site in instance.sites:
            for group in GROUPS:
                members = staff.of(group)
                for t in range(1, solution.periods + 1):
                    record = f"d_{site.i}_t{t}"
                    total = 0.0
                    for resource in members:
                        key = (resource.r, record, scenario.s)
                        if key not in solution.bas:
                            continue
                        span = solution.bit[key] - solution.bas[key]
                        if span < -TOL:
                            problems.append(f"negatif süre {resource.r} {record}")
                        total += resource.p * max(0.0, span)
                        if span > instance.L + TOL:
                            problems.append(f"süre > L {resource.r} {record}")
                    recorded = solution.q[(group, site.i, t, scenario.s)]
                    if abs(recorded - total) > TOL:
                        problems.append(
                            f"q süre değil {group} {site.i} t{t} {scenario.s}: {recorded} != {total}"
                        )


def _chains(instance, solution, staff, network, by_id, eta, vartheta, problems: list[str]) -> None:
    for scenario in instance.scenarios:
        graph = network.by_arc[scenario.s]
        for resource in staff.resources:
            pairs = solution.arcs.get((resource.r, scenario.s), [])
            chain = solution.chains.get((resource.r, scenario.s), [])
            if not chain or chain[0] != "σ" or chain[-1] != "ω":
                problems.append(f"zincir {resource.r} {scenario.s}")
                continue
            entries: dict[str, int] = {}
            for tail, head in pairs:
                arc = graph.get((tail, head))
                if arc is None:
                    problems.append(f"yay yok {resource.r} {tail}->{head}")
                    continue
                if arc.v.kind == "debris" and resource.r == "hafif-1" and arc.v.i != "I4":
                    problems.append(f"hafif {arc.v.i}")
                if resource.group == GROUP_W and arc.v.kind == "debris" and arc.v.i in {"I3", "I4"}:
                    problems.append(f"makine {arc.v.i}")
                if _is_physical_entry(arc, arc.v.i) and arc.v.kind == "debris":
                    entries[arc.v.i] = entries.get(arc.v.i, 0) + 1
                if arc.kind == "continue":
                    if arc.u.i != arc.v.i or arc.v.t != arc.u.t + 1:
                        problems.append(f"devam {resource.r}")
                if arc.u.kind in {"debris", "center", "origin"} and arc.v.kind in {"debris", "center"}:
                    bas = solution.bas[(resource.r, arc.v.key, scenario.s)]
                    bit = solution.bit[(resource.r, arc.u.key, scenario.s)]
                    if arc.kind == "travel" and bas + TOL < bit + arc.sey:
                        problems.append(f"çalışma-yol {resource.r} {arc.u.label}->{arc.v.label}")
                    if arc.kind in {"continue", "wait"} and bas + TOL < bit:
                        problems.append(f"devam saati {resource.r}")
                if arc.v.kind == "debris" and arc.u.kind != "sigma":
                    remain = solution.R[(resource.group, arc.v.i, arc.v.t, scenario.s)]
                    if remain + TOL < vartheta:
                        problems.append(f"boş bekleyiş {resource.r} {arc.v.label}")
                if (
                    resource.group == GROUP_U
                    and arc.v.kind == "debris"
                    and arc.u.physical() not in {None, arc.v.i}
                ):
                    initial = group_load(next(site for site in instance.sites if site.i == arc.v.i), GROUP_A)
                    done = initial - solution.R[(GROUP_A, arc.v.i, arc.v.t, scenario.s)]
                    if done + TOL < min(eta, initial):
                        problems.append(f"UMKE erken {resource.r} {arc.v.label} {scenario.s}")
                if arc.u.kind == "debris" and _is_har(arc):
                    left = (
                        solution.R[(resource.group, arc.u.i, arc.u.t, scenario.s)]
                        - solution.q[(resource.group, arc.u.i, arc.u.t, scenario.s)]
                    )
                    if left > TOL:
                        problems.append(f"iş bitmeden ayrılış {resource.r} {arc.u.label} {scenario.s}")
            for site_i, count in entries.items():
                if count > 1:
                    problems.append(f"ikinci giriş {resource.r} {site_i} {scenario.s}")
