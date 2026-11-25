"""Pareto adımları. Rapor (4.3), (4.4) ve (4.6).

1. Yalnız Z1, sonra Z1 sabitken Z2 → Z̄_2.
2. En az bir merkez açıkken en küçük Z2 → Z_2.
3. [Z_2, Z̄_2] üzerinde eşit aralıklı ε noktaları. Amaç Z1 + δ Z2, δ = 10^{-3}/Z̄_2.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from model.instance import Instance
from model.planning import solve_planning


@dataclass
class ParetoPoint:
    epsilon: float
    status: str
    z1: float | None
    z2: float | None
    gap: float | None
    open_centers: list[str]
    seconds: float | None


@dataclass
class ParetoSweep:
    z1_status: str
    z1: float | None
    z1_gap: float | None
    z1_bound: float | None
    z_bar_2: float | None
    z_bar_status: str
    z_low_2: float | None
    z_low_status: str
    delta: float | None
    points: list[ParetoPoint] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def pareto_sweep(
    instance: Instance,
    periods: int = 36,
    time_limit: int = 60,
    threads: int | None = None,
    points: int = 5,
    vartheta: float = 0.01,
) -> ParetoSweep:
    """Üç adım ve ε taraması. Her noktanın durumu olduğu gibi yazılır."""

    if points < 2:
        raise ValueError("en az iki ε noktası gerekir")
    z1_sol = solve_planning(
        instance,
        periods=periods,
        time_limit=time_limit,
        threads=threads,
        vartheta=vartheta,
        mode="z1",
    )
    result = ParetoSweep(
        z1_status=z1_sol.status,
        z1=z1_sol.z1,
        z1_gap=z1_sol.gap,
        z1_bound=z1_sol.lower_bound,
        z_bar_2=None,
        z_bar_status="",
        z_low_2=None,
        z_low_status="",
        delta=None,
    )
    if z1_sol.z1 is None:
        result.notes.append("Z1 için tamsayı çözüm yok; tarama durdu.")
        return result
    z_bar = solve_planning(
        instance,
        periods=periods,
        time_limit=time_limit,
        threads=threads,
        vartheta=vartheta,
        mode="z2",
        z1_cap=z1_sol.z1,
    )
    z_low = solve_planning(
        instance,
        periods=periods,
        time_limit=time_limit,
        threads=threads,
        vartheta=vartheta,
        mode="z2",
        min_centers=1,
    )
    result.z_bar_status = z_bar.status
    result.z_low_status = z_low.status
    result.z_bar_2 = z_bar.z2
    result.z_low_2 = z_low.z2
    if z_bar.z2 is None or z_low.z2 is None:
        result.notes.append("Z2 uçlarından biri bulunamadı; ε taraması yok.")
        return result
    if z_bar.z2 <= 1e-9:
        result.notes.append("Z̄_2 sıfır; δ tanımsız, tarama yapılmadı.")
        return result
    result.delta = 1e-3 / z_bar.z2
    lo = min(z_low.z2, z_bar.z2)
    hi = max(z_low.z2, z_bar.z2)
    if z_low.z2 > z_bar.z2 + 1e-4:
        result.notes.append("Alt uç üst uçtan büyük göründü; aralık uçların sırasına göre tarandı.")
    for index in range(points):
        epsilon = lo + index * (hi - lo) / (points - 1)
        solved = solve_planning(
            instance,
            periods=periods,
            time_limit=time_limit,
            threads=threads,
            vartheta=vartheta,
            mode="weighted",
            delta=result.delta,
            z2_cap=epsilon,
        )
        result.points.append(
            ParetoPoint(
                epsilon=epsilon,
                status=solved.status,
                z1=solved.z1,
                z2=solved.z2,
                gap=solved.gap,
                open_centers=[name for name, opened in solved.G.items() if opened],
                seconds=solved.seconds,
            )
        )
    return result
