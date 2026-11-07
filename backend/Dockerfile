FROM python:3.12-slim
# Diagram renderers for the "source must compile" quality check (plan 2.18):
# Graphviz (dot) and PlantUML. Mermaid (mmdc) needs Node + Chromium; add it if
# the team uses Mermaid diagrams.
RUN apt-get update \
 && apt-get install -y --no-install-recommends graphviz plantuml \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
