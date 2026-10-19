# --- build the web UI ---
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- API + engine ---
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TRADEBOT_STATIC=/app/web/dist TRADEBOT_DB=/app/data/tradebot.db \
    TRADEBOT_CONFIG=/app/config/config.yaml
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .
COPY config/ config/
RUN [ -f config/config.yaml ] || cp config/config.example.yaml config/config.yaml
COPY --from=web /web/dist web/dist
VOLUME /app/data
EXPOSE 8000
CMD ["uvicorn", "tradebot.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
