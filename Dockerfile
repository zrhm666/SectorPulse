FROM node:22-alpine AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
COPY config ./config
COPY --from=web-build /web/dist ./web/dist
RUN pip install --no-cache-dir '.[postgres]'

EXPOSE 8010
CMD ["uvicorn", "sector_pulse.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010"]
