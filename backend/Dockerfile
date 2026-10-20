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
    AGENT_BROWSER_MAX_OUTPUT=6000 \
    AGENT_BROWSER_EXECUTABLE_PATH=/opt/agent-browser-cache/chrome \
    # Chrome writes its profile under ~/.config; the runtime root is read-only.
    XDG_CONFIG_HOME=/tmp/.config \
    LITELLM_LOCAL_MODEL_COST_MAP=True

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

# Keep the Node tools project-local and reproducible. agent-browser 0.27.3
# requires Node 24, so the official runtime is copied into the Python image.
COPY --from=browser-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=browser-tools /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=browser-tools /tools/node_modules /opt/learning-tools/node_modules

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates=20230311+deb12u1 \
        libstdc++6=12.2.0-14+deb12u1 \
        # Chrome runtime libraries. `agent-browser install --with-deps` needs
        # sudo, which this image lacks, so it silently skipped them.
        # ponytail: unpinned, pin if Debian updates ever break Chrome.
        libxcb-shm0 libx11-xcb1 libx11-6 libxcb1 libxext6 libxrandr2 libxcomposite1 \
        libxcursor1 libxdamage1 libxfixes3 libxi6 libgtk-3-0 libpangocairo-1.0-0 \
        libpango-1.0-0 libatk1.0-0 libcairo-gobject2 libcairo2 libgdk-pixbuf-2.0-0 \
        libxrender1 libasound2 libfreetype6 libfontconfig1 libdbus-1-3 libnss3 libnspr4 \
        libatk-bridge2.0-0 libdrm2 libxkbcommon0 libatspi2.0-0 libcups2 libxshmfence1 \
        libgbm1 fonts-noto-color-emoji fonts-noto-cjk fonts-freefont-ttf \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && mkdir -p /opt/agent-browser-cache \
    && HOME=/home/app agent-browser install \
    # compose mounts a tmpfs over ~/.agent-browser, so keep Chrome outside it.
    && mv /home/app/.agent-browser/browsers /opt/agent-browser-cache/browsers \
    && ln -s /opt/agent-browser-cache/browsers/chrome-*/chrome /opt/agent-browser-cache/chrome \
    && chown -R app:app /home/app /opt/learning-tools /opt/agent-browser-cache \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
RUN chown -R app:app /app

USER app

# Validate the CLI and the configured Chrome as the same unprivileged user that
# serves API requests. `doctor` ignores AGENT_BROWSER_EXECUTABLE_PATH, so check
# the binary directly. No model request is made.
RUN agent-browser --version && "$AGENT_BROWSER_EXECUTABLE_PATH" --version

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
