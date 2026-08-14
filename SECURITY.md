# Security Policy

AutoInfo handles sensitive material: LLM API keys, webhook endpoints, and
locally collected knowledge. This document explains which versions are
supported, how to report a vulnerability, and what you can expect from the
maintainers.

## Supported versions

Only the **latest release** is supported with security fixes. If a
vulnerability is discovered and the fix is straightforward, it also lands on
`main` immediately so the next release carries it. Older releases are not
backported; users are encouraged to upgrade.

## Reporting a vulnerability

- **Preferred**: use GitHub private vulnerability reporting (Security
  Advisories) on the repository. This keeps the report confidential until a
  fix is ready.
- **Non-sensitive bugs**: if you believe an issue is not security-sensitive,
  open a normal issue and label it `security` so maintainers triage it with
  security context.

If you are unsure whether something is sensitive, report it privately anyway.
A report about a potential vulnerability is never wasted.

### What to include

A good report contains, where possible:

- **Affected version**: the release or commit you tested
- **Steps to reproduce**: minimal, concrete, and repeatable
- **Impact**: what an attacker could do, and under what conditions
- **Suggested fix** (optional): a patch or an idea; not required

## Handling commitments

- Maintainers acknowledge receipt within **48-72 hours** of a report.
- Disclosure is coordinated with the reporter before anything is made public.
  Private reports stay private until a fix is released, typically within 14
  days for serious issues. We will not publish a report or a fix until you
  agree it is safe.
- The reporter is credited in the advisory and release notes unless
  anonymity is requested.

## Security-relevant areas of AutoInfo

These areas carry the most risk and receive the most scrutiny:

- **LLM API keys (BYOK)**: keys are passed through the
  `AUTOINFO_LLM_API_KEY` environment variable and referenced in configs as a
  `${...}` placeholder that the host process interpolates. The `configure_llm`
  MCP tool stores only an environment-variable reference, never the raw key,
  and AutoInfo does not write keys to config files or logs.
- **Webhook endpoints**: incoming and outgoing webhooks use HMAC signature
  verification. Always verify signatures before trusting a payload.
- **REST API**: the FastAPI server binds to localhost on port 8741. It has no
  authentication by design; it must never be exposed to untrusted networks.
- **SQLite knowledge base**: KB entries, user profiles, and cost data live in
  SQLite files. Access control, retention, and GDPR-style deletion are the
  primary protections.
- **MCP server**: the stdio transport is a local protocol. Do not bridge it
  to a remote or untrusted process.

## Responsible use

- **Never commit secrets.** Not LLM keys, not webhook secrets, not
  credentials. The runtime `.gitignore` covers generated state
  (`collections/`, `knowledge/`, `outputs/`, `autoinfo.db`, `.autoinfo/`),
  but it cannot protect a secret you paste into a tracked file.
- Treat any leaked key as compromised and rotate it.
- Report suspected leaks or vulnerabilities through the channels above
  instead of discussing them in public issues.
