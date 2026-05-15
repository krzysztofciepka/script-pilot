from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import sys
from pathlib import Path

import httpx
import pytest
import respx

from scriptpilot import upgrade
from scriptpilot.upgrade import (
    ASSET_NAME,
    UpgradeError,
    download_asset,
    fetch_latest_release,
    human_size,
    install_binary,
    pick_asset,
    run_upgrade,
)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _is_linux_amd64() -> bool:
    return sys.platform == "linux" and platform.machine().lower() in (
        "x86_64",
        "amd64",
    )


linux_only = pytest.mark.skipif(
    not _is_linux_amd64(), reason="upgrade flow only runs on linux/amd64"
)


class TestPickAsset:
    def test_exact_match(self):
        rel = {
            "tag_name": "v0.0.22",
            "assets": [
                {"name": "scriptpilot", "browser_download_url": "https://example/a"}
            ],
        }
        a = pick_asset(rel)
        assert a["name"] == "scriptpilot"

    def test_picks_matching_from_many(self):
        rel = {
            "tag_name": "v0.0.22",
            "assets": [
                {"name": "other"},
                {"name": "scriptpilot", "browser_download_url": "https://example/want"},
                {"name": "checksums.txt"},
            ],
        }
        assert pick_asset(rel)["browser_download_url"] == "https://example/want"

    def test_no_match_raises(self):
        rel = {"tag_name": "v0.0.22", "assets": [{"name": "other"}]}
        with pytest.raises(UpgradeError) as exc:
            pick_asset(rel)
        assert ASSET_NAME in str(exc.value)
        assert "v0.0.22" in str(exc.value)


class TestFetchLatestRelease:
    @respx.mock
    def test_success(self):
        body = {
            "tag_name": "v0.0.22",
            "assets": [
                {
                    "name": "scriptpilot",
                    "browser_download_url": "https://example/scriptpilot",
                    "size": 16355490,
                    "digest": "sha256:deadbeef",
                }
            ],
        }
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["accept"] = request.headers.get("Accept")
            captured["ua"] = request.headers.get("User-Agent")
            captured["path"] = request.url.path
            return httpx.Response(200, json=body)

        respx.get(
            "https://api.test/repos/krzysztofciepka/script-pilot/releases/latest"
        ).mock(side_effect=handler)

        rel = fetch_latest_release("https://api.test", "v0.0.20")

        assert rel["tag_name"] == "v0.0.22"
        assert rel["assets"][0]["digest"] == "sha256:deadbeef"
        assert captured["accept"] == "application/vnd.github+json"
        assert captured["ua"].startswith("scriptpilot-upgrader/")
        assert captured["path"] == (
            "/repos/krzysztofciepka/script-pilot/releases/latest"
        )

    @respx.mock
    def test_non_200(self):
        respx.get(
            "https://api.test/repos/krzysztofciepka/script-pilot/releases/latest"
        ).mock(return_value=httpx.Response(403, json={"message": "rate limit"}))

        with pytest.raises(UpgradeError) as exc:
            fetch_latest_release("https://api.test", "v0")
        msg = str(exc.value)
        assert "403" in msg
        assert "rate limit" in msg

    @respx.mock
    def test_bad_json(self):
        respx.get(
            "https://api.test/repos/krzysztofciepka/script-pilot/releases/latest"
        ).mock(return_value=httpx.Response(200, text="not json {"))
        with pytest.raises(UpgradeError) as exc:
            fetch_latest_release("https://api.test", "v0")
        assert "parse release metadata" in str(exc.value)


class TestDownloadAsset:
    @respx.mock
    def test_success(self, tmp_path: Path):
        payload = b"fake scriptpilot binary contents"
        respx.get("https://cdn.test/asset").mock(
            return_value=httpx.Response(200, content=payload)
        )

        dst = tmp_path / "scriptpilot.new"
        download_asset("https://cdn.test/asset", dst, _sha256(payload), "vTest")

        assert dst.read_bytes() == payload
        assert (dst.stat().st_mode & 0o777) == 0o755

    @respx.mock
    def test_404(self, tmp_path: Path):
        respx.get("https://cdn.test/asset").mock(
            return_value=httpx.Response(404, text="nope")
        )

        dst = tmp_path / "scriptpilot.new"
        with pytest.raises(UpgradeError) as exc:
            download_asset("https://cdn.test/asset", dst, "sha256:0", "vTest")
        assert "404" in str(exc.value)
        assert not dst.exists()

    @respx.mock
    def test_digest_mismatch(self, tmp_path: Path):
        payload = b"payload"
        respx.get("https://cdn.test/asset").mock(
            return_value=httpx.Response(200, content=payload)
        )
        wrong = "sha256:" + "0" * 64
        dst = tmp_path / "scriptpilot.new"
        with pytest.raises(UpgradeError) as exc:
            download_asset("https://cdn.test/asset", dst, wrong, "vTest")
        assert "checksum mismatch" in str(exc.value)
        assert not dst.exists()


