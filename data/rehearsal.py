"""Saat 1, 3, 5, 7, 9, 11 prova kayıtları.

HYK onayıyla üretilmiş hipotetik veri. Rapor saatleri verir, kayıt içeriğini
vermez. Üretim kuralları:

- Tohum 20261125. Aynı tohum aynı tabloyu üretir.
- Her saatte bir yeni enkaz ve bir gönüllü grup. Adet raporda yok; prova için
  birer tanedir.
- Hasar sınıfı {Hafif, Orta, Ağır} üzerinde düzgün çekilir. Sınıf seçilince γ
  ve a_{i,k} Bölüm 4.2 / 5.3 hiyerarşisidir. Ağır enkazda E=1, diğerlerinde 0.
- m^A sınıfın 5.3 ölçeğidir (Ağır 4, Orta 2,5, Hafif 1,5). m^U = 0,3 m^A.
  m^W = 0,5 m^A yalnız E=1 ise. 5.2'nin 80/50/20 tepe değerlerinin sınırları
  raporda yoktur; prova o ölçeği kullanmaz.
- Merkeze süreler 0,1 saatlik ızgarada, her mevcut enkazla üçgen aralığı
  boş kalmayacak biçimde çekilir. Enkaz–enkaz süre, merkez sürelerinin orta
  noktasıdır (docs/hipotetik_tau.md ile aynı yuvarlama).
- Gönüllü üretkenliği Üçgen(1; 1,5; 3)/5. Açık merkezlerden birinde, bir
  sonraki periyodun başında belirir.
- β, 5.3 kalıbıdır: s1 0,10, s3 0,50, s2 ağırda 0,30 diğerlerinde 0,15.
- Saat periyodun içindedir. Kayıt bir sonraki periyodun başında modele girer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from data.section_5_3 import afad_competency, round_tenth, triangle_bounds
from model.instance import Instance

LABEL = "HYK onayıyla üretilmiş hipotetik veri"
SEED = 20261125
EVENT_HOURS = (1, 3, 5, 7, 9, 11)
CLASS_LOAD = {"Ağır": 4.0, "Orta": 2.5, "Hafif": 1.5}
CLASSES = ("Hafif", "Orta", "Ağır")


@dataclass(frozen=True)
class RehearsalEvent:
    hour: int
    entry_period: int
    theta: float
    site_id: str
    damage: str
    gamma: int
    m_A: float
    m_U: float
    m_W: float
    E: int
    tau_center: dict[str, float]
    tau_site: dict[str, float]
    volunteer_id: str
    volunteer_p: float
    volunteer_center: str
    label: str = LABEL


def entry_period(hour: int, length: float = 2.0) -> int:
    """Saatin düştüğü periyodun bir sonrası."""

    current = int((hour - 1) // length) + 1
    return current + 1


def generate_rehearsal(
    instance: Instance,
    open_centers: tuple[str, ...] = ("J1", "J2"),
    seed: int = SEED,
) -> tuple[RehearsalEvent, ...]:
    rng = random.Random(seed)
    events = []
    centers = [center.j for center in instance.centers]
    known_sites = [site.i for site in instance.sites]
    center_tau = {(center, site): instance.tau[(center, site)] for center in centers for site in known_sites}
    for offset, hour in enumerate(EVENT_HOURS, start=1):
        damage = rng.choice(CLASSES)
        tau_to_center = _draw_center_times(rng, centers, known_sites, center_tau)
        tau_to_site = {}
        for site_i in known_sites:
            merged = dict(center_tau)
            for center, value in tau_to_center.items():
                merged[(center, f"NEW")] = value
            lower, upper = triangle_bounds(merged, centers, site_i, "NEW")
            rounded = round_tenth((lower + upper) / 2.0)
            if rounded < lower - 1e-9:
                rounded = round_tenth(lower + 0.05)
            if rounded > upper + 1e-9:
                rounded = round_tenth(upper)
            tau_to_site[site_i] = rounded
        load = CLASS_LOAD[damage]
        machine = 1 if damage == "Ağır" else 0
        m_u = round(0.3 * load, 10)
        m_w = round(0.5 * load, 10) if machine else 0.0
        entered = entry_period(hour, instance.L)
        events.append(
            RehearsalEvent(
                hour=hour,
                entry_period=entered,
                theta=instance.L * (entered - 1),
                site_id=f"I{len(instance.sites) + offset}",
                damage=damage,
                gamma={"Ağır": 3, "Orta": 2, "Hafif": 1}[damage],
                m_A=load,
                m_U=m_u,
                m_W=m_w,
                E=machine,
                tau_center=tau_to_center,
                tau_site=tau_to_site,
                volunteer_id=f"gonullu-{offset}",
                volunteer_p=rng.triangular(1.0, 3.0, 1.5) / 5.0,
                volunteer_center=rng.choice(open_centers),
            )
        )
        for center, value in tau_to_center.items():
            center_tau[(center, events[-1].site_id)] = value
        known_sites.append(events[-1].site_id)
    return tuple(events)


def _draw_center_times(rng, centers, sites, center_tau) -> dict[str, float]:
    """|τ_J1 − τ_J2| bütün mevcut enkazların üçgenine sığsın."""

    gaps = []
    for site_i in sites:
        values = [center_tau[(center, site_i)] for center in centers]
        gaps.append(max(values) - min(values))
    limit = min(gaps) if gaps else 0.7
    grid = [round_tenth(0.5 + 0.1 * step) for step in range(0, 9)]
    options = []
    for first in grid:
        for second in grid:
            if abs(first - second) <= limit + 1e-9 and _intervals_open(centers, sites, center_tau, first, second):
                options.append((first, second))
    if not options:
        raise RuntimeError("üçgeni bozmayan merkez süresi bulunamadı")
    picked = options[rng.randrange(len(options))]
    return {centers[0]: picked[0], centers[1]: picked[1]}


def _intervals_open(centers, sites, center_tau, first, second) -> bool:
    trial = dict(center_tau)
    trial[(centers[0], "NEW")] = first
    trial[(centers[1], "NEW")] = second
    for site_i in sites:
        lower, upper = triangle_bounds(trial, centers, site_i, "NEW")
        if lower > upper + 1e-9:
            return False
    return True


def beta_for(scenario_key: str, damage: str) -> float:
    """5.3 kalıbı. s2'de ağır güzergâh 0,30, diğerleri 0,15."""

    if scenario_key == "s1":
        return 0.10
    if scenario_key == "s3":
        return 0.50
    return 0.30 if damage == "Ağır" else 0.15


