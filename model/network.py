"""Ziyaret kayıtları ve izinli bağlantılar. Rapor 4.3.1, 4.3.2 ve (4.1).

Düğümler periyotludur: enkaz (i, t), merkez (j, t, ℓ), başlangıç kaydı o_j,
rota uçları σ ve ω, ufuk sonu dönüş kaydı ω^yol_j. ℓ = 1, …, |I|+1 aynı
periyottaki tekrar merkez ziyaretlerini ayırır; yeni merkez değildir.

Gerçek hareketin β ve h değeri çıkış periyoduna aittir. Seyahat bir periyot
sınırını aşabilir: varış, varış saatinin düştüğü periyodun kaydına yazılır.
Aynı yerdeki devam ve bekleme seyri sıfırdır. Ufuk sonunda yetişmeyecek
merkez dönüşü ω^yol_j ile durur; ekip merkeze varmış sayılmaz.

Çevrim, enkaz sırasıyla kesilmez. Farklı noktalar arasında süre pozitiftir;
aynı periyotta ℓ artar. Seçilen çevrimi süre eşitlikleri (4.29)–(4.30) bozar.
Grafın kendisi, aynı periyotta gidilip dönülebildiği için çevrim içerebilir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from model.instance import Instance, Scenario

REPORT_PERIODS = 36
TAM_KINDS = frozenset({"travel", "continue", "wait"})
TIME_TOL = 1e-9


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
    """A_s içindeki yönlü bağlantı. tam, A_s^{tam} üyesidir.

    sey, (4.1). departure_t, β ve h'nin okunduğu çıkış periyodudur.
    """

    u: Visit
    v: Visit
    kind: str
    sey: float = 0.0
    departure_t: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.u.key, self.v.key)

    @property
    def tam(self) -> bool:
        return self.kind in TAM_KINDS

    @property
    def crosses(self) -> bool:
        start = self.u.period()
        end = self.v.period()
        return start is not None and end is not None and end > start


@dataclass
class Network:
    """Bütün senaryoların ziyaret kayıtları ve A_s kümeleri."""

    periods: int
    horizon: float
    big_m: float
    sigma: Visit
    omega: Visit
    visits: list[Visit]
    by_key: dict[str, Visit]
    arcs: dict[str, list[Arc]]
    by_arc: dict[str, dict[tuple[str, str], Arc]]
    # (n, n', t) -> çıkış periyodu t olan gerçek hareketler. ω^yol dahildir.
    har: dict[str, dict[tuple[str, str, int], list[Arc]]] = field(default_factory=dict)
    # (j, t) -> merkez j'ye t periyodunda varan gerçek bağlantılar. ω^yol yoktur.
    arrivals: dict[str, dict[tuple[str, int], list[Arc]]] = field(default_factory=dict)


def horizon_hours(periods: int, period_hours: float) -> float:
    """H = L|T|."""

    return period_hours * periods


def beta_at(instance: Instance, scenario: Scenario, n: str, n2: str, t: int) -> float | None:
    """β_{n,n',t,s}. Çizelge 5.1 site bazlıdır; beta_t varsa çıkış periyodu kazanır."""

    sites = {site.i for site in instance.sites}
    debris = n2 if n2 in sites else n if n in sites else None
    if debris is None:
        return None
    if scenario.beta_t is not None and (debris, t) in scenario.beta_t:
        return scenario.beta_t[(debris, t)]
    return scenario.beta.get(debris)


def travel_sey(
    instance: Instance,
    n: str,
    n2: str,
    t: int,
    scenario: Scenario,
) -> float | None:
    """(4.1)'in farklı noktalar kolu. τ yoksa veya iki merkezse None.

    Dönüşte τ_{i,j} = τ_{j,i}. Enkaz–enkaz süresi tabloda yoktur.
    """

    centers = {center.j for center in instance.centers}
    sites = {site.i for site in instance.sites}
    if n in centers and n2 in centers:
        return None
    if n == n2 or n not in centers | sites or n2 not in centers | sites:
        return None
    tau = instance.tau.get((n, n2))
    if tau is None:
        tau = instance.tau.get((n2, n))
    if tau is None:
        return None
    beta = beta_at(instance, scenario, n, n2, t)
    if beta is None:
        return None
    return tau * (1.0 + beta)


def route_h(instance: Instance, n: str, n2: str, t: int, scenario: Scenario) -> int:
    """(4.26). h_{n,n',t,s} = 1 ancak çıkış periyodunda açık ve τ(1+β) ≤ L ise."""

    if t < 1:
        return 0
    sey = travel_sey(instance, n, n2, t, scenario)
    if sey is None:
        return 0
    return 1 if sey <= instance.L + TIME_TOL else 0


def arrival_periods(t_dep: int, sey: float, period_hours: float, periods: int) -> list[int]:
    """Varış saati aralığının kesiştiği periyotlar.

    Çıkış, çıkış penceresinin herhangi bir saatinde olabilir. Varış penceresi
    [L(t-1), Lt] ile kesişen her t_arr bir kayıt adayıdır. Sınır saati iki
    pencereye de girer; çözüm bunlardan birini seçer.
    """

    earliest = period_hours * (t_dep - 1) + sey
    latest = period_hours * t_dep + sey
    found: list[int] = []
    for t_arr in range(max(1, t_dep), periods + 1):
        lo = period_hours * (t_arr - 1)
        hi = period_hours * t_arr
        if earliest <= hi + TIME_TOL and latest >= lo - TIME_TOL:
            found.append(t_arr)
        elif lo > latest + TIME_TOL:
            break
    return found


def may_miss_horizon(t_dep: int, sey: float, period_hours: float, horizon: float) -> bool:
    """Bu çıkış periyodunda dönüş H anına yetişmeyebilir."""

    latest = period_hours * t_dep + sey
    return latest >= horizon - TIME_TOL


def is_site_entry(arc: Arc, site_i: str) -> bool:
    """(4.23) toplamı: A^{tam} içinden (i, t)'ye, n(u) ≠ i olan giriş."""

    if not arc.tam or arc.v.kind != "debris" or arc.v.i != site_i:
        return False
    origin = arc.u.physical()
    return origin is not None and origin != site_i


def time_window(visit: Visit, period_hours: float) -> tuple[float, float] | None:
    """(4.24) penceresi. Başlangıç kaydında Bit üst sınırı L'dir; Bas 0'dır."""

    if visit.kind == "origin":
        return (0.0, period_hours)
    period = visit.period()
    if period is None:
        return None
    return (period_hours * (period - 1), period_hours * period)


def build_network(instance: Instance, periods: int) -> Network:
    """A_s'yi 4.3.2 kurallarıyla kurar. periods en az 1'dir."""

    if periods < 1:
        raise ValueError("periyot sayısı en az 1 olmalı")

    length = instance.L
    horizon = horizon_hours(periods, length)
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

    center_ids = [center.j for center in instance.centers]
    site_ids = [site.i for site in instance.sites]
    arcs: dict[str, list[Arc]] = {}
    by_arc: dict[str, dict[tuple[str, str], Arc]] = {}
    har: dict[str, dict[tuple[str, str, int], list[Arc]]] = {}
    arrivals: dict[str, dict[tuple[str, int], list[Arc]]] = {}

    for scenario in instance.scenarios:
        found: dict[tuple[str, str], Arc] = {}
        har_s: dict[tuple[str, str, int], list[Arc]] = {}
        arr_s: dict[tuple[str, int], list[Arc]] = {}

        def add(arc: Arc) -> None:
            if arc.key in found:
                raise RuntimeError(f"yinelenen yay {arc.key} ({scenario.s})")
            found[arc.key] = arc
            if arc.kind in {"travel", "enroute"} and arc.departure_t is not None:
                tail = arc.u.physical()
                head = arc.v.j if arc.kind == "enroute" else arc.v.physical()
                if tail and head:
                    har_s.setdefault((tail, head, arc.departure_t), []).append(arc)
            if arc.kind == "travel" and arc.v.kind == "center":
                arr_s.setdefault((arc.v.j, arc.v.t), []).append(arc)

        def add_outbound(node: Visit, t_dep: int) -> None:
            origin = node.physical()
            if origin is None:
                return
            for site_i in site_ids:
                if route_h(instance, origin, site_i, t_dep, scenario) != 1:
                    continue
                sey = travel_sey(instance, origin, site_i, t_dep, scenario)
                if sey is None:
                    continue
                for t_arr in arrival_periods(t_dep, sey, length, periods):
                    add(
                        Arc(
                            node,
                            debris_at[(site_i, t_arr)],
                            "travel",
                            sey=sey,
                            departure_t=t_dep,
                        )
                    )

        def add_returns(node: Visit) -> None:
            for center_j in center_ids:
                if route_h(instance, node.i, center_j, node.t, scenario) != 1:
                    continue
                sey = travel_sey(instance, node.i, center_j, node.t, scenario)
                if sey is None:
                    continue
                for t_arr in arrival_periods(node.t, sey, length, periods):
                    for ell in range(1, copies + 1):
                        add(
                            Arc(
                                node,
                                center_at[(center_j, t_arr, ell)],
                                "travel",
                                sey=sey,
                                departure_t=node.t,
                            )
                        )
                if may_miss_horizon(node.t, sey, length, horizon):
                    add(
                        Arc(
                            node,
                            enroute_of[center_j],
                            "enroute",
                            sey=sey,
                            departure_t=node.t,
                        )
                    )

        # 1. σ → o_j ve tahsis edilmeyen ekip için σ → ω.
        for origin in origins:
            add(Arc(sigma, origin, "start"))
        add(Arc(sigma, omega, "start"))

        for origin in origins:
            # 4. Başlangıç merkezi kaydı ω'ya bağlanabilir.
            add(Arc(origin, omega, "end", departure_t=1))
            first = center_at.get((origin.j, 1, 1))
            if first is not None:
                add(Arc(origin, first, "wait", sey=0.0, departure_t=1))
            add_outbound(origin, 1)

        for visit in center_visits:
            add(Arc(visit, omega, "end", departure_t=visit.t))
            # 3. Aynı periyotta ℓ artar. Periyot ilerleyince ilk kopya.
            if visit.ell < copies:
                add(
                    Arc(
                        visit,
                        center_at[(visit.j, visit.t, visit.ell + 1)],
                        "wait",
                        sey=0.0,
                        departure_t=visit.t,
                    )
                )
            if visit.t < periods:
                add(
                    Arc(
                        visit,
                        center_at[(visit.j, visit.t + 1, 1)],
                        "wait",
                        sey=0.0,
                        departure_t=visit.t,
                    )
                )
            add_outbound(visit, visit.t)

        for visit in debris:
            # 3. Devam yalnız (i, t) → (i, t+1), seyir 0.
            if visit.t < periods:
                add(
                    Arc(
                        visit,
                        debris_at[(visit.i, visit.t + 1)],
                        "continue",
                        sey=0.0,
                        departure_t=visit.t,
                    )
                )
            # 4. Enkazdan ω yalnız son periyotta.
            if visit.t == periods:
                add(Arc(visit, omega, "end", departure_t=visit.t))
            # 2 ve 5. Dönüş, varış periyoduna; yetişmeyen dönüş ω^yol'a.
            add_returns(visit)

        for visit in enroutes:
            add(Arc(visit, omega, "enroute_end"))

        arcs[scenario.s] = list(found.values())
        by_arc[scenario.s] = found
        har[scenario.s] = har_s
        arrivals[scenario.s] = arr_s

    return Network(
        periods=periods,
        horizon=horizon,
        big_m=horizon + length,
        sigma=sigma,
        omega=omega,
        visits=visits,
        by_key=by_key,
        arcs=arcs,
        by_arc=by_arc,
        har=har,
        arrivals=arrivals,
    )