class TestInstallBinary:
    def test_happy_path(self, tmp_path: Path):
        target = tmp_path / "scriptpilot"
        src = tmp_path / ".scriptpilot-upgrade-1234"
        target.write_bytes(b"old")
        src.write_bytes(b"new")
        os.chmod(src, 0o755)

        install_binary(src, target)

        assert target.read_bytes() == b"new"
        assert not (tmp_path / "scriptpilot.old").exists()
        assert not src.exists()
        assert (target.stat().st_mode & 0o777) == 0o755

    def test_permission_error_on_first_rename(self, tmp_path: Path):
        target = tmp_path / "scriptpilot"
        src = tmp_path / ".scriptpilot-upgrade-1234"
        target.write_bytes(b"old")
        src.write_bytes(b"new")

        os.chmod(tmp_path, 0o555)
        try:
            with pytest.raises(UpgradeError) as exc:
                install_binary(src, target)
            assert "move existing binary aside" in str(exc.value)
        finally:
            os.chmod(tmp_path, 0o755)

        assert target.read_bytes() == b"old"

    def test_rollback_on_second_rename_failure(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "scriptpilot"
        src = tmp_path / ".scriptpilot-upgrade-1234"
        target.write_bytes(b"old")
        src.write_bytes(b"new")

        original = upgrade._rename_impl
        calls = {"n": 0}

        def fake_rename(o, n):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated rename failure")
            return original(o, n)

        monkeypatch.setattr(upgrade, "_rename_impl", fake_rename)

        with pytest.raises(UpgradeError) as exc:
            install_binary(src, target)
        assert "install new binary" in str(exc.value)

        assert target.read_bytes() == b"old"
        assert not (tmp_path / "scriptpilot.old").exists()


def _fake_release_url(respx_mock, tag: str, payload: bytes) -> str:
    digest = _sha256(payload)
    asset_url = "https://cdn.test/asset"
    respx_mock.get(asset_url).mock(
        return_value=httpx.Response(200, content=payload)
    )

    body = {
        "tag_name": tag,
        "assets": [
            {
                "name": ASSET_NAME,
                "browser_download_url": asset_url,
                "size": len(payload),
                "digest": digest,
            }
        ],
    }
    respx_mock.get(
        "https://api.test/repos/krzysztofciepka/script-pilot/releases/latest"
    ).mock(return_value=httpx.Response(200, json=body))
    return "https://api.test"


class TestRunUpgrade:
    @linux_only
    @respx.mock
    def test_already_latest(self, tmp_path: Path):
        respx.get(
            "https://api.test/repos/krzysztofciepka/script-pilot/releases/latest"
        ).mock(
            return_value=httpx.Response(
                200, json={"tag_name": "v0.0.42", "assets": []}
            )
        )

        target = tmp_path / "scriptpilot"
        target.write_bytes(b"current")

        out = io.StringIO()
        rc = run_upgrade(out, "v0.0.42", "https://api.test", str(target))

        assert rc == 0
        assert "up to date" in out.getvalue()
        assert target.read_bytes() == b"current"

    @linux_only
    @respx.mock
    def test_dev_build_always_proceeds(self, tmp_path: Path):
        target = tmp_path / "scriptpilot"
        target.write_bytes(b"old")
        api = _fake_release_url(respx, "v0.0.99", b"new binary bytes")

        out = io.StringIO()
        rc = run_upgrade(out, "dev", api, str(target))

        assert rc == 0, out.getvalue()
        assert target.read_bytes() == b"new binary bytes"

    @linux_only
    @respx.mock
    def test_full_path(self, tmp_path: Path):
        target = tmp_path / "scriptpilot"
        target.write_bytes(b"v0.0.20-bytes")
        payload = b"v0.0.21-bytes"
        api = _fake_release_url(respx, "v0.0.21", payload)

        out = io.StringIO()
        rc = run_upgrade(out, "v0.0.20", api, str(target))

        assert rc == 0, out.getvalue()
        assert target.read_bytes() == payload
        assert not (tmp_path / "scriptpilot.old").exists()
        assert "v0.0.20" in out.getvalue()
        assert "v0.0.21" in out.getvalue()

    @pytest.mark.skipif(
        _is_linux_amd64(),
        reason="unsupported-platform branch only reachable off linux/amd64",
    )
    def test_unsupported_platform(self):
        out = io.StringIO()
        rc = run_upgrade(out, "v0.0.20", "http://unused", "/unused")
        assert rc == 1
        assert "self-upgrade is not supported" in out.getvalue()


class TestHumanSize:
    @pytest.mark.parametrize(
        "n,expected",
        [
            (0, "0 B"),
            (512, "512 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1048576, "1.0 MB"),
            (16355490, "15.6 MB"),
        ],
    )
    def test_formatting(self, n, expected):
        assert human_size(n) == expected
