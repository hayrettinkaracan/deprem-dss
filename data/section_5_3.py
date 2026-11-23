"""Çizelge 5.1 ve Bölüm 5.3 senaryoları.

Tabloda olmayan ve bu dosyada doldurulanlar (model varsayımı):
C_{j,k} = A_k, U_{j,max} = U_top, W_{j,max} = W_top, N_max = 2,
p_k = 1, a_{i,k} = 1, D_{i,s} senaryodan bağımsız, fiziksel yol kapanması yok.
"""

from __future__ import annotations

from model.instance import Center, Instance, Scenario, Site, TeamType

PERIODS = 36
PERIOD_HOURS = 2.0

# (merkez, enkaz) -> saat. Çizelge 5.1 sütunları.
TAU = {
    ("J1", "I1"): 1.5,
    ("J1", "I2"): 1.0,
    ("J1", "I3"): 2.0,
    ("J1", "I4"): 2.5,
    ("J1", "I5"): 3.0,
    ("J2", "I1"): 2.0,
    ("J2", "I2"): 1.5,
    ("J2", "I3"): 1.0,
    ("J2", "I4"): 1.5,
    ("J2", "I5"): 2.5,
}

DEMAND = {"I1": 12.0, "I2": 8.0, "I3": 6.0, "I4": 4.0, "I5": 10.0}


def section_5_3() -> Instance:
    sites = [
        Site(i="I1", name="I1", m=4.0, E=1, damage="Ağır"),
        Site(i="I2", name="I2", m=3.0, E=1, damage="Orta"),
        Site(i="I3", name="I3", m=2.5, E=0, damage="Orta"),
        Site(i="I4", name="I4", m=1.5, E=0, damage="Hafif"),
        Site(i="I5", name="I5", m=4.5, E=1, damage="Ağır"),
    ]
    team_types = [
        TeamType(k="hafif", name="Hafif", A=1, p=1.0),
        TeamType(k="orta", name="Orta", A=2, p=1.0),
        TeamType(k="agir", name="Ağır", A=1, p=1.0),
    ]
    capacity = {team.k: team.A for team in team_types}
    centers = [
        Center(j="J1", name="J1", C=dict(capacity), U_max=3, W_max=2),
        Center(j="J2", name="J2", C=dict(capacity), U_max=3, W_max=2),
    ]
    beta_s1 = {site.i: 0.10 for site in sites}
    beta_s2 = {site.i: 0.30 if site.i in {"I1", "I5"} else 0.15 for site in sites}
    beta_s3 = {site.i: 0.50 for site in sites}
    demand = dict(DEMAND)
    scenarios = [
        Scenario(s="s1", name="İyimser", P=0.30, D=dict(demand), beta=beta_s1),
        Scenario(s="s2", name="Beklenen", P=0.45, D=dict(demand), beta=beta_s2),
        Scenario(s="s3", name="Kötümser", P=0.25, D=dict(demand), beta=beta_s3),
    ]
    return Instance(
        centers=centers,
        team_types=team_types,
        sites=sites,
        scenarios=scenarios,
        tau=dict(TAU),
        N_max=2,
        U_top=3,
        W_top=2,
        L=PERIOD_HOURS,
    )
