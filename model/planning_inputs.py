"""Supabase satırlarını rapor notasyonundaki örneğe çevirir.

Canlı veride τ tablosu yoktur. Mesafe 30 km/saat ile saate çevrilir; bu yalnızca
önizlemedir. s2'deki I1/I5 ayrımı 5.3 tablosuna aittir, canlıda bütün güzergâhlara
0,15 uygulanır. m_i = talep ve p_k = tip içi ortalama kapasite de önizleme
varsayımıdır. Plan Supabase atamasını değiştirmez.
"""

from __future__ import annotations

import unicodedata

from model.instance import Center, Instance, Scenario, Site, TeamType, haversine_km
from model.problem import Solution

LIVE_SPEED_KMH = 30.0
LIVE_N_MAX = 2
LIVE_U_TOP = 3
LIVE_W_TOP = 2
LIVE_CENTERS = (
    ("J1", "Avcılar Belediye Koordinasyon", 40.9790, 28.7210),
    ("J2", "Ambarlı Lojistik", 40.9605, 28.6855),
)

PLAN_CAPTION = (
    "Rapor (4.4)–(4.10): G merkez açar, V ekip, V^U UMKE, V^W iş makinesi ön konumlar. "
    "N_max merkez sayısıdır, parasal bütçe yoktur. β seyahat gecikmesidir; "
    "τ(1+β) > 2 saat ise güzergâh kullanılamaz. "
    f"Canlı τ, koordinattan {LIVE_SPEED_KMH:.0f} km/saat ile türetilir. "
    f"UMKE havuzu {LIVE_U_TOP}, iş makinesi havuzu {LIVE_W_TOP}. "
    "Bu plan Supabase kaydını değiştirmez."
)


def build_live_instance(enkaz_rows: list[dict], ekip_rows: list[dict]) -> Instance:
    sites = [_site_from_row(row) for row in sorted(enkaz_rows, key=lambda row: row["id"])]
    team_types = _team_types(ekip_rows)
    capacity = {team.k: team.A for team in team_types}
    centers = [
        Center(j=key, name=name, C=dict(capacity), U_max=LIVE_U_TOP, W_max=LIVE_W_TOP)
        for key, name, _lat, _lon in LIVE_CENTERS
    ]
    tau = {}
    for key, _name, lat, lon in LIVE_CENTERS:
        for site in sites:
            tau[(key, site.i)] = haversine_km(lat, lon, site.lat, site.lon) / LIVE_SPEED_KMH
    return Instance(
        centers=centers,
        team_types=team_types,
        sites=sites,
        scenarios=_live_scenarios(sites),
        tau=tau,
        N_max=LIVE_N_MAX,
        U_top=LIVE_U_TOP,
        W_top=LIVE_W_TOP,
        L=2.0,
    )


def plan_view(instance: Instance, solution: Solution) -> dict:
    rows = []
    for center in instance.centers:
        row = {
            "Merkez": center.name,
            "Açık": "evet" if solution.G[center.j] == 1 else "hayır",
        }
        for team in instance.team_types:
            row[team.name] = solution.V[(center.j, team.k)]
        row["UMKE"] = solution.VU[center.j]
        row["İş makinesi"] = solution.VW[center.j]
        rows.append(row)
    opened = [center.name for center in instance.centers if solution.G[center.j] == 1]
    return {
        "status": solution.status,
        "objective": solution.objective,
        "unmet": solution.unmet_cost,
        "open_count": len(opened),
        "team_count": sum(solution.V.values()),
        "rows": rows,
        "opened_names": opened,
        "caption": PLAN_CAPTION,
    }


def _live_scenarios(sites: list[Site]) -> list[Scenario]:
    demand = {site.i: site.m for site in sites}
    specs = (
        ("s1", "İyimser", 0.30, 0.10),
        ("s2", "Beklenen", 0.45, 0.15),
        ("s3", "Kötümser", 0.25, 0.50),
    )
    return [
        Scenario(
            s=key,
            name=name,
            P=probability,
            D=dict(demand),
            beta={site.i: beta for site in sites},
        )
        for key, name, probability, beta in specs
    ]


def _site_from_row(row: dict) -> Site:
    try:
        lat = float(row["enlem"])
        lon = float(row["boylam"])
        demand = float(row["talep"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Enkaz satırında enlem, boylam veya talep yok: {row.get('id')}") from exc
    if demand <= 0:
        raise ValueError(f"Enkaz {row.get('id')} talebi pozitif olmalı")
    machine = 1 if row.get("makine_gerekli") else 0
    name = str(row.get("isim") or row["id"])
    return Site(i=str(row["id"]), name=name, m=demand, E=machine, lat=lat, lon=lon)


def _team_types(rows: list[dict]) -> list[TeamType]:
    grouped: dict[str, list[float]] = {}
    names: dict[str, str] = {}
    for row in rows:
        kapasite = row.get("kapasite")
        if kapasite is None:
            continue
        label = str(row.get("tip") or "Arama-Kurtarma")
        key = _slug(label)
        grouped.setdefault(key, []).append(float(kapasite))
        names[key] = label
    types = []
    for key in sorted(grouped):
        capacities = grouped[key]
        types.append(
            TeamType(
                k=key,
                name=names[key],
                A=len(capacities),
                p=sum(capacities) / len(capacities),
            )
        )
    return types


def _slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.translate(str.maketrans({"ı": "i", "İ": "i"}))
    cleaned = []
    for char in folded.lower():
        cleaned.append(char if char.isalnum() else "_")
    slug = "".join(cleaned).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "tip"
