"""Ziyaret kayıtları ve izinli bağlantılar. Rapor 4.3.1 ve 4.3.2.

Düğümler periyotlu kurulur: enkaz (i, t), merkez (j, t, ℓ), başlangıç kaydı
o_j, rota uçları σ ve ω, ufuk sonu dönüş kaydı ω^yol_j. A_s çözümden önce
aşağıdaki kurallarla üretilir. ℓ = 1, …, |I|+1 aynı periyottaki tekrar
merkez ziyaretlerini ayırır; yeni merkez değildir.

Bu kalemin yer tutucuları (Bas/Bit ve periyot aşan yolculuk madde 3 ve 4):

- Gerçek hareket yalnız çıkış periyodunun içinde bağlanır: t(v) = t(u).
- τ tablosunda yalnız merkez–enkaz vardır. Dönüş için τ_{i,j} = τ_{j,i}.
  Enkaz–enkaz süresi tabloda yoktur; o yay kurulmaz.
- β periyoda ayrılmaz. h_{n,n',t,s} her t için aynıdır.
- ω^yol_j yayı, h = 1 olan son periyot dönüşlerinde durur. Varışın 72. saati
  aşıp aşmadığı süre hesabı olmadan bilinemez.
- Rapor çevrimi pozitif süreyle keser. Süre modeli gelene kadar aynı periyottaki
  yaylar enkaz listesinin sırasına göre yönlenir: sıra r, ℓ = r+1 kopyasına
  döner; ℓ kopyası yalnız sırası ≥ ℓ olan enkazlara çıkar. Ziyaret kümesi
  bundan etkilenmez; sıra artan indise oturur. Graf çevrimsizdir.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.instance import Instance, Scenario, route_open

TAM_KINDS = frozenset({"travel", "continue", "wait"})


@dataclass(frozen=True)
class Visit:
    """Ziyaret kaydı. σ ve ω fiziksel değildir. o_j için t = 1, n = j."""

    kind: str
    j: str = ""
    i: str = ""
    t: int = 0
    ell: int = 0

    @property
    def key(self) -> str:
        if self.kind == "sigma":
            return "sigma"
        if self.kind == "omega":
            return "omega"
        if self.kind == "origin":
            return f"o_{self.j}"
        if self.kind == "debris":
            return f"d_{self.i}_t{self.t}"
        if self.kind == "center":
            return f"c_{self.j}_t{self.t}_l{self.ell}"
        if self.kind == "enroute":
            return f"wy_{self.j}"
        raise ValueError(f"bilinmeyen ziyaret: {self.kind}")

    @property
    def label(self) -> str:
        if self.kind == "sigma":
            return "σ"
        if self.kind == "omega":
            return "ω"
        if self.kind == "origin":
            return f"o_{self.j}"
        if self.kind == "debris":
            return f"({self.i},{self.t})"
        if self.kind == "center":
            return f"({self.j},{self.t},{self.ell})"
        if self.kind == "enroute":
            return f"ω^yol_{self.j}"
        raise ValueError(f"bilinmeyen ziyaret: {self.kind}")

    def physical(self) -> str | None:
        """n(v). σ, ω ve yolda bitiş kaydının normal noktası yoktur."""

        if self.kind in {"origin", "center"}:
            return self.j
        if self.kind == "debris":
            return self.i
        return None

    def period(self) -> int | None:
        """t(v). Başlangıç kaydı 1. periyottadır."""

        if self.kind == "origin":
            return 1
        if self.kind in {"debris", "center"}:
            return self.t
        return None


@dataclass(frozen=True)
class Arc:
    """A_s içindeki yönlü bağlantı. tam, A_s^{tam} üyesidir."""

    u: Visit
    v: Visit
    kind: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.u.key, self.v.key)

    @property
    def tam(self) -> bool:
        return self.kind in TAM_KINDS


@dataclass
class Network:
    """Bütün senaryoların ziyaret kayıtları ve A_s kümeleri."""

    periods: int
    sigma: Visit
    omega: Visit
    visits: list[Visit]
    by_key: dict[str, Visit]
    arcs: dict[str, list[Arc]]
    by_arc: dict[str, dict[tuple[str, str], Arc]]


def route_h(instance: Instance, n: str, n2: str, t: int, scenario: Scenario) -> int:
    """h_{n,n',t,s}. Rapor 4.3: açık ve τ(1+β) ≤ L ise 1.

    Çizelge 5.1 β'yi periyoda ayırmaz; bu kalemde her t aynı değeri verir.
    Dönüşte τ_{i,j} = τ_{j,i} alınır. Merkezler arası doğrudan hareket yoktur.
    τ'si olmayan çift (enkaz–enkaz) kullanılamaz.
    """

    if t < 1:
        return 0
    centers = {center.j for center in instance.centers}
    sites = {site.i for site in instance.sites}
    if n in centers and n2 in centers:
        return 0
    if n == n2 or n not in centers | sites or n2 not in centers | sites:
        return 0
    tau = instance.tau.get((n, n2))
    if tau is None:
        tau = instance.tau.get((n2, n))
    if tau is None:
        return 0
    debris = n2 if n2 in sites else n
    beta = scenario.beta.get(debris)
    if beta is None:
        return 0
    return route_open(tau, beta, instance.L)


def is_site_entry(arc: Arc, site_i: str) -> bool:
    """(4.23) toplamı: A^{tam} içinden (i, t)'ye, n(u) ≠ i olan giriş."""

    if not arc.tam or arc.v.kind != "debris" or arc.v.i != site_i:
        return False
    origin = arc.u.physical()
    return origin is not None and origin != site_i


def build_network(instance: Instance, periods: int) -> Network:
    """A_s'yi 4.3.2 kurallarıyla kurar. periods en az 1'dir."""

    if periods < 1:
        raise ValueError("periyot sayısı en az 1 olmalı")

    sigma = Visit("sigma")
    omega = Visit("omega")
    origins = [Visit("origin", j=center.j) for center in instance.centers]
    debris = [
        Visit("debris", i=site.i, t=t)
        for site in instance.sites
        for t in range(1, periods + 1)
    ]
    debris_at = {(visit.i, visit.t): visit for visit in debris}
    copies = len(instance.sites) + 1
    site_rank = {site.i: index + 1 for index, site in enumerate(instance.sites)}
    center_visits = [
        Visit("center", j=center.j, t=t, ell=ell)
        for center in instance.centers
        for t in range(1, periods + 1)
        for ell in range(1, copies + 1)
    ]
    center_at = {(visit.j, visit.t, visit.ell): visit for visit in center_visits}
    enroutes = [Visit("enroute", j=center.j) for center in instance.centers]
    enroute_of = {visit.j: visit for visit in enroutes}
    visits = origins + debris + center_visits + enroutes
    by_key = {sigma.key: sigma, omega.key: omega}
    for visit in visits:
        by_key[visit.key] = visit

    arcs: dict[str, list[Arc]] = {}
    by_arc: dict[str, dict[tuple[str, str], Arc]] = {}
    for scenario in instance.scenarios:
        found: dict[tuple[str, str], Arc] = {}

        def add(arc: Arc) -> None:
            if arc.key in found:
                raise RuntimeError(f"yinelenen yay {arc.key} ({scenario.s})")
            found[arc.key] = arc

        # 1. σ → o_j ve tahsis edilmeyen ekip için σ → ω.
        for origin in origins:
            add(Arc(sigma, origin, "start"))
        add(Arc(sigma, omega, "start"))

        for origin in origins:
            # 4. Başlangıç merkezi kaydı ω'ya bağlanabilir.
            add(Arc(origin, omega, "end"))
            first = center_at.get((origin.j, 1, 1))
            if first is not None:
                add(Arc(origin, first, "wait"))
            for site in instance.sites:
                if route_h(instance, origin.j, site.i, 1, scenario) == 1:
                    add(Arc(origin, debris_at[(site.i, 1)], "travel"))

        for visit in center_visits:
            add(Arc(visit, omega, "end"))
            # 3. Aynı periyotta ℓ artar.
            if visit.ell < copies:
                add(Arc(visit, center_at[(visit.j, visit.t, visit.ell + 1)], "wait"))
            # Periyot ilerler. Ara kopyalar zorunlu uğrak değildir.
            if visit.t < periods:
                add(Arc(visit, center_at[(visit.j, visit.t + 1, 1)], "wait"))
            for site in instance.sites:
                # ℓ kopyası, listede kendisinden sonra (veya kendisi) gelen enkazlara çıkar.
                if site_rank[site.i] < visit.ell:
                    continue
                if route_h(instance, visit.j, site.i, visit.t, scenario) == 1:
                    add(Arc(visit, debris_at[(site.i, visit.t)], "travel"))

        for visit in debris:
            # 2. Geçmiş periyoda dönüş yok. 3. Devam yalnız (i, t) → (i, t+1).
            if visit.t < periods:
                add(Arc(visit, debris_at[(visit.i, visit.t + 1)], "continue"))
            # 4. Enkazdan ω yalnız son periyotta.
            if visit.t == periods:
                add(Arc(visit, omega, "end"))
                # 5. Ufuk sonunda sürebilecek dönüş. Süre testi madde 3'tedir.
                for center in instance.centers:
                    if route_h(instance, visit.i, center.j, visit.t, scenario) == 1:
                        add(Arc(visit, enroute_of[center.j], "enroute"))
            # Dönüş yalnız bir sonraki kopyaya. Böylece aynı periyotta çevrim oluşmaz.
            return_ell = site_rank[visit.i] + 1
            if return_ell <= copies:
                for center in instance.centers:
                    if route_h(instance, visit.i, center.j, visit.t, scenario) == 1:
                        add(Arc(visit, center_at[(center.j, visit.t, return_ell)], "travel"))

        for visit in enroutes:
            add(Arc(visit, omega, "enroute_end"))

        arcs[scenario.s] = list(found.values())
        by_arc[scenario.s] = found

    return Network(
        periods=periods,
        sigma=sigma,
        omega=omega,
        visits=visits,
        by_key=by_key,
        arcs=arcs,
        by_arc=by_arc,
    )