def instance_with_event(instance: Instance, event: RehearsalEvent) -> Instance:
    """Yeni enkazı ve β'sini ekler. Gönüllü kadroya burada girmez."""

    from model.instance import Scenario, Site

    site = Site(
        i=event.site_id,
        name=event.site_id,
        m=event.m_A,
        E=event.E,
        damage=event.damage,
        gamma=float(event.gamma),
        m_U=event.m_U,
        m_W=event.m_W,
    )
    tau = dict(instance.tau)
    for center, value in event.tau_center.items():
        tau[(center, event.site_id)] = value
    for other, value in event.tau_site.items():
        tau[(event.site_id, other)] = value
        tau[(other, event.site_id)] = value
    competency = dict(instance.a or {})
    for team in instance.team_types:
        competency[(event.site_id, team.k)] = afad_competency(event.damage, team.k)
    scenarios = []
    for scenario in instance.scenarios:
        beta = dict(scenario.beta)
        beta[event.site_id] = beta_for(scenario.s, event.damage)
        scenarios.append(
            Scenario(
                s=scenario.s,
                name=scenario.name,
                P=scenario.P,
                D=scenario.D,
                beta=beta,
                beta_t=scenario.beta_t,
            )
        )
    return Instance(
        centers=list(instance.centers),
        team_types=list(instance.team_types),
        sites=list(instance.sites) + [site],
        scenarios=scenarios,
        tau=tau,
        N_max=instance.N_max,
        U_top=instance.U_top,
        W_top=instance.W_top,
        L=instance.L,
        a=competency,
    )
