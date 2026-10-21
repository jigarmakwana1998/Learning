"""Static contracts for the reproducible browser-research runtime.

These tests deliberately avoid starting Chromium or making network requests.  They
protect the pieces that must be present before the opt-in live smoke test can run.
"""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\s*\n|^networks:|\Z)",
        compose,
    )
    assert match is not None, f"compose service {service!r} is missing"
    return match.group("body")


def test_api_image_contains_pinned_node_toolchain_and_chrome_installation():
    dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"(?mi)^FROM node:24(?:[.-][^\s]+)?\s+AS\s+\S+", dockerfile)
    assert re.search(r"(?mi)^FROM python:3\.12-slim-bookworm", dockerfile)
    assert "npm ci" in dockerfile
    assert "agent-browser install --with-deps" in dockerfile
    assert re.search(r"agent-browser\s+(?:--version|doctor)", dockerfile)
    assert "gemini" not in dockerfile.casefold()
    assert re.search(r"(?mi)^USER app\s*$", dockerfile)


def test_compose_gives_only_api_public_egress_and_ephemeral_browser_state():
    compose = (PROJECT_ROOT / "compose.yml").read_text(encoding="utf-8")
    api = _service_block(compose, "api")

    assert "read_only: true" in api
    assert "networks: [edge, internal]" in api
    for path in (
        "/tmp",
        "/dev/shm",
        "/home/app/.cache",
        "/home/app/.agent-browser",
    ):
        assert path in api
    assert "pids_limit: 512" in api
    assert "mem_limit: 2g" in api
    assert 'cpus: "2.0"' in api
    assert "command -v agent-browser" in api

    # Public browsing is isolated to the API.  Data stores stay on Docker's
    # internal-only network and are never attached to the public-egress network.
    for service in ("postgres",):
        block = _service_block(compose, service)
        assert "networks: [internal]" in block
        assert "edge" not in block

    searxng = _service_block(compose, "searxng")
    assert "read_only: true" in searxng and "cap_drop: [ALL]" in searxng
    assert "@sha256:" in searxng
    assert "SEARXNG_URL: http://searxng:8080" in api

    networks = compose.split("\nnetworks:\n", maxsplit=1)[1]
    assert re.search(r"(?m)^  internal:\s*\n    internal: true$", networks)


def test_litellm_mcp_client_imports_with_pinned_mcp():
    # litellm>=1.103 imports mcp 2 types here and broke /learning-runs at runtime.
    import importlib

    importlib.import_module("litellm.experimental_mcp_client")
