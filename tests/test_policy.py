from __future__ import annotations

from pathlib import Path

BANNED = ("enda" + "va", "rel" + "ias", "fan " + "universe")
MEASURED_PHRASES = (
    "SIMULATED placeholder, 2026-10-17",
    "python -m voice_cascade eval",
    "python -m voice_cascade live",
    "The harness computes and gates a latency budget.",
    "p95 end-to-end: 1004.5 ms (SIMULATED)",
    "p50 end-to-end: 896 ms (SIMULATED)",
    "false-cut rate (aggressive, SIMULATED): 1.0",
    "false-cut rate (balanced, SIMULATED): 0.0",
    "false-cut rate (patient, SIMULATED): 0.0",
    "missed eligible interruptions (balanced, SIMULATED): 0.0",
    "missed barge-in including sub-threshold (balanced, SIMULATED): 0.5",
    "premature endpoint (aggressive, SIMULATED): 1.0",
    "p95 end-to-end (aggressive, SIMULATED): 780 ms",
    "p95 end-to-end (patient, SIMULATED): 1413.75 ms",
    "## Use cases, governance and business strategy",
    "### Measured with real providers",
    "stays empty until a pasted run",
)


def test_readme_locks_measured_phrases() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    for phrase in MEASURED_PHRASES:
        assert phrase in text, phrase


def test_repo_has_no_banned_client_names() -> None:
    roots = [Path("src"), Path("tests"), Path("docs"), Path("README.md"), Path("CHANGELOG.md")]
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix in {".wav", ".png", ".pyc", ".sqlite"}:
                continue
            if "__pycache__" in path.parts:
                continue
            try:
                lowered = path.read_text(encoding="utf-8").lower()
            except UnicodeDecodeError:
                continue
            for banned in BANNED:
                assert banned not in lowered, f"{banned} in {path}"
