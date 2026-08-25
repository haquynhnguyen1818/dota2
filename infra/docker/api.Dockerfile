FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

# The weekly refresh job (app.jobs.refresh_weekly) runs in this image and its
# loaders read these by path. Listed individually rather than copying data/ and
# docs/ wholesale, which would drag the UI mockups and OpenDota's schema dump
# into a runtime image.
COPY data/hero_role.csv data/hero_tags.csv data/
COPY docs/players_id.txt docs/

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
