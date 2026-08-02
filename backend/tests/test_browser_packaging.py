"""Static contracts for the reproducible browser-research runtime.

These tests deliberately avoid starting Chromium or making network requests.  They
protect the pieces that must be present before the opt-in live smoke test can run.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\s*\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\s*\n|^networks:|\Z)",
        compose,
    )
    assert match is not None, f"compose service {service!r} is missing"
    return match.group("body")


def test_browser_toolchain_is_exactly_pinned_in_manifest_and_lockfile():
    manifest = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text(encoding="utf-8"))

    expected = {
        "@google/gemini-cli": "0.51.0",
        "agent-browser": "0.27.3",
    }
    assert manifest["private"] is True
    assert manifest["engines"]["node"] == ">=24.0.0"
    assert manifest["dependencies"] == expected
    assert lock["packages"][""]["name"] == manifest["name"]
    assert lock["packages"][""]["engines"] == manifest["engines"]
    assert lock["packages"][""]["dependencies"] == expected
    assert lock["packages"]["node_modules/@google/gemini-cli"]["version"] == "0.51.0"
    browser_package = lock["packages"]["node_modules/agent-browser"]
    assert browser_package["version"] == "0.27.3"
    # The pinned browser CLI requires Node 24.  Keep the container in sync with
    # the lockfile instead of relying on npm's engine warning at build time.
    assert browser_package["engines"]["node"].startswith(">=24")


def test_mcp_dependency_is_declared_consistently_for_both_install_paths():
    pyproject = tomllib.loads((PROJECT_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    project_dependencies = set(pyproject["project"]["dependencies"])
    requirements = {
        line.strip()
        for line in (PROJECT_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "mcp>=1.28.1,<2" in project_dependencies
    assert "mcp>=1.28.1,<2" in requirements


def test_bootstrap_scripts_install_locked_packages_browser_and_run_doctor():
    scripts = [
        PROJECT_ROOT / "scripts" / "setup-browser-tools.ps1",
        PROJECT_ROOT / "scripts" / "setup-browser-tools.sh",
    ]

    for script in scripts:
        assert script.is_file(), f"missing bootstrap script: {script.name}"
        body = script.read_text(encoding="utf-8").casefold()
        assert "npm ci" in body
        assert "agent-browser install" in body
        assert "agent-browser doctor" in body
        assert "npm install -g" not in body


def test_api_image_contains_pinned_node_toolchain_and_chrome_installation():
    dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"(?mi)^FROM node:24(?:[.-][^\s]+)?\s+AS\s+\S+", dockerfile)
    assert re.search(r"(?mi)^FROM python:3\.12-slim-bookworm", dockerfile)
    assert "npm ci" in dockerfile
    assert "agent-browser install --with-deps" in dockerfile
    assert re.search(r"agent-browser\s+(?:--version|doctor)", dockerfile)
    assert re.search(r"gemini\s+--version", dockerfile)
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
        "/home/app/.gemini",
        "/home/app/.agent-browser",
    ):
        assert path in api
    assert "pids_limit: 512" in api
    assert "mem_limit: 2g" in api
    assert 'cpus: "2.0"' in api
    assert "command -v gemini" in api
    assert "command -v agent-browser" in api

    # Public browsing is isolated to the API.  Data stores stay on Docker's
    # internal-only network and are never attached to the public-egress network.
    for service in ("postgres", "neo4j", "qdrant", "minio"):
        block = _service_block(compose, service)
        assert "networks: [internal]" in block
        assert "edge" not in block

    networks = compose.split("\nnetworks:\n", maxsplit=1)[1]
    assert re.search(r"(?m)^  internal:\s*\n    internal: true$", networks)
