FROM node:24-bookworm-slim@sha256:cd84903a12dbd26b46f1f3b8144a2568c41c5d37ddd0c7a80a34c7a19786b35f AS browser-tools

WORKDIR /tools

COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app \
    PATH=/opt/learning-tools/node_modules/.bin:$PATH \
    PUPPETEER_CACHE_DIR=/opt/agent-browser-cache \
    AGENT_BROWSER_CONTENT_BOUNDARIES=1 \
    AGENT_BROWSER_MAX_OUTPUT=6000

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

# Keep the Node tools project-local and reproducible. agent-browser 0.27.3
# requires Node 24, so the official runtime is copied into the Python image.
COPY --from=browser-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=browser-tools /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=browser-tools /tools/node_modules /opt/learning-tools/node_modules

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && mkdir -p /opt/agent-browser-cache \
    && HOME=/home/app agent-browser install --with-deps \
    && chown -R app:app /home/app /opt/learning-tools /opt/agent-browser-cache \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

RUN chown -R app:app /app

USER app

# Validate executable discovery and the durable Chrome cache as the same
# unprivileged user that serves API requests. No model request is made.
RUN agent-browser doctor --offline --quick \
    && gemini --version

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
