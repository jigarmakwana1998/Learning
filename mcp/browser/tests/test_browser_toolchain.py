"""The browser server's pinned Node toolchain and its setup scripts."""

import json
import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_browser_toolchain_is_exactly_pinned_in_manifest_and_lockfile():
    manifest = json.loads((PACKAGE_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((PACKAGE_ROOT / "package-lock.json").read_text(encoding="utf-8"))

    expected = {"agent-browser": "0.27.3"}
    assert manifest["private"] is True
    assert manifest["engines"]["node"] == ">=24.0.0"
    assert manifest["dependencies"] == expected
    assert lock["packages"][""]["name"] == manifest["name"]
    assert lock["packages"][""]["engines"] == manifest["engines"]
    assert lock["packages"][""]["dependencies"] == expected
    browser_package = lock["packages"]["node_modules/agent-browser"]
    assert browser_package["version"] == "0.27.3"
    # The pinned browser CLI requires Node 24.  Keep the container in sync with
    # the lockfile instead of relying on npm's engine warning at build time.
    assert browser_package["engines"]["node"].startswith(">=24")


def test_mcp_sdk_stays_on_fastmcp_1x():
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "mcp>=1.28.1,<2" in pyproject["project"]["dependencies"]


def test_bootstrap_scripts_install_locked_packages_browser_and_run_doctor():
    scripts = [
        PACKAGE_ROOT / "scripts" / "setup-browser-tools.ps1",
        PACKAGE_ROOT / "scripts" / "setup-browser-tools.sh",
    ]

    for script in scripts:
        assert script.is_file(), f"missing bootstrap script: {script.name}"
        body = script.read_text(encoding="utf-8").casefold()
        assert "npm ci" in body
        assert "agent-browser install" in body
        assert "agent-browser doctor" in body
        assert "npm install -g" not in body
