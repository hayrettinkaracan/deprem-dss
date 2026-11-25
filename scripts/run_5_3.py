"""5.3 Z1 ve Pareto koşusu. Uzun CBC işi bu makinede değil, yerelde çalışır.

    python -m scripts.run_5_3 --mode z1 --time-limit 900 --threads 4 --out docs/sonuclar_5_3.md
    python -m scripts.run_5_3 --mode pareto --time-limit 120 --threads 4 --out docs/sonuclar_5_3.md
    python -m scripts.run_5_3 --mode rehearsal --time-limit 60 --threads 4 --out docs/prova_5_3.md

Süre sınırı her CBC çağrısı içindir. z1 tek çağrıdır. pareto yedi çağrıdır
(Z1, iki Z2 ucu, beş ε). rehearsal her olay için bir çağrıdır (altı olay).
36 periyotluk z1, 4 çekirdekte çoğunlukla birkaç dakika ile 15 dakika arasındadır;
900 s yerel bütçe olarak yeter. pareto için 120 s ile üst sınır kabaca 15 dakikadır.
rehearsal tam ufukta olay başı 60 s ile kabaca 6 dakikadır. Kısa kontrol:
--mode rehearsal --max-events 1 --periods 2 --time-limit 15
"""

from __future__ import annotations

import argparse
from pathlib import Path

from data.rehearsal import LABEL, generate_rehearsal, instance_with_event
from data.section_5_3 import HYK_KARARI, section_5_3
from model.operational import OperationalState, TeamState, solve_operational
from model.pareto import ParetoSweep, pareto_sweep
from model.planning import solve_planning
from model.staff import GROUP_A, GROUPS, Resource, group_load, planning_staff


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "5.3 planlama ve prova koşusu. --time-limit her CBC çağrısı içindir. "
            "z1 tek çağrı, 36 periyotta 4 çekirdekte birkaç dakika ile 15 dakika; 900 s yerel bütçedir. "
            "pareto 7 çağrıdır (Z1, iki Z2 ucu, beş ε); 120 s ile üst sınır kabaca 15 dakikadır. "
            "rehearsal 6 olaydır, olay başı bir çağrı; tam ufukta 60 s ile kabaca 6 dakika. "
            "Kısa prova: --max-events 1 --periods 2 --time-limit 15."
        )
    )
    parser.add_argument("--mode", choices=("z1", "pareto", "rehearsal"), required=True)
    parser.add_argument(
        "--time-limit",
        type=int,
        default=900,
        help="Her CBC çağrısının saniye sınırı. z1: 1 çağrı. pareto: 7 çağrı. rehearsal: olay başına 1 çağrı.",
    )
    parser.add_argument("--threads", type=int, default=0, help="0 ise bütün çekirdekler")
    parser.add_argument("--periods", type=int, default=36, help="Son periyot. Prova kısa kontrolde 2 yeter.")
    parser.add_argument("--points", type=int, default=5)
    parser.add_argument("--max-events", type=int, default=6, help="Prova olayı sayısı. Kısa kontrolde 1.")
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
    elif args.mode == "pareto":
        sweep = pareto_sweep(
            instance,
            periods=args.periods,
            time_limit=args.time_limit,
            threads=threads,
            points=args.points,
            vartheta=HYK_KARARI.vartheta,
        )
        text = _pareto_markdown(sweep, args.time_limit, threads or "tümü")
    else:
        text = _rehearsal(instance, args.time_limit, threads, args.periods, args.max_events)
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


def _rehearsal(instance, time_limit: int, threads, last_period: int, max_events: int) -> str:
    events = generate_rehearsal(instance)[:max_events]
    lines = [
        "# 5.3 saat provası",
        "",
        f"Kayıtlar {LABEL}. Tohum 20261125. Her olay bir sonraki periyodun başında girer.",
        "Saat başına bir enkaz ve bir gönüllü. Adet raporda yoktur.",
        "",
        "| Saat | Giriş periyodu | θ | Enkaz | κ | γ | m^A | E | τ J1 | τ J2 | Gönüllü | p | Merkez |",
        "|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---|---:|---|",
    ]
    for event in events:
        lines.append(
            f"| {event.hour} | {event.entry_period} | {event.theta:g} | {event.site_id} | {event.damage} | {event.gamma} | {event.m_A:g} | {event.E} | {event.tau_center['J1']:g} | {event.tau_center['J2']:g} | {event.volunteer_id} | {event.volunteer_p:.4f} | {event.volunteer_center} |"
        )
    lines.extend(["", "## Kısa çözüm", ""])
    built = instance
    for event in events:
        built = instance_with_event(built, event)
        solution = _solve_event(built, event, time_limit, threads, last_period)
        opened = ", ".join(name for name, flag in solution.G.items() if flag) or "—"
        lines.append(
            f"- Saat {event.hour} → periyot {event.entry_period}: durum {solution.status}, Z1 {_num(solution.z1)}, açık {opened}."
        )
    lines.append("")
    return "\n".join(lines)


def _solve_event(instance, event, time_limit, threads, last_period: int):
    t0 = event.entry_period
    horizon = max(last_period, t0)
    theta = instance.L * (t0 - 1)
    homes = ("J1", "J2")
    teams = []
    for index, resource in enumerate(planning_staff(instance).resources):
        center = homes[index % 2]
        teams.append(TeamState(resource, f"c_{center}_t{t0}_l1", theta, True))
    volunteer = Resource(event.volunteer_id, GROUP_A, event.volunteer_p, k=None)
    teams.append(TeamState(volunteer, f"c_{event.volunteer_center}_t{t0}_l1", theta, True))
    remaining = {}
    for scenario in instance.scenarios:
        for site in instance.sites:
            for group in GROUPS:
                remaining[(group, site.i, scenario.s)] = group_load(site, group)
    state = OperationalState(t0, theta, set(homes), teams, remaining)
    return solve_operational(
        instance,
        horizon,
        state,
        time_limit=time_limit,
        threads=1 if threads is None else threads,
        delta=0.001,
        vartheta=HYK_KARARI.vartheta,
    )


def _num(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.6g}"


if __name__ == "__main__":
    main()
