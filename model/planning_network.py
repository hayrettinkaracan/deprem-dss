"""Planlama grafı. Rapor 4.3.1, 4.3.2, (4.1), (4.29), (4.33).

Eski ``build_network`` arayüzün kullandığı çözücüde durur. Bu kurucu yeni
raporun grafıdır: global M yoktur, varış yalnız t veya t+1, ω^yol kaydında
zaman yoktur.

β kuralı: güzergâhın enkazına aittir. Varış bir enkazsa o enkazın β'si
(5.3, "I1 ve I5 güzergâhları"). Varış merkezse güzergâh hâlâ çıkılan
enkazındır. İki enkaz arasında hedef enkazın β'si kullanılır; gecikme
gidilen işin yoluna yazılır. β periyot boyunca sabittir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from model.instance import Instance
from model.network import (
    TIME_TOL,
    Arc,
    Visit,
    horizon_hours,
    route_h,
    travel_sey,
)
from model.staff import Resource, Staff, can_serve, planning_staff


def planning_arrivals(t_dep: int, periods: int) -> list[int]:
    """(4.3.2) kural 2. Farklı noktada varış yalnız t veya t+1."""

    found = [t_dep]
    if t_dep + 1 <= periods:
        found.append(t_dep + 1)
    return found


def movement_m(u: Visit, v: Visit, sey: float, length: float) -> float | None:
    """(4.33). Aynı yerde 0. Zamanı olmayan kayıtta M yoktur."""

    if u.kind == "enroute" or v.kind == "enroute":
        return None
    if u.physical() is not None and u.physical() == v.physical():
        return 0.0
    start = u.period()
    end = v.period()
    if start is None or end is None:
        return None
    return length * (start - end + 1) + sey


def has_time(visit: Visit) -> bool:
    """(4.38). ω^yol, σ ve ω için zaman değişkeni yok."""

    return visit.kind in {"origin", "debris", "center"}


@dataclass
class PlanningNetwork:
    """Ekip süzgeci uygulanmış A_s. big_m alanı yoktur."""

    periods: int
    horizon: float
    sigma: Visit
    omega: Visit
    visits: list[Visit]
    by_key: dict[str, Visit]
    by_arc: dict[str, dict[tuple[str, str], Arc]]
    team_arcs: dict[str, dict[str, list[Arc]]] = field(default_factory=dict)

    def timed(self) -> list[Visit]:
        return [visit for visit in self.visits if has_time(visit)]


def useful_center_copies(instance: Instance) -> int:
    """Aynı periyotta zamanı tutarlı merkez dönüşü sayısı.

    Rapor ℓ'yi |I|+1'e kadar açar. En kısa gidiş-dönüş 2·min Sey sürdüğünden,
    bir periyot penceresine sığmayan kopyanın uygulanabilir çözümü yoktur.
    İlk dönüş pencerenin başında gelebilir; her ek dönüş bir gidiş-dönüş ister.
    """

    cap = len(instance.sites) + 1
    min_sey = None
    for scenario in instance.scenarios:
        for center in instance.centers:
            for site in instance.sites:
                if route_h(instance, center.j, site.i, 1, scenario) != 1:
                    continue
                sey = travel_sey(instance, center.j, site.i, 1, scenario)
                if sey is None or sey <= TIME_TOL:
                    continue
                min_sey = sey if min_sey is None else min(min_sey, sey)
    if min_sey is None:
        return cap
    extra = int((instance.L + 1e-9) // (2.0 * min_sey))
    return max(1, min(cap, 1 + extra))


def build_planning_network(
    instance: Instance,
    periods: int,
    staff: Staff | None = None,
) -> PlanningNetwork:
    """A_s. Enkaza giriş, ekibin yetkinliği ve E_i ile sınırlıdır."""

    if periods < 1:
        raise ValueError("periyot sayısı en az 1 olmalı")
    staff = staff or planning_staff(instance)
    length = instance.L
    horizon = horizon_hours(periods, length)
    sigma = Visit("sigma")
    omega = Visit("omega")
    origins = [Visit("origin", j=center.j) for center in instance.centers]
    debris = [
        Visit("debris", i=site.i, t=t)
        for site in instance.sites
        for t in range(1, periods + 1)
    ]
    debris_at = {(visit.i, visit.t): visit for visit in debris}
    copies = useful_center_copies(instance)
    center_visits = [
        Visit("center", j=center.j, t=t, ell=ell)
        for center in instance.centers
        for t in range(1, periods + 1)
        for ell in range(1, copies + 1)
    ]
    center_at = {(visit.j, visit.t, visit.ell): visit for visit in center_visits}
    enroutes = [Visit("enroute", j=center.j) for center in instance.centers]
    enroute_of = {visit.j: visit for visit in enroutes}
    visits = origins + debris + center_visits + enroutes
    by_key = {sigma.key: sigma, omega.key: omega}
    for visit in visits:
        by_key[visit.key] = visit

    site_of = {site.i: site for site in instance.sites}
    allowed = {
        site.i: tuple(resource for resource in staff.resources if can_serve(instance, resource, site))
        for site in instance.sites
    }
    everyone = staff.resources
    by_arc: dict[str, dict[tuple[str, str], Arc]] = {}
    team_arcs: dict[str, dict[str, list[Arc]]] = {}

    for scenario in instance.scenarios:
        found: dict[tuple[str, str], Arc] = {}
        chosen: dict[str, list[Arc]] = {resource.r: [] for resource in everyone}
        seen: dict[str, set[tuple[str, str]]] = {resource.r: set() for resource in everyone}

        def allow(arc: Arc, resources: tuple[Resource, ...] | list[Resource]) -> None:
            existing = found.get(arc.key)
            if existing is None:
                found[arc.key] = arc
                existing = arc
            for resource in resources:
                if arc.key in seen[resource.r]:
                    continue
                seen[resource.r].add(arc.key)
                chosen[resource.r].append(existing)

        def travel_to_sites(node: Visit, t_dep: int, pool: tuple[Resource, ...] | list[Resource]) -> None:
            origin = node.physical()
            if origin is None:
                return
            for site in instance.sites:
                admitted = tuple(resource for resource in pool if resource in allowed[site.i])
                if not admitted:
                    continue
                if route_h(instance, origin, site.i, t_dep, scenario) != 1:
                    continue
                sey = travel_sey(instance, origin, site.i, t_dep, scenario)
                if sey is None:
                    continue
                for t_arr in planning_arrivals(t_dep, periods):
                    head = debris_at[(site.i, t_arr)]
                    allow(
                        Arc(
                            node,
                            head,
                            "travel",
                            sey=sey,
                            departure_t=t_dep,
                            m_uv=movement_m(node, head, sey, length),
                        ),
                        admitted,
                    )

        for origin in origins:
            allow(Arc(sigma, origin, "start"), everyone)
        allow(Arc(sigma, omega, "start"), everyone)

        for origin in origins:
            allow(Arc(origin, omega, "end", departure_t=1), everyone)
            first = center_at.get((origin.j, 1, 1))
            if first is not None:
                allow(
                    Arc(origin, first, "wait", sey=0.0, departure_t=1, m_uv=0.0),
                    everyone,
                )
            travel_to_sites(origin, 1, everyone)

        for visit in center_visits:
            allow(Arc(visit, omega, "end", departure_t=visit.t), everyone)
            if visit.ell < copies:
                nxt = center_at[(visit.j, visit.t, visit.ell + 1)]
                allow(
                    Arc(visit, nxt, "wait", sey=0.0, departure_t=visit.t, m_uv=0.0),
                    everyone,
                )
            if visit.t < periods:
                nxt = center_at[(visit.j, visit.t + 1, 1)]
                allow(
                    Arc(visit, nxt, "wait", sey=0.0, departure_t=visit.t, m_uv=0.0),
                    everyone,
                )
            travel_to_sites(visit, visit.t, everyone)

        for visit in debris:
            present = allowed[visit.i]
            if not present:
                continue
            if visit.t < periods:
                allow(
                    Arc(
                        visit,
                        debris_at[(visit.i, visit.t + 1)],
                        "continue",
                        sey=0.0,
                        departure_t=visit.t,
                        m_uv=0.0,
                    ),
                    present,
                )
            if visit.t == periods:
                allow(Arc(visit, omega, "end", departure_t=visit.t), present)
            for center in instance.centers:
                if route_h(instance, visit.i, center.j, visit.t, scenario) != 1:
                    continue
                sey = travel_sey(instance, visit.i, center.j, visit.t, scenario)
                if sey is None:
                    continue
                for t_arr in planning_arrivals(visit.t, periods):
                    for ell in range(1, copies + 1):
                        head = center_at[(center.j, t_arr, ell)]
                        allow(
                            Arc(
                                visit,
                                head,
                                "travel",
                                sey=sey,
                                departure_t=visit.t,
                                m_uv=movement_m(visit, head, sey, length),
                            ),
                            present,
                        )
                if visit.t == periods and sey > TIME_TOL:
                    allow(
                        Arc(
                            visit,
                            enroute_of[center.j],
                            "enroute",
                            sey=sey,
                            departure_t=visit.t,
                        ),
                        present,
                    )
            for other in instance.sites:
                if other.i == visit.i:
                    continue
                both = tuple(resource for resource in present if resource in allowed[other.i])
                if not both:
                    continue
                if route_h(instance, visit.i, other.i, visit.t, scenario) != 1:
                    continue
                sey = travel_sey(instance, visit.i, other.i, visit.t, scenario)
                if sey is None:
                    continue
                for t_arr in planning_arrivals(visit.t, periods):
                    head = debris_at[(other.i, t_arr)]
                    allow(
                        Arc(
                            visit,
                            head,
                            "travel",
                            sey=sey,
                            departure_t=visit.t,
                            m_uv=movement_m(visit, head, sey, length),
                        ),
                        both,
                    )

        for visit in enroutes:
            allow(Arc(visit, omega, "enroute_end"), everyone)

        by_arc[scenario.s] = found
        team_arcs[scenario.s] = chosen

    return PlanningNetwork(
        periods=periods,
        horizon=horizon,
        sigma=sigma,
        omega=omega,
        visits=visits,
        by_key=by_key,
        by_arc=by_arc,
        team_arcs=team_arcs,
    )
