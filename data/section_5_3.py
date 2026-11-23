"""Bölüm 5.3 küçük doğrulama seti.

Rapordaki 5 enkaz, 4 ekip ve 3 senaryo korunur. Aday merkezler raporda bu
kalemde geçmediği için Avcılar koordinatlı 3 merkez eklenmiştir. Yol açıklığı
oranları prototipteki h ∈ {0.9, 0.7, 0.4} ile aynıdır; 5 noktalık kümede
oranlar birebir tamsayı olmadığı için sabit bir gerçekleşme kullanılır
(açık yol sayıları 5, 4 ve 2).

Kapsama, 2.6 km yarıçapla şu matrise gelir:
    j1: i1, i2, i5
    j2: i2, i3
    j3: i4, i5
"""

from __future__ import annotations

from model.instance import Center, Instance, Scenario, Site, TeamType

RADIUS_KM = 2.6

# (j, i) -> r. Mesafe kuralının belgelenmiş sonucu; test bunu yeniden ölçer.
COVERAGE_53 = {
    ("j1", "i1"): 1,
    ("j1", "i2"): 1,
    ("j1", "i3"): 0,
    ("j1", "i4"): 0,
    ("j1", "i5"): 1,
    ("j2", "i1"): 0,
    ("j2", "i2"): 1,
    ("j2", "i3"): 1,
    ("j2", "i4"): 0,
    ("j2", "i5"): 0,
    ("j3", "i1"): 0,
    ("j3", "i2"): 0,
    ("j3", "i3"): 0,
    ("j3", "i4"): 1,
    ("j3", "i5"): 1,
}

_CENTER_SPECS = (
    # j, ad, enlem, boylam, f, cap_tot, cap_u, cap_w
    ("j1", "Avcılar Belediye Koordinasyon", 40.9790, 28.7210, 90.0, 3, 2, 1),
    ("j2", "Ambarlı Lojistik", 40.9605, 28.6855, 70.0, 3, 2, 1),
    ("j3", "Firuzköy Koordinasyon", 41.0065, 28.7660, 70.0, 3, 2, 1),
)

_TEAM_CAP = {"hafif": 2, "orta": 1, "agir": 1}


def planning_centers() -> list[Center]:
    """Canlı plan ve 5.3 için aynı üç aday nokta. Kapasiteler 5.3 setine göredir."""

    centers = []
    for j, name, lat, lon, cost, cap_tot, cap_u, cap_w in _CENTER_SPECS:
        centers.append(
            Center(
                j=j,
                name=name,
                lat=lat,
                lon=lon,
                f=cost,
                cap=dict(_TEAM_CAP),
                cap_tot=cap_tot,
                cap_u=cap_u,
                cap_w=cap_w,
            )
        )
    return centers


# Canlı adaptör koordinat ve adı buradan okur; kapasiteyi filoya göre ezer.
PLANNING_CENTERS = planning_centers()


def section_5_3() -> Instance:
    """Her çağrı yeni nesneler döndürür; testler örneği yerinde değiştirebilir."""

    centers = planning_centers()
    team_types = [
        TeamType(k="hafif", name="Hafif", N=2, q=120.0),
        TeamType(k="orta", name="Orta", N=1, q=180.0),
        TeamType(k="agir", name="Ağır", N=1, q=240.0),
    ]
    sites = [
        Site(i="i1", name="Avcılar-Merkez", lat=40.9840, lon=28.7275, d=180.0),
        Site(i="i2", name="Avcılar-Cihangir", lat=40.9698, lon=28.7035, d=140.0),
        Site(i="i3", name="Avcılar-Ambarlı", lat=40.9568, lon=28.6810, d=130.0),
        Site(i="i4", name="Avcılar-Firuzköy", lat=41.0112, lon=28.7725, d=160.0),
        Site(i="i5", name="Avcılar-Üniversite", lat=40.9938, lon=28.7445, d=110.0),
    ]
    # İyimser: 5/5 açık. Baz: i4 kapalı (4/5). Kötümser: yalnız i1 ve i4 (2/5).
    open_iyimser = {site.i: 1 for site in sites}
    open_baz = {site.i: 0 if site.i == "i4" else 1 for site in sites}
    open_kotumser = {site.i: 1 if site.i in {"i1", "i4"} else 0 for site in sites}
    scenarios = [
        Scenario(s="iyimser", name="İyimser", beta=0.2, h=open_iyimser, pi=1.0),
        Scenario(s="baz", name="Baz", beta=0.5, h=open_baz, pi=1.0),
        Scenario(s="kotumser", name="Kötümser", beta=1.0, h=open_kotumser, pi=1.0),
    ]
    return Instance(
        centers=centers,
        team_types=team_types,
        sites=sites,
        scenarios=scenarios,
        B=160.0,
        N_max=2,
        N_U=3,
        N_W=2,
        radius_km=RADIUS_KM,
    )
