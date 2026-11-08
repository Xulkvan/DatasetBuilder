# Security Policy

## Supported Versions

Only the latest release on `main` receives security fixes.
Older versions are supported on a best-effort basis.

Current version: see `/api/version`.

## Reporting a Vulnerability

**Do not open a public issue for security problems.**

Please report security vulnerabilities privately via
[GitHub Security Advisories](https://github.com/Xulkvan/DatasetBuilder/security/advisories/new).

Please include:

- affected version (`/api/version` output),
- steps to reproduce,
- expected vs actual behavior,
- potential impact (data leak, RCE, DoS, auth bypass, …).

## What to Expect

- Acknowledgement within **72 hours**.
- Triage + initial assessment within **7 days**.
- Fix or mitigation plan, or a reasoned decision to defer, within **30 days**.
- Credit in the release notes unless you prefer to remain anonymous.

## Scope

In scope:

- Authentication / session / CSRF / RBAC bypass.
- SSRF in imports, webhooks, or stream URLs.
- Path traversal / zip-slip / zip-bomb in imports and backups.
- Stored XSS in user-controlled fields.
- Data exposure via API v2 (`/api/v2/*`) when `API_KEY` is set.
- Secrets leakage via logs, exports, or backups.

Out of scope (see `docs/adr/`):

- Rate limiter being in-memory only (`docs/adr/0008-rate-limiter-multiworker.md`).
- `/api/docs` / `/openapi.json` exposure when explicitly enabled in prod.
- Weaknesses requiring an already-compromised host or admin credentials.

## Disclosure Policy

We follow coordinated disclosure. Once a fix is released, we publish a
security advisory with CVE request (if applicable) and credit.
