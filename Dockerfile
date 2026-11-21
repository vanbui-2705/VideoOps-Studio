FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system videoops \
    && useradd --system --gid videoops --create-home videoops

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY core ./core
COPY ui ./ui
COPY migrations ./migrations
COPY assets ./assets
COPY config.py app.py alembic.ini run_*_worker.py run_retention_sweeper.py ./
RUN python -m pip install .

RUN mkdir -p /app/temp /app/outputs \
    && chown -R videoops:videoops /app
USER videoops

EXPOSE 7860
CMD ["python", "app.py"]
