"""Self-upgrade for the bundled scriptpilot binary.

Mirrors the clipad upgrade flow: fetch latest GitHub release, verify the
sha256 the API reports for the asset, atomically rename the new binary into
place over the old one with rollback on failure.
"""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from pathlib import Path
from typing import IO

import httpx

REPO_OWNER = "krzysztofciepka"
REPO_NAME = "script-pilot"
ASSET_NAME = "scriptpilot"
USER_AGENT_PREFIX = "scriptpilot-upgrader/"
GITHUB_API_BASE = "https://api.github.com"


class UpgradeError(Exception):
    """Raised when an upgrade step fails. The message is user-facing."""


def fetch_latest_release(api_base_url: str, version: str) -> dict:
    url = f"{api_base_url}/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    try:
        r = httpx.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT_PREFIX + version,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        raise UpgradeError(f"failed to fetch latest release: {e}") from e

    if r.status_code != 200:
        body = r.text
        snippet = body[:200] + "..." if len(body) > 200 else body
        raise UpgradeError(
            f"failed to fetch latest release: {r.status_code}: {snippet}"
        )

    try:
        return r.json()
    except ValueError as e:
        raise UpgradeError(f"failed to parse release metadata: {e}") from e


def pick_asset(release: dict, asset_name: str = ASSET_NAME) -> dict:
    for a in release.get("assets", []) or []:
        if a.get("name") == asset_name:
            return a
    tag = release.get("tag_name", "?")
    raise UpgradeError(f"no asset matching {asset_name} in release {tag}")


def download_asset(
    url: str, dst_path: Path, expected_digest: str, version: str
) -> None:
    """Stream `url` to `dst_path`, verifying sha256 against `expected_digest`.

    `expected_digest` is GitHub's "sha256:<hex>" string from the release JSON.
    On any failure (HTTP, IO, checksum) the partial file is removed.
    """
    hasher = hashlib.sha256()
    try:
        with httpx.stream(
            "GET",
            url,
            headers={"User-Agent": USER_AGENT_PREFIX + version},
            timeout=30.0,
            follow_redirects=True,
        ) as r:
            if r.status_code != 200:
                raise UpgradeError(f"failed to download {url}: {r.status_code}")
            fd = os.open(
                str(dst_path),
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC,
                0o755,
            )
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    hasher.update(chunk)
    except httpx.HTTPError as e:
        _silent_unlink(dst_path)
        raise UpgradeError(f"failed to download {url}: {e}") from e
    except OSError as e:
        _silent_unlink(dst_path)
        raise UpgradeError(f"failed to download {url}: {e}") from e
    except BaseException:
        _silent_unlink(dst_path)
        raise

    got = hasher.hexdigest()
    want = expected_digest[len("sha256:"):] if expected_digest.startswith(
        "sha256:"
    ) else expected_digest
    if got != want:
        _silent_unlink(dst_path)
        raise UpgradeError(f"checksum mismatch: expected {want}, got {got}")


def _silent_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


_rename_impl = os.rename


def install_binary(src_path: Path, target_path: Path) -> None:
    """Atomically replace `target_path` with `src_path`, rolling back on failure."""
    backup = Path(str(target_path) + ".old")
    try:
        _rename_impl(str(target_path), str(backup))
    except OSError as e:
        raise UpgradeError(f"cannot move existing binary aside: {e}") from e

    try:
        _rename_impl(str(src_path), str(target_path))
    except OSError as e:
        try:
            _rename_impl(str(backup), str(target_path))
        except OSError:
            raise UpgradeError(
                f"failed to install new binary: {e}; "
                f"original saved at {backup} — restore manually"
            ) from e
        raise UpgradeError(f"failed to install new binary: {e}") from e

    _silent_unlink(backup)


def human_size(n: int) -> str:
    KB = 1 << 10
    MB = 1 << 20
    if n >= MB:
        return f"{n / MB:.1f} MB"
    if n >= KB:
        return f"{n / KB:.1f} KB"
    return f"{n} B"


def _is_supported_platform() -> bool:
    machine = platform.machine().lower()
    return sys.platform == "linux" and machine in ("x86_64", "amd64")


def run_upgrade(
    out: IO[str], current_version: str, api_base_url: str, exe_path: str
) -> int:
    """Run the upgrade flow. Returns 0 on success or no-op, 1 on error."""
    if not _is_supported_platform():
        out.write(
            f"self-upgrade is not supported on {sys.platform}/{platform.machine()}"
            " — please reinstall manually\n"
        )
        return 1

    try:
        target = Path(exe_path).resolve(strict=False)
    except OSError:
        target = Path(exe_path)
    target_dir = target.parent

    try:
        rel = fetch_latest_release(api_base_url, current_version)
    except UpgradeError as e:
        out.write(f"error: {e}\n")
        return 1

    tag = rel.get("tag_name", "")
    if current_version != "dev" and tag == current_version:
        out.write(f"scriptpilot is up to date ({current_version}).\n")
        return 0

    try:
        asset = pick_asset(rel, ASSET_NAME)
    except UpgradeError as e:
        out.write(f"error: {e}\n")
        return 1

    size = int(asset.get("size", 0) or 0)
    out.write(f"Current version: {current_version}\n")
    out.write(f"Latest version:  {tag}\n")
    out.write(f"Downloading {asset['name']} ({human_size(size)})...\n")
    out.flush()

    tmp_path = target_dir / f".scriptpilot-upgrade-{os.getpid()}"
    try:
        download_asset(
            asset["browser_download_url"],
            tmp_path,
            asset.get("digest", "") or "",
            current_version,
        )
    except UpgradeError as e:
        msg = str(e).lower()
        if "permission" in msg:
            out.write(
                f"cannot write to {target_dir}: {e} — re-run with sudo or "
                "move scriptpilot to a user-owned path\n"
            )
            return 1
        out.write(f"error: {e}\n")
        return 1

    out.write("Verifying checksum... ok\n")
    out.write(f"Installing to {target}... ")
    out.flush()

    try:
        install_binary(tmp_path, target)
    except UpgradeError as e:
        out.write("failed\n")
        _silent_unlink(tmp_path)
        out.write(f"error: {e}\n")
        return 1

    out.write("ok\n")
    out.write(
        f"Upgraded {current_version} → {tag}. "
        "Restart scriptpilot to use the new version.\n"
    )
    return 0
