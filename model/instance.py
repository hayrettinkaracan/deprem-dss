"""Küme, parametre ve kapsama tanımları.

İndeksler rapor notasyonuyla durur:
    j  lojistik / koordinasyon merkezi
    k  kurtarma ekip tipi
    i  enkaz noktası
    s  senaryo
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Center:
    """Aday merkez j."""

    j: str
    name: str
    lat: float
    lon: float
    f: float
    cap: dict[str, int]
    cap_tot: int
    cap_u: int
    cap_w: int


@dataclass(frozen=True)
class TeamType:
    """Ekip tipi k. N = N_k (eldeki ekip), q = nominal kişi kapasitesi."""

    k: str
    name: str
    N: int
    q: float


@dataclass(frozen=True)
class Site:
    """Enkaz noktası i. d = talep (kişi)."""

    i: str
    name: str
    lat: float
    lon: float
    d: float


@dataclass(frozen=True)
class Scenario:
    """Senaryo s. h[i] yolun açık olması, pi ağırlık (şimdilik 1)."""

    s: str
    name: str
    beta: float
    h: dict[str, int]
    pi: float = 1.0


@dataclass
class Instance:
    """Birinci aşama modeli için tüm veri.

    r_override verilirse mesafe kuralının yerine geçer; eksik (j, i) çiftleri
    kapsamaz. a, yetkinlik a_{i,k} için yer tutucudur; boşsa her çift 1 kabul edilir.
    """

    centers: list[Center]
    team_types: list[TeamType]
    sites: list[Site]
    scenarios: list[Scenario]
    B: float
    N_max: int
    N_U: int
    N_W: int
    radius_km: float
    r_override: dict[tuple[str, str], int] | None = None
    a: dict[tuple[str, str], float] | None = field(default=None)


def capacity_factor(beta: float) -> float:
    """Prototipteki β tanımı: etkin kapasite = nominal × 1/(1+β)."""

    return 1.0 / (1.0 + float(beta))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    hav = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(hav))


def competency(instance: Instance, i: str, k: str) -> float:
    """a_{i,k}. Tanımsızsa 1 (ileride tip-enkaz yetkinliği buraya yazılacak)."""

    if not instance.a:
        return 1.0
    return float(instance.a.get((i, k), 1.0))


def coverage_matrix(instance: Instance) -> dict[tuple[str, str], int]:
    """r_{j,i} ∈ {0,1}. Merkez, yarıçap içindeki enkazı kapsar."""

    if instance.r_override is not None:
        covered = {}
        for center in instance.centers:
            for site in instance.sites:
                covered[(center.j, site.i)] = 1 if instance.r_override.get((center.j, site.i), 0) else 0
        return covered

    covered = {}
    for center in instance.centers:
        for site in instance.sites:
            distance = haversine_km(center.lat, center.lon, site.lat, site.lon)
            covered[(center.j, site.i)] = 1 if distance <= instance.radius_km + 1e-9 else 0
    return covered


def validate(instance: Instance) -> None:
    if instance.B < 0:
        raise ValueError("Açma bütçesi B negatif olamaz")
    if instance.N_max < 0:
        raise ValueError("Açılabilecek merkez sayısı Nmax negatif olamaz")
    if instance.N_U < 0 or instance.N_W < 0:
        raise ValueError("UMKE ve iş makinesi sayıları negatif olamaz")
    if instance.radius_km <= 0:
        raise ValueError("Kapsama yarıçapı pozitif olmalı")

    seen_j = set()
    for center in instance.centers:
        if center.j in seen_j:
            raise ValueError(f"Yinelenen merkez indeksi: {center.j}")
        seen_j.add(center.j)
        if center.f < 0 or center.cap_tot < 0 or center.cap_u < 0 or center.cap_w < 0:
            raise ValueError(f"Merkez {center.j} parametreleri negatif olamaz")

    seen_k = set()
    for team in instance.team_types:
        if team.k in seen_k:
            raise ValueError(f"Yinelenen ekip tipi: {team.k}")
        seen_k.add(team.k)
        if team.N < 0 or team.q < 0:
            raise ValueError(f"Ekip tipi {team.k} parametreleri negatif olamaz")
        for center in instance.centers:
            if team.k not in center.cap:
                raise ValueError(f"Merkez {center.j} için Cap_{{j,{team.k}}} yok")
            if center.cap[team.k] < 0:
                raise ValueError(f"Cap_{{{center.j},{team.k}}} negatif olamaz")

    seen_i = set()
    for site in instance.sites:
        if site.i in seen_i:
            raise ValueError(f"Yinelenen enkaz indeksi: {site.i}")
        seen_i.add(site.i)
        if site.d < 0:
            raise ValueError(f"Enkaz {site.i} talebi negatif olamaz")

    seen_s = set()
    for scenario in instance.scenarios:
        if scenario.s in seen_s:
            raise ValueError(f"Yinelenen senaryo: {scenario.s}")
        seen_s.add(scenario.s)
        if scenario.beta < 0:
            raise ValueError(f"Senaryo {scenario.s} beta negatif olamaz")
        if scenario.pi < 0:
            raise ValueError(f"Senaryo {scenario.s} ağırlığı negatif olamaz")
        for site in instance.sites:
            if site.i not in scenario.h:
                raise ValueError(f"h_{{{site.i},{scenario.s}}} tanımlı değil")
            if scenario.h[site.i] not in (0, 1):
                raise ValueError(f"h_{{{site.i},{scenario.s}}} 0 veya 1 olmalı")
