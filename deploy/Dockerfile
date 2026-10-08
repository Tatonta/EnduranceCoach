# syntax=docker/dockerfile:1
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/coach
COPY requirements-platform-runtime.txt ./
RUN python -m pip install --disable-pip-version-check -r requirements-platform-runtime.txt \
    && python -m pip check \
    && groupadd --gid 10001 coach && useradd --uid 10001 --gid coach --no-create-home coach
# Explicit allowlist: never copy the personal app, .env, data, watch sessions,
# browser screenshots, native fixtures or licensed personal climb assets.
COPY app/__init__.py app/errors.py app/models.py app/training_profile.py app/session_feedback.py ./app/
COPY app/platform/*.py ./app/platform/
COPY app/integrations/__init__.py app/integrations/activities.py app/integrations/session_details.py ./app/integrations/
COPY app/services/__init__.py app/services/planner.py app/services/reviewer.py app/services/workout_review.py app/services/session_analysis.py ./app/services/
USER 10001:10001
EXPOSE 8001
CMD ["python", "-m", "app.platform.host"]
