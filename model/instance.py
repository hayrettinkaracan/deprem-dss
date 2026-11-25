"""Rapor notasyonu: kümeler, parametreler, yol kullanılabilirliği.

İndeksler: j merkez, k ekip tipi, i enkaz, s senaryo.
β yol gecikmesidir. h, güzergâh açıksa ve τ(1+β) ≤ L ise 1'dir (Bölüm 4.3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Center:
    """Aday merkez j. C: C_{j,k}. U_max, W_max: merkez envanter üst sınırları."""

    j: str
    name: str
    C: dict[str, int]
    U_max: int
    W_max: int


@dataclass(frozen=True)
class TeamType:
    """Ekip tipi k. A = A_k, p = p_k (saat başına iş yükü)."""

    k: str
    name: str
    A: int
    p: float


@dataclass(frozen=True)
class Site:
    """Enkaz i.

    m = m^A (AFAD-saat). m_U ve m_W grup işleridir; eski model ikisini okumaz.
    gamma = γ_i. E = E_i.
    """

    i: str
    name: str
    m: float
    E: int = 0
    damage: str = ""
    lat: float | None = None
    lon: float | None = None
    gamma: float | None = None
    m_U: float | None = None
    m_W: float | None = None


@dataclass(frozen=True)
class Scenario:
    """Senaryo s. P = P_s. beta[i], i'ye giden güzergâhların gecikme oranı.

    beta_t[(i, t)] verilirse o enkazın t çıkış periyodundaki β budur.
    Boşsa β periyoda ayrılmaz; her t için beta[i] kullanılır.
    """

    s: str
    name: str
    P: float
    # Eski modelin kişi talebi. Yeni Çizelge 5.1'de yoktur; o fixture None verir.
    D: dict[str, float] | None
    beta: dict[str, float]
    beta_t: dict[tuple[str, int], float] | None = None


@dataclass
class Instance:
    """Birinci aşama verisi.

    tau[(j, i)] normal seyahat süresi (saat). a boşsa a_{i,k} = 1.
    L periyot uzunluğudur; h eşiği ve bu kalemdeki tek periyotluk iş için kullanılır.
    """

    centers: list[Center]
    team_types: list[TeamType]
    sites: list[Site]
    scenarios: list[Scenario]
    tau: dict[tuple[str, str], float]
    N_max: int
    U_top: int
    W_top: int
    L: float = 2.0
    a: dict[tuple[str, str], int] | None = field(default=None)


def require_legacy_demand(instance: Instance) -> None:
    """Eski u amacı kişi talebi D okur. Yeni Çizelge 5.1 bu alanı taşımaz."""

    missing = [scenario.s for scenario in instance.scenarios if scenario.D is None]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            "Bu çözücü eski kişi talebi D bekler "
            f"({joined}). Yeni Çizelge 5.1'de D yoktur; "
            "eski girdi data.legacy_section_5_3.legacy_section_5_3() içindedir."
        )


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


def competency(instance: Instance, i: str, k: str) -> int:
    """a_{i,k}. Tabloda yoksa 1."""

    if not instance.a:
        return 1
    return 1 if instance.a.get((i, k), 1) else 0


def route_open(tau: float, beta: float, period_hours: float) -> int:
    """h = 1 ancak gecikme dahil seyahat bir periyodu aşmıyorsa (rapor 4.3)."""

    travel = tau * (1.0 + beta)
    return 1 if travel <= period_hours + 1e-9 else 0


def h_matrix(instance: Instance) -> dict[tuple[str, str, str], int]:
    """h_{j,i,s}. Bu kalemde periyot ayrımı yok; çıkış kuralı L eşiğidir."""

    usable = {}
    for center in instance.centers:
        for site in instance.sites:
            tau = instance.tau[(center.j, site.i)]
            for scenario in instance.scenarios:
                usable[(center.j, site.i, scenario.s)] = route_open(
                    tau, scenario.beta[site.i], instance.L
                )
    return usable


def validate(instance: Instance) -> None:
    if instance.N_max < 0:
        raise ValueError("N_max negatif olamaz")
    if instance.U_top < 0 or instance.W_top < 0:
        raise ValueError("U_top ve W_top negatif olamaz")
    if instance.L <= 0:
        raise ValueError("L pozitif olmalı")

    seen_j = set()
    for center in instance.centers:
        if center.j in seen_j:
            raise ValueError(f"Yinelenen merkez: {center.j}")
        seen_j.add(center.j)
        if center.U_max < 0 or center.W_max < 0:
            raise ValueError(f"Merkez {center.j} envanter üst sınırı negatif")

    seen_k = set()
    for team in instance.team_types:
        if team.k in seen_k:
            raise ValueError(f"Yinelenen ekip tipi: {team.k}")
        seen_k.add(team.k)
        if team.A < 0 or team.p < 0:
            raise ValueError(f"Ekip tipi {team.k} parametresi negatif")
        for center in instance.centers:
            if team.k not in center.C or center.C[team.k] < 0:
                raise ValueError(f"C_{{{center.j},{team.k}}} tanımlı ve negatif olmamalı")

    seen_i = set()
    for site in instance.sites:
        if site.i in seen_i:
            raise ValueError(f"Yinelenen enkaz: {site.i}")
        seen_i.add(site.i)
        if site.m <= 0:
            raise ValueError(f"m_{site.i} pozitif olmalı")
        if site.E not in (0, 1):
            raise ValueError(f"E_{site.i} 0 veya 1 olmalı")
        for center in instance.centers:
            if (center.j, site.i) not in instance.tau or instance.tau[(center.j, site.i)] < 0:
                raise ValueError(f"tau_{{{center.j},{site.i}}} tanımlı olmalı")

    seen_s = set()
    for scenario in instance.scenarios:
        if scenario.s in seen_s:
            raise ValueError(f"Yinelenen senaryo: {scenario.s}")
        seen_s.add(scenario.s)
        if scenario.P < 0:
            raise ValueError(f"P_{scenario.s} negatif olamaz")
        for site in instance.sites:
            if scenario.D is not None and (site.i not in scenario.D or scenario.D[site.i] < 0):
                raise ValueError(f"D_{{{site.i},{scenario.s}}} tanımlı olmalı")
            if site.i not in scenario.beta or scenario.beta[site.i] < 0:
                raise ValueError(f"beta_{{{site.i},{scenario.s}}} tanımlı olmalı")
        if scenario.beta_t:
            for key, value in scenario.beta_t.items():
                if (
                    not isinstance(key, tuple)
                    or len(key) != 2
                    or not isinstance(key[1], int)
                    or key[1] < 1
                    or value < 0
                ):
                    raise ValueError(f"beta_t_{scenario.s} (i, t) ve negatif olmayan oran olmalı")

    if instance.a:
        for value in instance.a.values():
            if value not in (0, 1):
                raise ValueError("a_{i,k} 0 veya 1 olmalı")
