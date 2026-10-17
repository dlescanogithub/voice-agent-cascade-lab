from __future__ import annotations

import hashlib
import re
from pathlib import Path

from voice_cascade.secretscan import main, scan_path, scan_text


def _piece(*parts: str) -> str:
    return "".join(parts)


def test_each_key_shape_is_detected_and_short_values_are_not() -> None:
    samples = {
        "xai_key": _piece("xai-", "a" * 20),
        "sk_ant_key": _piece("sk-ant-", "b" * 20),
        "sk_proj_key": _piece("sk-proj-", "c" * 20),
        "sk_key": _piece("sk-", "d" * 20),
        "sk_underscore_key": _piece("sk_", "e" * 20),
        "github_token": _piece("ghp_", "f" * 20),
        "github_pat": _piece("github_pat_", "g" * 20),
        "aws_access_key": _piece("AKIA", "H" * 16),
        "bearer_token": _piece("Bearer ", "i" * 20),
        "private_key": _piece("-----BEGIN ", "PRIVATE KEY-----"),
        "slack_token": _piece("xoxb-", "j" * 10),
    }
    for name, secret in samples.items():
        findings = scan_text(f"token={secret}")
        assert any(item.startswith(f"{name}:") for item in findings), name

        negatives = (
            _piece("xai-", "a" * 19),
            _piece("sk-", "d" * 19),
            _piece("sk_", "e" * 19),
            _piece("ghp_", "f" * 19),
            _piece("github_pat_", "g" * 19),
            _piece("AKIA", "H" * 15),
            _piece("Bearer ", "i" * 19),
            "-----BEGIN PUBLIC KEY-----",
            _piece("xoxb-", "j" * 9),
            "skill-set is not a credential",
            "the bearer of this note is short",
        )
        for text in negatives:
            assert scan_text(text) == [], text
        # A short sk-ant- / sk-proj- value is not that shape. It can still
        # match the wider sk- shape, which is a real detection.
        for name, text in (
            ("sk_ant_key", _piece("sk-ant-", "b" * 19)),
            ("sk_proj_key", _piece("sk-proj-", "c" * 19)),
        ):
            names = [item.split(":", 1)[0] for item in scan_text(text)]
            assert name not in names


def test_specific_shapes_are_reported_even_when_a_wider_shape_also_matches() -> None:
    secret = _piece("sk-ant-", "k" * 20)
    names = [item.split(":", 1)[0] for item in scan_text(secret)]
    assert "sk_ant_key" in names
    assert "sk_key" in names


def test_scan_path_reports_every_shape_in_a_file(tmp_path: Path) -> None:
    body = "\n".join(
        (
            _piece("ghp_", "m" * 20),
            _piece("-----BEGIN ", "RSA PRIVATE KEY-----"),
        )
    )
    (tmp_path / "leak.txt").write_text(body, encoding="utf-8")
    findings = scan_path(tmp_path)
    assert any(item.startswith("github_token:") for item in findings)
    assert any(item.startswith("private_key:") for item in findings)


def test_scanner_main_exits_on_a_fixture(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0
    (tmp_path / "leak.txt").write_text(_piece("ghp_", "z" * 20), encoding="utf-8")
    assert main([str(tmp_path)]) == 1


def test_vendored_scanner_hash_matches_provenance() -> None:
    text = Path("docs/PROVENANCE.md").read_text(encoding="utf-8")
    match = re.search(r"sha256:\s*([0-9a-f]{64})", text)
    assert match is not None
    digest = hashlib.sha256(Path("src/voice_cascade/secretscan.py").read_bytes()).hexdigest()
    assert digest == match.group(1)
