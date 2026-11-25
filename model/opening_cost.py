"""Merkez açma maliyeti, rapor (4.6).

Saf fonksiyon. Çözücü çağırmaz.

β̄, HYK kararıyla olasılık ağırlıklı senaryo ortalamasıdır:
β̄_i = Σ_s P_s β_{i,s}. 5.3'te β periyot boyunca sabittir; periyot ortalaması
aynı sayıyı verir. β güzergâhın enkazına bağlıdır, merkeze değil, bu yüzden
β̄_{i,j} = β̄_i.

τ̄_{i,j} = τ_{i,j}(1 + β̄_i). En yakın ve ikinci en yakın merkez bu süreye göredir.
Eşit τ̄'de merkez listesindeki sıra kazanır; 5.3'te eşitlik yoktur.

π_i = Σ_s P_s · 1[m^A_i > 0]. Bu doğrulamada m^A senaryodan bağımsızdır.
Ψ_j = Σ_{i ∈ I_j} π_i γ_i (τ̄_{i,j2(i)} − τ̄_{i,j}), f = (Σ_j Ψ_j) / |J|.

Φ_j = Σ_k C_{j,k} + U_{j,max} + W_{j,max}. Φ̄ aday merkezlerin ortalama
kapasitesidir. f_j = f · Φ_j / Φ̄.
"""

from __future__ import annotations

from dataclasses import dataclass

from model.instance import Instance


@dataclass(frozen=True)
class OpeningCost:
    """(4.6) ve f_j dağılımı."""

    beta_bar: dict[str, float]
    tau_bar: dict[tuple[str, str], float]
    nearest: dict[str, str]
    second: dict[str, str]
    pi: dict[str, float]
    psi: dict[str, float]
    f: float
    phi: dict[str, float]
    phi_bar: float
    f_j: dict[str, float]


def calibrate_opening_cost(instance: Instance) -> OpeningCost:
    """Olasılık ağırlıklı β̄, τ̄, Ψ_j, f ve f_j."""

    if len(instance.centers) < 2:
        raise ValueError("(4.6) ikinci en yakın merkezi ister; |J| < 2")
    if not instance.scenarios:
        raise ValueError("(4.6) en az bir senaryo ister")

    beta_bar = {site.i: _beta_bar(instance, site.i) for site in instance.sites}
    tau_bar: dict[tuple[str, str], float] = {}
    for center in instance.centers:
        for site in instance.sites:
            tau = instance.tau[(center.j, site.i)]
            tau_bar[(center.j, site.i)] = tau * (1.0 + beta_bar[site.i])

    nearest: dict[str, str] = {}
    second: dict[str, str] = {}
    for site in instance.sites:
        ordered = sorted(
            instance.centers,
            key=lambda center: (tau_bar[(center.j, site.i)], _center_index(instance, center.j)),
        )
        nearest[site.i] = ordered[0].j
        second[site.i] = ordered[1].j

    probability = sum(scenario.P for scenario in instance.scenarios)
    pi = {site.i: probability if site.m > 0 else 0.0 for site in instance.sites}

    psi = {center.j: 0.0 for center in instance.centers}
    for site in instance.sites:
        if site.gamma is None:
            raise ValueError(f"γ_{site.i} yok; (4.6) hasar ağırlığı ister")
        home = nearest[site.i]
        other = second[site.i]
        extra = tau_bar[(other, site.i)] - tau_bar[(home, site.i)]
        psi[home] += pi[site.i] * site.gamma * extra

    f = sum(psi.values()) / len(instance.centers)
    phi = {center.j: _phi(instance, center.j) for center in instance.centers}
    phi_bar = sum(phi.values()) / len(instance.centers)
    if phi_bar == 0:
        raise ValueError("Φ̄ = 0; f_j tanımsız")
    f_j = {center.j: f * phi[center.j] / phi_bar for center in instance.centers}
    return OpeningCost(
        beta_bar=beta_bar,
        tau_bar=tau_bar,
        nearest=nearest,
        second=second,
        pi=pi,
        psi=psi,
        f=f,
        phi=phi,
        phi_bar=phi_bar,
        f_j=f_j,
    )


def _beta_bar(instance: Instance, site_i: str) -> float:
    """β̄_i = Σ_s P_s β_{i,s}. Periyot profili bu kalemde yoktur."""

    total = 0.0
    for scenario in instance.scenarios:
        if scenario.beta_t:
            raise ValueError(
                "(4.6) bu kalemde senaryo β'sini kullanır; "
                "5.3'te β periyot boyunca sabittir."
            )
        total += scenario.P * scenario.beta[site_i]
    return total


def _phi(instance: Instance, center_j: str) -> float:
    """Φ_j = Σ_k C_{j,k} + U_{j,max} + W_{j,max}."""

    center = next(item for item in instance.centers if item.j == center_j)
    capacity = sum(center.C[team.k] for team in instance.team_types)
    return float(capacity + center.U_max + center.W_max)


def _center_index(instance: Instance, center_j: str) -> int:
    for index, center in enumerate(instance.centers):
        if center.j == center_j:
            return index
    raise KeyError(center_j)
