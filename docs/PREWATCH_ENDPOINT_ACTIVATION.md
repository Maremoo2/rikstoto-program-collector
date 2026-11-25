# CORE-STABILITY-001A-ENDPOINT — activation boundary

This branch adds a read-only Ledger reader and a manually dispatched authentication diagnostic. The existing Collector integration defaults to diagnostic-only; no publication, workflow schedule or Ledger write is authorized. A successful ChatGPT Sheets connector read does not establish Actions credentials.

## Before any activation
1. HQ review the exact PR HEAD and CI. Do not merge just to make a test green.
2. Owner may create a marker-only draft through the GitHub Releases UI (tag and title `prewatch-ready-v1`, body `{"schema":"prewatch_ready_v1","status":"NOT_INITIALIZED","bet_authority":false}`). Save draft; never publish. Alternatively use the existing approved bootstrap workflow after it exists on main. Numeric authenticated GET and draft/published_at checks required. No actual source data in public repository artifacts.
3. Configure a dedicated Google service account with Viewer access only on the named Ledger. Enable Sheets API and configure GitHub OIDC Workload Identity Federation with a provider condition scoped to this repository's immutable ID, trusted ref and exact diagnostic workflow; grant only workloadIdentityUser to the intended principal. No long-lived key, no public sharing. Set GitHub repository variables PREWATCH_WIF_PROVIDER and PREWATCH_LEDGER_READER_SA to the owner-provisioned identifiers. Set the GitHub Actions secret PREWATCH_LEDGER_SPREADSHEET_ID to the exact authorized spreadsheet ID (never commit it). Verify organization policies and least privilege; do not give the service account Editor.
4. The manual diagnostic workflow requires main and configuration; run only after separate approval. It logs aggregate counts, not sheet content. A 403 is a failed read, never an empty Ledger.
5. For a source integration diagnostic use --read-ledger with authenticated ADC and existing authenticated GitHub CLI. The packet remains operational_publication_allowed=false. No write or release PATCH in this task.

A future task must prove the dedicated draft readback and complete live source + Ledger + transport chain, including one serialized writer and final prestart rechecks. The draft marker alone is not a valid packet. Rollback: leave main and scheduled Pre-Watch unchanged, revoke service account Viewer / WIF and delete only the newly created test draft if applicable with owner approval.
