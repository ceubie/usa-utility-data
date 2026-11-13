FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY app ./app
COPY registry ./registry
COPY graph ./graph
COPY contracts ./contracts
RUN uv sync --frozen --no-dev
RUN /opt/venv/bin/python -c "import duckdb; duckdb.connect().execute('INSTALL spatial')"

ENV PATH="/opt/venv/bin:${PATH}"
CMD ["python", "-m", "app.backend.main"]
