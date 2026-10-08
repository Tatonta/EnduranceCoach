"""Create a synthetic example plan. Never overwrite an existing athlete plan."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(kind, minutes=None, seconds=None, distance=None, target=None):
    item = {"type": kind}
    if minutes is not None:
        item["duration_min"] = minutes
    if seconds is not None:
        item["duration_s"] = seconds
    if distance is not None:
        item["distance_m"] = distance
    if target:
        item["target"] = target
    return item


def pace(fast, slow):
    return {"type": "pace", "slow": slow, "fast": fast}


def repeat(n, steps):
    return {"type": "repeat", "iterations": n, "steps": steps}


def workout(day, name, sport, description, steps=None, minutes=None, quality=False):
    result = {
        "id": f"oct-{day:02}",
        "date": f"2026-10-{day:02}",
        "name": name,
        "sport": sport,
        "description": description,
        "quality": quality,
    }
    if steps:
        result["steps"] = steps
        result["estimated_duration_min"] = minutes
    return result


def easy(day, name, minutes, description):
    return workout(
        day,
        name,
        "running",
        description,
        [step("warmup", 10), step("run", minutes - 15), step("cooldown", 5)],
        minutes,
    )


def strides(day):
    return workout(
        day,
        "Easy 50 + 6 Strides",
        "running",
        "50 min facili totali + 6x20s allunghi rilassati, rec 60s. Nessun target GPS rigido.",
        [
            step("warmup", 10),
            step("run", 35),
            repeat(6, [step("interval", seconds=20), step("recovery", seconds=60)]),
            step("cooldown", 5),
        ],
        58,
    )


def quality(day, name, n, fast, slow, minutes=None, distance=None, recovery=120):
    interval = step("interval", minutes=minutes, distance=distance, target=pace(fast, slow))
    duration = 25 + n * (
        (
            minutes
            if minutes is not None
            else distance
            / 1000
            * sum(int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in (fast, slow))
            / 120
        )
        + recovery / 60
    )
    return workout(
        day,
        name,
        "running",
        "15' warmup, blocchi al ritmo indicato, recuperi facili, 10' cooldown. Solo se recuperato; interrompere la qualità se la tolleranza al carico peggiora.",
        [
            step("warmup", 15),
            repeat(n, [interval, step("recovery", seconds=recovery)]),
            step("cooldown", 10),
        ],
        round(duration, 1),
        True,
    )


def bike(day, minutes=60, recovery=False):
    return workout(
        day,
        "Bike Recovery 60" if recovery else "Bike Z2 60",
        "cycling",
        "Bici facile Z1-Z2; mantenere basso il carico."
        if recovery
        else "60 min Z2 (fino a 75 se recuperato), oppure easy run equivalente. Per schedulare la corsa alternativa modifica sport e steps nel JSON.",
        [
            step("warmup", 10),
            step("run", minutes - 20, target={"type": "hr_zone", "zone": 1 if recovery else 2}),
            step("cooldown", 10),
        ],
        minutes,
    )


def initial_plan():
    workouts = [
        workout(
            4,
            "Recovery / Rest",
            "rest",
            "Riposo nel piano di esempio. Nessuna attività personale è inclusa.",
        ),
        workout(
            5,
            "Rest + Strength moderata",
            "manual",
            "Riposo dalla corsa. Forza moderata, volume controllato e senza cedimento.",
        ),
        quality(6, "Threshold 3x8", 3, "5:10", "5:20", minutes=8),
        strides(7),
        bike(8),
        easy(9, "Recovery Run 40", 40, "Molto facile; se gambe pesanti, riposo."),
        quality(10, "VO2 6x800", 6, "4:50", "5:00", distance=800),
        easy(
            11,
            "Long Easy 80",
            80,
            "80–85' facili, scegliendo inizialmente 80'. Niente finale tirato.",
        ),
        workout(
            12, "Rest + Strength", "manual", "Riposo corsa + forza, senza eccesso di volume gambe."
        ),
        quality(13, "Threshold 3x10", 3, "5:05", "5:15", minutes=10),
        strides(14),
        workout(
            15,
            "Aerobic Steady 60",
            "running",
            "15' easy + 30' @6:00–6:10/km + 15' easy.",
            [
                step("warmup", 15),
                step("interval", 30, target=pace("6:00", "6:10")),
                step("cooldown", 15),
            ],
            60,
            True,
        ),
        bike(16, recovery=True),
        quality(17, "VO2 5x1K", 5, "4:55", "5:05", distance=1000),
        easy(
            18,
            "Long Easy 90",
            90,
            "90–95' facili, scegliendo inizialmente 90'. Ridurre se tolleranza insufficiente.",
        ),
        workout(19, "Rest + Strength", "manual", "Riposo corsa + forza moderata."),
        quality(20, "Threshold 2x15", 2, "5:00", "5:10", minutes=15, recovery=180),
        strides(21),
        bike(22),
        easy(23, "Recovery Run 40", 40, "Facilissimo, nessun target rigido."),
        quality(24, "10K Pace Plus 4x1K", 4, "4:50", "5:00", distance=1000, recovery=150),
        easy(
            25,
            "Long Easy 75",
            75,
            "75–80' facili, scegliendo inizialmente 75'. Lungo ridotto per rivalutare il blocco.",
        ),
    ]
    return {
        "plan_name": "Synthetic example plan · October 2026",
        "goal": "Exercise plan import, structured workouts and review with synthetic data.",
        "athlete": {},
        "notes": [
            "Synthetic software example, not a personal training prescription.",
            "Replace dates, sessions and targets with a suitable plan before watch synchronization.",
        ],
        "workouts": workouts,
    }


if __name__ == "__main__":
    path = ROOT / "data" / "workouts.json"
    if path.exists():
        raise SystemExit("Piano già presente: nessuna sovrascrittura eseguita.")
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(initial_plan(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Creato {path}")
