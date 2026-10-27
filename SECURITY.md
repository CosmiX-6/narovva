# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's
[private vulnerability reporting](https://github.com/CosmiX-6/narovva/security/advisories/new)
(Security tab → "Report a vulnerability"), not in a public issue. Include what you
found, how to reproduce it, and its impact. You should hear back within a week.

## How narovva handles credentials

- Secrets are only read from environment variables (GitHub Actions secrets in CI).
  Channel YAML files name the variables; they never hold values.
- `narovva.logsafe` holds HTTP client loggers at WARNING (request URLs carry the
  Instagram token) and redacts token and key shapes from every log line and every
  error stored in the database.
- Refreshed Instagram tokens are stored encrypted (Fernet, `TOKEN_ENCRYPTION_KEY`).
- Workflows run with a read-only `GITHUB_TOKEN`. CI for pull requests uses no secrets.

If a token is exposed anyway, revoke and replace it: see
[docs/operations.md](docs/operations.md#the-instagram-token).
