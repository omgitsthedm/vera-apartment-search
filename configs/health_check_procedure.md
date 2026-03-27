# Health Check Procedure

Run:

```bash
cd /Users/davidmarsh/Desktop/Apartment\ Search
./scripts/health_check.sh
```

## What It Checks

- project root exists
- logs directory exists
- required config files exist
- required scripts exist
- output directories are writable
- `ollama` is available on the machine
- expected local models are installed

## If A Check Fails

- Missing folder: create or restore the folder inside the project root
- Missing config: restore it from version control or rebuild it manually from this project
- Missing model: pull it locally with `ollama pull <model>`
- Permission failure: verify the Desktop folder is writable
- Script missing: rebuild the script before running the pipeline

## Recommended Habit

- Run health checks before enabling any schedule
- Run health checks after changing configs or models
- Review the newest log in `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/logs/` after any failure
