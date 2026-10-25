FROM node:24-bookworm-slim@sha256:cd84903a12dbd26b46f1f3b8144a2568c41c5d37ddd0c7a80a34c7a19786b35f AS browser-tools

WORKDIR /tools

COPY mcp/browser/package.json mcp/browser/package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app \
    PATH=/opt/venv/bin:/opt/learning-tools/node_modules/.bin:$PATH \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
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
        fonts-freefont-ttf=20120503-10 \
        fonts-noto-cjk=1:20220127+repack1-1 \
        fonts-noto-color-emoji=2.042-0+deb12u1 \
        libasound2=1.2.8-1+b1 \
        libatk-bridge2.0-0=2.46.0-5 \
        libatk1.0-0=2.46.0-5 \
        libatspi2.0-0=2.46.0-5 \
        libcairo-gobject2=1.16.0-7 \
        libcairo2=1.16.0-7 \
        libcups2=2.4.2-3+deb12u9 \
        libdbus-1-3=1.14.10-1~deb12u1 \
        libdrm2=2.4.114-1+b1 \
        libfontconfig1=2.14.1-4 \
        libfreetype6=2.12.1+dfsg-5+deb12u4 \
        libgbm1=22.3.6-1+deb12u2 \
        libgdk-pixbuf-2.0-0=2.42.10+dfsg-1+deb12u4 \
        libgtk-3-0=3.24.38-2~deb12u3 \
        libnspr4=2:4.35-1 \
        libnss3=2:3.87.1-1+deb12u4 \
        libpango-1.0-0=1.50.12+ds-1 \
        libpangocairo-1.0-0=1.50.12+ds-1 \
        libx11-6=2:1.8.4-2+deb12u2 \
        libx11-xcb1=2:1.8.4-2+deb12u2 \
        libxcb-shm0=1.15-1 \
        libxcb1=1.15-1 \
        libxcomposite1=1:0.4.5-1 \
        libxcursor1=1:1.2.1-1 \
        libxdamage1=1:1.1.6-1 \
        libxext6=2:1.3.4-1+b1 \
        libxfixes3=1:6.0.0-2 \
        libxi6=2:1.8-1+b1 \
        libxkbcommon0=1.5.0-1 \
        libxrandr2=2:1.5.2-2+b1 \
        libxrender1=1:0.9.10-1.1 \
        libxshmfence1=1.3-1 \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && mkdir -p /opt/agent-browser-cache \
    && HOME=/home/app agent-browser install \
    # compose mounts a tmpfs over ~/.agent-browser, so keep Chrome outside it.
    && mv /home/app/.agent-browser/browsers /opt/agent-browser-cache/browsers \
    && ln -s /opt/agent-browser-cache/browsers/chrome-*/chrome /opt/agent-browser-cache/chrome \
    && chown -R app:app /home/app /opt/learning-tools /opt/agent-browser-cache \
    && rm -rf /var/lib/apt/lists/*

# uv workspace: the API plus the database, browser-MCP and course-MCP packages, from the lock.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
COPY database ./database
COPY mcp/browser/pyproject.toml ./mcp/browser/
COPY mcp/browser/browser_mcp ./mcp/browser/browser_mcp
COPY mcp/course/pyproject.toml ./mcp/course/
COPY mcp/course/course_mcp ./mcp/course/course_mcp
RUN pip install --no-cache-dir uv==0.11.7 \
    && uv sync --frozen --no-dev --no-editable --package learning-coach-api \
    && chown -R app:app /app

USER app

# Validate the CLI and the configured Chrome as the same unprivileged user that
# serves API requests. `doctor` ignores AGENT_BROWSER_EXECUTABLE_PATH, so check
# the binary directly. No model request is made.
RUN agent-browser --version && "$AGENT_BROWSER_EXECUTABLE_PATH" --version

EXPOSE 8000

CMD ["sh", "-c", "cd /app/database && alembic upgrade head && cd /app/backend && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
