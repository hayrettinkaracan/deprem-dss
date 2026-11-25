"""Planlama kadrosu. Rapor 4.3.1 ve 4.2.

R^A arama-kurtarmadır: AFAD ekipleri ve gönüllüler. Planlamada R^G boştur,
bu yüzden R^A yalnız AFAD kadrosudur. R^U UMKE, R^W ağır iş makinesidir.
p_r ekibe aittir. 5.3'te AFAD, UMKE ve makine için p_r = 1.

Erişim: AFAD yalnız a_{i,k}=1. UMKE ve gönüllü her enkaza. Makine yalnız E_i=1.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.instance import Instance, Site, competency

GROUP_A = "A"
GROUP_U = "U"
GROUP_W = "W"
GROUP_G = "G"
GROUPS = (GROUP_A, GROUP_U, GROUP_W)

# Rapor 4.2: bu üç kaynak kendi biriminde saatte 1 birim iş yapar.
PLANNING_PRODUCTIVITY = 1.0


@dataclass(frozen=True)
class Resource:
    """Tek ekip. k yalnız AFAD yetkinliğidir."""

    r: str
    group: str
    p: float
    k: str | None = None


@dataclass(frozen=True)
class Staff:
    """R = R^A ∪ R^U ∪ R^W. Planlamada gönüllü yoktur."""

    resources: tuple[Resource, ...]

    def of(self, group: str) -> tuple[Resource, ...]:
        return tuple(resource for resource in self.resources if resource.group == group)


def planning_staff(instance: Instance) -> Staff:
    """5.3 planlama kadrosu. R^G = ∅. Sayılar A_k, U^top ve W^top'tan gelir."""

    resources: list[Resource] = []
    for spec in instance.team_types:
        for index in range(1, spec.A + 1):
            resources.append(
                Resource(
                    r=f"{spec.k}-{index}",
                    group=GROUP_A,
                    p=PLANNING_PRODUCTIVITY,
                    k=spec.k,
                )
            )
    for index in range(1, instance.U_top + 1):
        resources.append(Resource(r=f"umke-{index}", group=GROUP_U, p=PLANNING_PRODUCTIVITY))
    for index in range(1, instance.W_top + 1):
        resources.append(Resource(r=f"makine-{index}", group=GROUP_W, p=PLANNING_PRODUCTIVITY))
    return Staff(tuple(resources))


def group_load(site: Site, group: str) -> float:
    """m^c. Planlamada senaryodan bağımsızdır; 5.3 iş yükünü sabitlemiştir."""

    if group == GROUP_A:
        return site.m
    if group == GROUP_U:
        if site.m_U is None:
            raise ValueError(f"m^U_{site.i} yok")
        return site.m_U
    if group == GROUP_W:
        if site.m_W is None:
            raise ValueError(f"m^W_{site.i} yok")
        return site.m_W
    raise ValueError(f"bilinmeyen grup {group}")


def can_serve(instance: Instance, resource: Resource, site: Site) -> bool:
    """Ekip bu enkaza girebilir mi. Rapor 4.3.2 kural 3 ve 4.2."""

    if resource.group == GROUP_A:
        if resource.k is None:
            return False
        return competency(instance, site.i, resource.k) == 1
    if resource.group in {GROUP_U, GROUP_G}:
        return True
    if resource.group == GROUP_W:
        return site.E == 1
    return False
