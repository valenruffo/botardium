# Runtime Config Migration

Phase 1 moves reusable secrets out of tracked config and workspace exports.

- Workspace AI keys now live in `config/runtime_secrets.json` under the writable runtime root.
- In local dev that file resolves inside the repo, so `.gitignore` explicitly excludes it from accidental commits.
- `scripts/main.py` migrates legacy `users.google_api_key` and `users.openai_api_key` values into that runtime file on startup, then clears the database columns.
- `opencode.json` now reads MCP credentials from environment variables via `{env:...}` placeholders.
- Workspace exports omit AI keys, Instagram passwords, and session material by default.
- Legacy ZIP archives that still contain keys, passwords, cookies, or `sessions/` content are rejected during import.

Operator steps:

1. Put shared bootstrap secrets in `.env` only when they are needed as local fallbacks.
2. Re-open Botardium once so startup can migrate legacy workspace AI keys into `config/runtime_secrets.json`.
3. Never copy `config/runtime_secrets.json` into exports or source control; each machine should rebuild it locally.
4. Recreate any old workspace export archives after upgrading; pre-Phase-1 archives are intentionally rejected.
5. After importing a sanitized workspace, rebind AI keys, Instagram passwords, and fresh sessions locally.
