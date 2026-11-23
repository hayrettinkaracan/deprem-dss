"""Sekmedeki operasyonel ekip→enkaz atamasının taşınmış hali.

h=0 enkazlar çağıran tarafta elenir. Her ekip en fazla bir enkaz alır.
Etkin kapasite eski prototipteki q / (1+β) kuralıdır. Raporun β'si yol gecikmesidir.
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp

def capacity_factor(beta: float) -> float:
    """Eski sekme: etkin kapasite = nominal / (1+β). Raporun gecikme β'si değildir."""

    return 1.0 / (1.0 + float(beta))



@dataclass(frozen=True)
class Assignment:
    ekip_id: object
    enkaz_id: object
    etkin_kapasite: float


@dataclass
class LegacyResult:
    status: str
    objective: float | None
    assignments: list[Assignment]
    unmet: dict[object, float]


def solve_team_to_site(teams: list[dict], sites: list[dict], beta: float) -> LegacyResult:
    factor = capacity_factor(beta)
    problem = pulp.LpProblem("Ekip_Atama", pulp.LpMinimize)
    pairs = [(team["id"], site["id"]) for team in teams for site in sites]
    x = pulp.LpVariable.dicts("atama", pairs, cat="Binary")
    unmet = pulp.LpVariable.dicts("unmet", [site["id"] for site in sites], lowBound=0)

    problem += pulp.lpSum(unmet[site["id"]] for site in sites)
    for site in sites:
        assigned = pulp.lpSum(
            x[(team["id"], site["id"])] * float(team["kapasite"]) * factor for team in teams
        )
        problem += unmet[site["id"]] >= float(site["talep"]) - assigned
    for team in teams:
        problem += pulp.lpSum(x[(team["id"], site["id"])] for site in sites) <= 1

    # msg=0, varsayılan CBC ayarları: sekmedeki önceki çağrıyla aynı.
    status_code = problem.solve(pulp.PULP_CBC_CMD(msg=0))
    status = pulp.LpStatus.get(status_code, str(status_code))

    assignments: list[Assignment] = []
    if status == "Optimal":
        for team in teams:
            for site in sites:
                value = pulp.value(x[(team["id"], site["id"])]) or 0.0
                if value > 0.5:
                    assignments.append(
                        Assignment(
                            ekip_id=team["id"],
                            enkaz_id=site["id"],
                            etkin_kapasite=float(team["kapasite"]) * factor,
                        )
                    )

    unmet_values = {}
    for site in sites:
        value = pulp.value(unmet[site["id"]])
        unmet_values[site["id"]] = float(value) if value is not None else 0.0
    objective = pulp.value(problem.objective)
    return LegacyResult(
        status=status,
        objective=None if objective is None else float(objective),
        assignments=assignments,
        unmet=unmet_values,
    )
