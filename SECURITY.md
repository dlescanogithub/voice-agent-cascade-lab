# Security

This repository is a local lab. It does not talk to a real clinic, a real phone network, or a paid model vendor.

## Reporting

Email the maintainer privately. Do not open a public issue that contains keys, transcripts of real people, or a live webhook secret. This lab should never have those, and a report should not add them.

## What is in scope

- HMAC verification on the local tool webhook
- Idempotency and the dead-letter queue
- PII redaction in logs and traces
- The secret scanner and CI

## What is not in scope

- Hosting, telephony, or multi-tenant auth
- A real identity provider
- Recording consent for real callers
- Timestamp freshness windows on webhooks (retries reuse the same body on purpose)

## Secrets

Configuration is environment variables only. The process does not read a `.env` file. `.env.example` has empty placeholders. The demo HMAC string `local-demo-not-a-secret` is a lab constant, not a credential. Do not reuse it anywhere except this local demo.

Refuse-only flags default off and raise before any network call. The optional live command is a separate path. It stays off unless `LIVE_MODE=1`, reads keys only from the environment, and exits 2 with no request when config is missing or the pre-call estimate exceeds `MAX_LIVE_SPEND_USD`. CI does not set `LIVE_MODE`. Tests use a fake HTTP layer and do not open a socket. Do not commit keys. Do not put keys in `var/`, and do not paste them into the README table.

## Data

Every caller, phone number, and appointment in this repo is synthetic. Do not load a real schedule into the SQLite file.
