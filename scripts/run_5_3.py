"""5.3 Z1 ve Pareto koşusu. Uzun CBC işi bu makinede değil, yerelde çalışır.

    python -m scripts.run_5_3 --mode z1 --time-limit 900 --threads 4 --out docs/sonuclar_5_3.md
    python -m scripts.run_5_3 --mode pareto --time-limit 120 --threads 4 --out docs/sonuclar_5_3.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from data.section_5_3 import HYK_KARARI, section_5_3
from model.pareto import ParetoSweep, pareto_sweep
from model.planning import solve_planning


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="5.3 planlama koşusu")
    parser.add_argument("--mode", choices=("z1", "pareto"), required=True)
    parser.add_argument("--time-limit", type=int, default=900)
    parser.add_argument("--threads", type=int, default=0, help="0 ise bütün çekirdekler")
    parser.add_argument("--periods", type=int, default=36)
    parser.add_argument("--points", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("docs/sonuclar_5_3.md"))
    args = parser.parse_args(argv)
    threads = None if args.threads == 0 else args.threads
    instance = section_5_3()
    if args.mode == "z1":
        solution = solve_planning(
            instance,
            periods=args.periods,
            time_limit=args.time_limit,
            threads=threads,
            vartheta=HYK_KARARI.vartheta,
            mode="z1",
        )
        text = _z1_markdown(solution, args.time_limit, threads or "tümü")
    else:
        sweep = pareto_sweep(
            instance,
            periods=args.periods,
            time_limit=args.time_limit,
            threads=threads,
            points=args.points,
            vartheta=HYK_KARARI.vartheta,
        )
        text = _pareto_markdown(sweep, args.time_limit, threads or "tümü")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"yazıldı: {args.out}")


def _z1_markdown(solution, time_limit: int, threads) -> str:
    lines = [
        "# 5.3 planlama sonucu (Z1)",
        "",
        "Bu dosya `python -m scripts.run_5_3 --mode z1` ile üretildi.",
        "Amaç yalnız (4.2). (4.28), Z2 ve ε yok.",
        "",
        f"- Durum: {solution.status}",
        f"- Süre sınırı: {time_limit} s, çekirdek: {threads}",
        f"- Çözücü duvar saati: {solution.seconds}",
        f"- Z1: {_num(solution.z1)}",
        f"- Alt sınır: {_num(solution.lower_bound)}",
        f"- CBC aralığı (Z1 − alt sınır) / alt sınır: {_num(solution.gap)}",
        "",
        "Aralık 0 değilse sonuç kanıtlanmış optimal değildir.",
        "",
        "## Senaryo",
        "",
        "| Senaryo | Z1_s |",
        "|---|---:|",
    ]
    for key, value in solution.z1_by_scenario.items():
        lines.append(f"| {key} | {_num(value)} |")
    lines.extend(["", "## Açık merkezler ve yerleştirme", ""])
    lines.append(f"G = `{solution.G}`")
    lines.append(f"V = `{solution.V}`")
    lines.append(f"V^U = `{solution.VU}`")
    lines.append(f"V^W = `{solution.VW}`")
    lines.extend(["", "## Zincirler", ""])
    for (team, scenario), chain in solution.chains.items():
        lines.append(f"- {team} {scenario}: {' → '.join(chain) if chain else '(yok)'}")
    if solution.log_excerpt:
        lines.extend(["", "## Çözücü çıktısı", "", "```", solution.log_excerpt, "```"])
    lines.append("")
    return "\n".join(lines)


def _pareto_markdown(sweep: ParetoSweep, time_limit: int, threads) -> str:
    lines = [
        "# 5.3 Pareto taraması",
        "",
        "Bu dosya `python -m scripts.run_5_3 --mode pareto` ile üretildi.",
        "Z2 (4.3), δ = 10^{-3}/Z̄_2, ε kısıtı (4.4). f_j (4.6) kalibrasyonundan gelir.",
        "",
        f"- Her nokta için süre sınırı: {time_limit} s, çekirdek: {threads}",
        f"- Z1 durumu: {sweep.z1_status}, Z1 = {_num(sweep.z1)}, aralık {_num(sweep.z1_gap)}, alt sınır {_num(sweep.z1_bound)}",
        f"- Z̄_2 durumu: {sweep.z_bar_status}, Z̄_2 = {_num(sweep.z_bar_2)}",
        f"- Z_2 durumu: {sweep.z_low_status}, Z_2 = {_num(sweep.z_low_2)}",
        f"- δ = {_num(sweep.delta)}",
        "",
    ]
    for note in sweep.notes:
        lines.append(f"- Not: {note}")
    lines.extend(
        [
            "",
            "| ε | durum | Z1 | Z2 | aralık | açık merkezler |",
            "|---:|---|---:|---:|---:|---|",
        ]
    )
    for point in sweep.points:
        opened = ", ".join(point.open_centers) if point.open_centers else "—"
        lines.append(
            f"| {_num(point.epsilon)} | {point.status} | {_num(point.z1)} | {_num(point.z2)} | {_num(point.gap)} | {opened} |"
        )
    lines.append("")
    return "\n".join(lines)


def _num(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.6g}"


if __name__ == "__main__":
    main()
