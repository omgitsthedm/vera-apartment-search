# Check engine health

Run the health check from the canonical engine checkout:

```bash
cd /Users/davidmarsh/Code/Personal/vera-apartment-search
./scripts/health_check.sh
```

The script verifies the canonical project structure, required source and configuration files, active LaunchAgent templates, and writable private runtime directories. It recreates missing ignored runtime directories before checking them.

Ollama is optional. The deterministic pipeline does not require a local large language model, and the health check reports an absent Ollama installation as an optional capability rather than a failure.

If a check fails:

- Restore a missing tracked file from verified Git history
- Confirm that the canonical Code checkout is writable
- Confirm that all four `configs/launchd-v2/` templates still point to the canonical engine path
- Review the newest private log under `/Users/davidmarsh/Code/Personal/vera-apartment-search/logs/` without copying it into Git or a public handoff
- Run the isolated tests in `VERA-HANDOFF.md` before any authorized pipeline or schedule action

Do not enable, replace, or remove a schedule as part of a health check. Schedule maintenance requires separate authorization.
