import argparse
import json
import sys

from pydantic import ValidationError

from app.config import Settings
from app.garmin.client import CoachError
from app.services.coach import Coach


def display(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def serve():
    import uvicorn

    settings = Settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, workers=1)


def print_preview(preview):
    print(f"\nPreview {preview['start']} → {preview['end']}: {preview['remove_count']} rimozioni")
    print("DATA       | WORKOUT                       | SCHEDULED ID | AZIONE")
    for row in preview["rows"]:
        print(
            f"{row['date']} | {row['name'][:29]:29} | {row['scheduled_id']:12} | {row['action']} · {row['reason']}"
        )


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Garmin Adaptive Coach")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "login",
        "activities",
        "review",
        "serve",
        "validate-plan",
        "performances",
        "climbs",
    ):
        sub.add_parser(name)
    test = sub.add_parser(
        "test-workout", help="Upload/riuso e verifica un singolo template; non schedula"
    )
    test.add_argument("--id")
    cleanup = sub.add_parser("cleanup")
    group = cleanup.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview", action="store_true")
    group.add_argument("--apply", action="store_true")
    sub.add_parser("sync")
    catalog = sub.add_parser(
        "import-climbs", help="Importa il catalogo dalla mappa pubblica Climbfinder"
    )
    catalog.add_argument("--bbox", action="append", metavar="OVEST,SUD,EST,NORD")
    catalog.add_argument("--zoom", type=int, default=10)
    catalog.add_argument(
        "--refresh", action="store_true", help="Aggiorna anche i tile già in cache"
    )
    args = parser.parse_args()
    if args.command == "serve":
        serve()
        return
    if args.command == "import-climbs":
        from app.services.climb_import import import_catalog

        try:
            bounds = (
                [tuple(float(v) for v in bbox.split(",")) for bbox in args.bbox]
                if args.bbox
                else None
            )
            display(import_catalog(Settings().data_dir, bounds, args.zoom, args.refresh))
        except (CoachError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        return
    coach = Coach(Settings())
    try:
        if args.command == "login":
            coach.client.login(interactive=True)
            print("Login Garmin riuscito; sessione persistente salvata fuori dal progetto.")
        elif args.command == "validate-plan":
            plan = coach.plan()
            print(
                f"Piano valido: {plan.plan_name}, {len(plan.workouts)} sessioni ({plan.start} → {plan.end})"
            )
        elif args.command == "activities":
            coach.refresh()
            display(coach.db.activities()[:20])
        elif args.command == "review":
            display(coach.review())
        elif args.command == "performances":
            display(coach.refresh_performances())
        elif args.command == "climbs":
            display(coach.refresh_climbs())
        elif args.command == "test-workout":
            proof = coach.test_workout(args.id)
            display(proof)
            print("Template verificato; nessuna nuova schedulazione eseguita.")
        elif args.command == "cleanup":
            preview = coach.preview_calendar_cleanup()
            print_preview(preview)
            if args.apply:
                if (
                    not sys.stdin.isatty()
                    or input("Rimuovere SOLO queste schedulazioni? Scrivi CONFERMO: ").strip()
                    != "CONFERMO"
                ):
                    raise CoachError("Pulizia annullata: conferma esplicita mancante")
                display(coach.apply_calendar_cleanup(preview["preview_id"], True))
        elif args.command == "sync":
            proof = coach.db.get("test_proof")
            if not proof or not proof.get("valid"):
                raise CoachError("Esegui prima python -m app.cli test-workout")
            print(f"Test verificato: {proof['plan_workout_id']} · Garmin ID {proof['workout_id']}")
            if (
                not sys.stdin.isatty()
                or input("Confermi il test e la sync del piano futuro? Scrivi CONFERMO: ").strip()
                != "CONFERMO"
            ):
                raise CoachError("Sync annullata: conferma mancante")
            display(coach.sync_plan(True))
    except (CoachError, ValidationError) as exc:
        print(
            str(exc)
            if isinstance(exc, CoachError)
            else "Piano JSON non valido: controlla durate, target, sport e ID",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
