"""Shared initial-draft policy. Validation does not create or execute a workout."""

from datetime import timedelta


def validate_draft(plan, profile, today):
    profile.validate_calendar(today)
    if len(plan.workouts) > 28 or plan.athlete:
        raise ValueError("Initial draft must be bounded and contain no athlete metadata")
    if len(plan.plan_name) > 200 or len(plan.goal) > 1500 or len(plan.notes) > 20:
        raise ValueError("Draft text exceeds its limits")
    if any(len(note) > 2000 for note in plan.notes):
        raise ValueError("Draft note too long")
    days = {day.weekday: day.minutes for day in profile.availability}
    totals = {}
    training = []
    gym = []
    for workout in plan.workouts:
        if not today < workout.date <= today + timedelta(days=14) or workout.quality:
            raise ValueError("Initial draft requires future, easy sessions within fourteen days")
        if workout.sport == "rest":
            if workout.estimated_duration_min is not None:
                raise ValueError("Rest has no training duration")
            continue
        if (workout.sport == "running" and profile.primary_sport == "cycling") or (
            workout.sport == "cycling" and profile.primary_sport == "running"
        ):
            raise ValueError("Sport outside athlete preference")
        training.append(workout)
        if workout.sport == "manual":
            if not profile.gym_sessions_week:
                raise ValueError("No gym requested")
            gym.append(workout.date)
        elif not 1 <= len(workout.steps) <= 6:
            raise ValueError("Initial aerobic sessions require one to six simple steps")
        if any(
            step.type not in {"warmup", "run", "cooldown"} or step.distance_m or step.target
            for step in workout.steps
        ):
            raise ValueError("Initial draft requires simple time-based sessions without targets")
        actual = sum(step.seconds or 0 for step in workout.steps) / 60
        if not workout.estimated_duration_min:
            raise ValueError("Training duration required")
        if workout.steps and abs(actual - workout.estimated_duration_min) > 1 / 60:
            raise ValueError("Displayed duration must match the session's steps")
        minutes = workout.estimated_duration_min
        totals[workout.date] = totals.get(workout.date, 0) + minutes
        if totals[workout.date] > days.get(workout.date.weekday(), 0):
            raise ValueError("Combined sessions exceed availability")
    if not training:
        raise ValueError("Ask for clarification rather than returning a rest-only plan")
    if any(sum(day <= other < day + timedelta(days=7) for other in gym) > profile.gym_sessions_week for day in gym):
        raise ValueError("Gym frequency exceeds the requested rolling week")
