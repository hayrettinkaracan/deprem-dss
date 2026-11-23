"""Supabase satırlarını birinci aşama örneğine çevirir.

Canlı planda açma maliyetleri semboliktir. Veritabanındaki kişi talebi ile
rapor maliyeti aynı ölçekte olmadığı için 0.01, bir ekibin sağlayacağı
hizmetin altında kalır ve merkezi kapatmaya zorlamaz. Bütçe ve Nmax
kısıtları modelde durur; 5.3 doğrulama seti asıl maliyetleri kullanır.
"""

from __future__ import annotations

import random
import unicodedata

from data.section_5_3 import PLANNING_CENTERS
from model.instance import Center, Instance, Scenario, Site, TeamType
from model.problem import Solution

LIVE_RADIUS_KM = 8.0
LIVE_BUDGET = 1.0
LIVE_N_MAX = 2
LIVE_OPENING_COST = 0.01
LIVE_UMKE = 4
LIVE_MACHINERY = 2
LIVE_SEED = 20201123

SCENARIO_RATES = (
    ("iyimser", "İyimser", 0.2, 0.9),
    ("baz", "Baz", 0.5, 0.7),
    ("kotumser", "Kötümser", 1.0, 0.4),
)

PLAN_CAPTION = (
    "Here-and-now karar: hangi merkez açılır (G), hangi tip ekip orada bekler (V), "
    "UMKE (V^U) ve iş makinesi (V^W) nerede durur. Üç senaryo eşit ağırlıkla birlikte "
    "çözülür; yol açıklığı enkaz kimliğine göre sabit bir çekiliştir (tohum "
    f"{LIVE_SEED}, oranlar 0.9 / 0.7 / 0.4). Açma maliyeti sembolik {LIVE_OPENING_COST}, "
    f"bütçe {LIVE_BUDGET}, en fazla {LIVE_N_MAX} merkez, kapsama {LIVE_RADIUS_KM:.0f} km, "
    f"UMKE havuzu {LIVE_UMKE}, iş makinesi havuzu {LIVE_MACHINERY}. "
    "Ekip kapasitesi tip içi ortalamadır. Bu plan Supabase atamasını değiştirmez."
)


def build_live_instance(
    enkaz_rows: list[dict],
    ekip_rows: list[dict],
    *,
    seed: int = LIVE_SEED,
) -> Instance:
    sites = [_site_from_row(row) for row in sorted(enkaz_rows, key=lambda row: row["id"])]
    team_types = _team_types(ekip_rows)
    fleet = sum(team.N for team in team_types)
    centers = []
    for spec in PLANNING_CENTERS:
        centers.append(
            Center(
                j=spec.j,
                name=spec.name,
                lat=spec.lat,
                lon=spec.lon,
                f=LIVE_OPENING_COST,
                cap={team.k: team.N for team in team_types},
                cap_tot=max(fleet, 1),
                cap_u=LIVE_UMKE,
                cap_w=LIVE_MACHINERY,
            )
        )

    rng = random.Random(seed)
    scenarios = []
    for key, name, beta, rate in SCENARIO_RATES:
        # Kimlik sırasında çekilir; satır sırası sonucu değiştirmez.
        flags = {}
        for site in sites:
            flags[site.i] = 1 if rng.random() < rate else 0
        scenarios.append(Scenario(s=key, name=name, beta=beta, h=flags, pi=1.0))

    return Instance(
        centers=centers,
        team_types=team_types,
        sites=sites,
        scenarios=scenarios,
        B=LIVE_BUDGET,
        N_max=LIVE_N_MAX,
        N_U=LIVE_UMKE,
        N_W=LIVE_MACHINERY,
        radius_km=LIVE_RADIUS_KM,
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
        "opening_cost": solution.opening_cost,
        "unmet": solution.unmet_cost,
        "rows": rows,
        "opened_names": opened,
        "caption": PLAN_CAPTION,
    }


def _site_from_row(row: dict) -> Site:
    try:
        lat = float(row["enlem"])
        lon = float(row["boylam"])
        demand = float(row["talep"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Enkaz satırında enlem, boylam veya talep yok: {row.get('id')}") from exc
    name = str(row.get("isim") or row["id"])
    return Site(i=str(row["id"]), name=name, lat=lat, lon=lon, d=demand)


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
                N=len(capacities),
                q=sum(capacities) / len(capacities),
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
