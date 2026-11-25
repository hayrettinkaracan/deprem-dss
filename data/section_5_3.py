"""Çizelge 5.1 ve Bölüm 5.3 (END4902_20261125).

Kişi talebi D yoktur. Enkaz–enkaz τ_{i,i'} ve saat 1, 3, 5, 7, 9, 11 kayıtlarının
içeriği raporda yoktur; burada da yoktur. Yay kurulmaz, olay uydurulmaz.

m^U ve m^W, 5.3.1'deki tepe oranlarla türetilir: m^U = 0,3 m^A;
E_i = 1 ise m^W = 0,5 m^A, değilse 0. İş yükleri üç senaryoda aynıdır.
β periyoda göre değişmez; beta_t yazılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.instance import Center, Instance, Scenario, Site, TeamType

PERIODS = 36
PERIOD_HOURS = 2.0

# Bölüm 5.3: 3 UMKE ekibi, 2 ağır iş makinesi.
U_TOP = 3
W_TOP = 2

# 5.3.1, Bölüm 5.2 üçgenlerinin tepe değerleri.
RHO_U = 0.3
RHO_W = 0.5

# Hasar sınıfı sırası. a_{i,k} = 1 ancak k, κ_i'ye eşit ya da ondan yüksekse (4.3).
_DAMAGE_RANK = {"Hafif": 1, "Orta": 2, "Ağır": 3}
_TEAM_RANK = {"hafif": 1, "orta": 2, "agir": 3}
_GAMMA = {"Hafif": 1, "Orta": 2, "Ağır": 3}

# Çizelge 5.1: i, κ, m^A, E, τ_J1, τ_J2. γ hasar sınıfındandır.
_TABLE = (
    ("I1", "Ağır", 4.0, 1, 0.8, 1.2),
    ("I2", "Orta", 3.0, 1, 0.5, 1.0),
    ("I3", "Orta", 2.5, 0, 1.2, 0.5),
    ("I4", "Hafif", 1.5, 0, 1.3, 0.8),
    ("I5", "Ağır", 4.5, 1, 1.3, 1.0),
)


@dataclass(frozen=True)
class HykKarari:
    """HYK kararı (rapor sayı vermiyor).

    Rapor bu parametreleri sayı olarak kilitlemez. Uygulanan kural burada durur.
    N_max = |J| bağlayıcı değildir; kısıt (4.10) modelde durur.
    ϑ çözücüye bu kalemde girmez; (4.18) sonraki iştir.
    """

    baslik: str
    N_max_kurali: str
    C_jk: str
    U_j_max_kurali: str
    W_j_max_kurali: str
    U_top: int
    W_top: int
    vartheta: float
    beta_bar: str


HYK_KARARI = HykKarari(
    baslik="HYK kararı (rapor sayı vermiyor)",
    N_max_kurali="|J|",
    C_jk="A_k",
    U_j_max_kurali="U_top",
    W_j_max_kurali="W_top",
    U_top=U_TOP,
    W_top=W_TOP,
    vartheta=0.01,
    beta_bar="olasılık ağırlıklı senaryo ortalaması",
)


def afad_competency(damage: str, team_k: str) -> int:
    """a_{i,k}. k yetkinliği κ_i'ye eşit ya da daha yüksekse 1."""

    return 1 if _TEAM_RANK[team_k] >= _DAMAGE_RANK[damage] else 0


def section_5_3() -> Instance:
    sites = []
    tau: dict[tuple[str, str], float] = {}
    for site_i, damage, m_a, machine, tau_j1, tau_j2 in _TABLE:
        m_u = RHO_U * m_a
        m_w = RHO_W * m_a if machine == 1 else 0.0
        sites.append(
            Site(
                i=site_i,
                name=site_i,
                m=m_a,
                E=machine,
                damage=damage,
                gamma=float(_GAMMA[damage]),
                m_U=m_u,
                m_W=m_w,
            )
        )
        tau[("J1", site_i)] = tau_j1
        tau[("J2", site_i)] = tau_j2

    team_types = [
        TeamType(k="hafif", name="Hafif", A=1, p=1.0),
        TeamType(k="orta", name="Orta", A=2, p=1.0),
        TeamType(k="agir", name="Ağır", A=1, p=1.0),
    ]
    # HYK kararı (rapor sayı vermiyor): C_{j,k} = A_k, U_{j,max} = U^top, W_{j,max} = W^top.
    capacity = {team.k: team.A for team in team_types}
    centers = [
        Center(j="J1", name="J1", C=dict(capacity), U_max=HYK_KARARI.U_top, W_max=HYK_KARARI.W_top),
        Center(j="J2", name="J2", C=dict(capacity), U_max=HYK_KARARI.U_top, W_max=HYK_KARARI.W_top),
    ]
    competency = {
        (site.i, team.k): afad_competency(site.damage, team.k)
        for site in sites
        for team in team_types
    }
    beta_s1 = {site.i: 0.10 for site in sites}
    beta_s2 = {site.i: 0.30 if site.i in {"I1", "I5"} else 0.15 for site in sites}
    beta_s3 = {site.i: 0.50 for site in sites}
    scenarios = [
        Scenario(s="s1", name="İyimser", P=0.30, D=None, beta=beta_s1),
        Scenario(s="s2", name="Beklenen", P=0.45, D=None, beta=beta_s2),
        Scenario(s="s3", name="Kötümser", P=0.25, D=None, beta=beta_s3),
    ]
    return Instance(
        centers=centers,
        team_types=team_types,
        sites=sites,
        scenarios=scenarios,
        tau=tau,
        # HYK kararı (rapor sayı vermiyor): N_max = |J|. (4.10) durur, bağlayıcı değildir.
        N_max=len(centers),
        U_top=HYK_KARARI.U_top,
        W_top=HYK_KARARI.W_top,
        L=PERIOD_HOURS,
        a=competency,
    )
