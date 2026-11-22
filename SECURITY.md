# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :--- |
| `0.1.x` (research preview) | Yes |
| Older development snapshots | No |

## Reporting a Vulnerability

Use GitHub Security → **Report a vulnerability** for private disclosure. Do not open a public issue for credentials, broker/account identifiers, or exploitable defects.

Include: affected commit/tag, reproduction steps, impact, and a redacted proof. Do not include real tokens, account IDs, server names, balances, tickets, or PnL.

## Response Timeline

- Initial acknowledgement: within 72 hours.
- Severity triage: within 7 days.
- Fix or mitigation plan: within 14 days for confirmed P0/P1 issues.
- Public disclosure: after a fix or coordinated disclosure window.

## Scope

- Runtime risk boundaries, watchdog, emergency killswitch, credential storage, Telegram admin controls, and deterministic verification tooling.
- Source tree, CI, and release artifacts published from tagged commits.

## Out of Scope

- Third-party broker terminals, broker infrastructure, OANDA/FRED services, local operating system configuration, and user-managed API credentials.
- Any use of this software with real capital without independent review. See `DISCLAIMER.md`.

## Security Design Notes

- Zero LLM in the production inference/execution path.
- Outbound-only design; no inbound trading control port is required.
- Credentials are entered offline and stored via Windows DPAPI under the current OS user.
- Telegram control uses an integer admin whitelist, single-use nonces, and two-step confirmation for destructive actions.
- Runtime starts in `SIGNAL_ONLY` with live orders disabled.
- Independent watchdog validates limits before execution.
- If a modified version exposes any remote interactive interface, AGPL-3.0 Section 13 requires a prominent way for remote users to obtain Corresponding Source. Document such interfaces before enabling them.

## Secrets Policy

Never commit `.env`, `.secrets.enc`, databases, logs, broker reports, account IDs, server names, or performance screenshots. Use placeholders in `.env.example`. Rotate any credential that has appeared in a commit or log.
