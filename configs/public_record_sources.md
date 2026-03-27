# Public Record Sources

VERA now supports a live official-refresh step using NYC Open Data before enrichment.

## Official Datasets

- HPD Building Registration and Contacts:
  - dataset id: `tesw-yqqr`
  - use: registration signal and latest registration date
- HPD Buildings:
  - dataset id: `kj4p-ruqc`
  - use: building match confirmation and HPD building identifiers
- Housing Maintenance Code Complaints:
  - dataset id: `ygpa-z7cr`
  - use: complaint counts over the last 3 years
- Housing Maintenance Code Violations:
  - dataset id: `wvxf-dwi5`
  - use: total violations and open-violation counts over the last 3 years
- Housing Litigation Dataset:
  - dataset id: `59kj-x8nc`
  - use: housing-litigation count over the last 3 years

## Current Operating Rule

- Live official refresh happens after dedupe and before enrichment.
- If a live official row matches cleanly, VERA overlays those risk counts onto the local reference layer.
- If the live address lookup fails, VERA falls back to the local seed reference data instead of pretending the building has no history.

## Important Limits

- This step currently focuses on HPD and housing-litigation risk, not owner-name truth.
- Owner identity, owner type, and rent-stabilization heuristics may still rely on local reference data or future ACRIS or PLUTO integration.
- Exact address matching is only as good as the listing address quality.
