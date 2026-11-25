"""Periyot içi sevk. Rapor 4.9. Modelin dışındadır; MILP kısıtı değildir.

Ulaşılabilir, grubunun işi kalmış, yetkinliği uyan, daha önce ayrılmadığı
enkazlar. UMKE için o enkazda en az η AFAD-saat birikmiş olmalıdır. Aday yoksa
en yakın açık merkez. Eşit sürede küçük indis önce gelir.
"""

from __future__ import annotations

from model.instance import Instance
from model.network import route_h, travel_sey
from model.operational import nearest_open_center
from model.staff import GROUP_A, GROUP_U, Resource, can_serve

ETA = 0.2


def dispatch_target(
    instance: Instance,
    resource: Resource,
    scenario,
    t: int,
    origin: str,
    open_centers: set[str] | frozenset[str],
    remaining: dict[tuple[str, str], float],
    left_sites: set[str] | frozenset[str],
    eta: float = ETA,
) -> str | None:
    """Hedef enkazın ya da açık merkezin adı. Hiçbiri yoksa None."""

    best: tuple[tuple[float, str], str] | None = None
    for site in instance.sites:
        if site.i in left_sites or site.i == origin:
            continue
        if not can_serve(instance, resource, site):
            continue
        if remaining.get((resource.group, site.i), 0.0) <= 0:
            continue
        if resource.group == GROUP_U and not _umke_ready(site, remaining, eta):
            continue
        if route_h(instance, origin, site.i, t, scenario) != 1:
            continue
        sey = travel_sey(instance, origin, site.i, t, scenario)
        if sey is None:
            continue
        rank = (sey, site.i)
        if best is None or rank < best[0]:
            best = (rank, site.i)
    if best is not None:
        return best[1]
    nearest = nearest_open_center(instance, scenario, origin, t, frozenset(open_centers))
    if nearest is None and origin in open_centers:
        return origin
    return None if nearest is None else nearest[0]


def _umke_ready(site, remaining: dict[tuple[str, str], float], eta: float) -> bool:
    done = site.m - remaining.get((GROUP_A, site.i), site.m)
    return done + 1e-9 >= min(eta, site.m)
