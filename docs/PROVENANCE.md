# Provenance

The task asked for a documented copy of the eval kit in
`https://github.com/dlescanogithub/agent-runtime-evals`, pull request #1
(draft) on branch `cursor/agent-runtime-evals-mvp-7e58`, commit
`55cfd4183fb2489d77fc9c8552e008274dc78f77`.

## What was readable

On 2026-10-17 the GitHub token available to this workspace could read
`dlescanogithub/voice-agent-cascade-lab` and received HTTP 404 for
`dlescanogithub/agent-runtime-evals`. A 404 on a private repository is the
API's way of saying the token cannot see it. No file from that commit was
downloaded. Nothing in this tree is a byte-for-byte copy.

## What was reimplemented from the written contract

| Idea in the brief | Module here |
| --- | --- |
| Cassette provider and fake provider | `llm.py`, `stt.py`, `tts.py`, `cassettes/clinic.json` |
| JSONL trace | `trace.py` |
| JSON logging | `logging_setup.py` |
| Invariant checks, not trajectories | `evalkit.py` |
| Secret scan | `secretscan.py` |
| Real provider off unless an env flag is set | `providers.py`, `config.py` |

If that repository becomes readable later, diff these modules against commit
`55cfd4183fb2489d77fc9c8552e008274dc78f77` and replace this note with the list
of lines that were actually copied and the list of lines that changed.
