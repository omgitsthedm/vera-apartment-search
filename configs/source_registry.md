# Interpret VERA source status

`configs/source_catalog.json` is the tracked machine-readable source inventory. The latest sanitized feed reports observed source counts and health for one completed run. This document defines how to interpret those values without freezing a changing source list into prose.

## Status meanings

- **Healthy**: the source ran and produced results consistent with its current observed baseline
- **Degraded**: the source ran, but yield or query success fell enough to require review
- **Partial**: some source queries succeeded and some failed
- **Failing**: the source ran and all relevant queries failed or its expected output disappeared
- **Disabled**: configuration deliberately excludes the source
- **Not scheduled**: the current environment deliberately skips the source, often because the network cannot reach it safely
- **Experimental**: the adapter is measured but not relied on for coverage

Do not infer source health from a static label in this file. Inspect `source_health` and `sources` in the latest sanitized feed, then compare the result with the source's current configuration and run evidence. A source with zero records is not automatically broken, and a source labeled `ok` is not automatically healthy.

## Change rules

- Keep request delays and cache time-to-live values conservative
- Do not add authenticated scraping, CAPTCHA bypass, residential-proxy escalation, or terms-avoidance behavior
- Do not change enabled sources, target geography, price criteria, or scoring behavior without David's approval
- Update `configs/source_catalog.json`, executable adapter tests, and this interpretation contract together when a status model changes
- Never copy credentials, private alerts, personal preferences, or raw source payloads into this registry

Run `python3 tests/test_source_honesty.py` after an adapter, catalog, source-status, or price-ceiling change.
