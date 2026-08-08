# VERA engine source of truth

Verified 2026-08-08.

## Public product

- Product owner: Little Fight NYC. VERA is David's internal product and public demo, not a client.
- Operational identity: `hello@littlefightnyc.com`
- Sole public canonical URL: `https://littlefightnyc.com/vera/`
- Public application source: `/Users/davidmarsh/Code/LiFi NYC/Little Fight NYC Business/Website/littlefightnyc-website/app/public/vera`
- Public application repository: `https://github.com/omgitsthedm/littlefightnyc-website`, branch `main`
- Browser data contract:
  - `https://littlefightnyc.com/vera/data/public.json`
  - `https://littlefightnyc.com/vera/data/archive.json`
  - `https://littlefightnyc.com/vera/data/meta.json`

The browser must use only those first-party Little Fight NYC endpoints. The
Little Fight Netlify project owns the page, its assets, the routes, and the
public response surface. VERA has no second public application or deploy
target.

## Private engine

- Canonical local checkout: `/Users/davidmarsh/Code/Personal/vera-apartment-search`
- Canonical repository: `https://github.com/omgitsthedm/vera-apartment-search`, branch `main`
- Active local LaunchAgents reference this Code checkout.

The engine remains separate so raw hunt data, owner-only fields, credentials,
notes, and other private state never enter the public website repository or
Netlify property. The old Projects and Desktop/OpenClaw copies are not sources
of truth. Do not move this checkout, alter schedules, or run the pipeline as
housekeeping. A future move to `/Users/davidmarsh/Code/LiFi NYC/Internal/VERA/`
must update every loaded LaunchAgent in one authorized maintenance window.

## Sanitized feed publication

The scheduled GitHub Actions sweep publishes exactly three sanitized files to
the orphan `feed` branch of this engine repository:

- `public.json`
- `archive.json`
- `meta.json`

`scripts/public_lens.py` is the single privacy boundary.
`audit_public_payload()` rejects personal fields or un-neutralized private
watchlist language before the workflow writes anything public. Cross-run
engine memory remains in the private Actions cache, not the public feed branch.

The Little Fight site rewrites its exact `/vera/data/*` routes to those three
upstream feed files. That feed branch is an implementation detail and sanitized
upstream; it is not a browser-facing product. Visitors stay on
`littlefightnyc.com` for the entire VERA experience.

The historical `nyc-apartment-search-dashboard` checkout and `vera-pipeline`
Netlify project are retired, nondeployable references. Never sync or publish
into the dashboard checkout, run its Netlify deploy path, restore a dedicated
VERA Netlify site, or add VERA Netlify credentials. Any older documentation
that instructs an operator to use `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`, or a
separate VERA host is superseded by this file.

## Cost constraint

David's standing requirement is that VERA spend nothing.

- VERA has no dedicated hosting project; the public product is part of the
  existing Little Fight NYC website.
- The feed workflow uses only the automatic `GITHUB_TOKEN`.
- The Hugging Face classifier runs on the workflow runner's CPU, with no
  inference API bill.
- GitHub Actions is unmetered for this public engine repository. If the
  repository becomes private, Actions may become metered; flag that before
  changing visibility.
