FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOTFLOW_TRADING_MODE=paper \
    HOTFLOW_ACCEPT_LIVE=0

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY scripts ./scripts

RUN pip install --no-cache-dir .

CMD ["hotflow", "--help"]
