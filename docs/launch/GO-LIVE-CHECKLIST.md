# VERA public-launch kit — everything staged, nothing published
**Every item below is prepared. Each needs only David's go. (2026-08-03)**

## Gate 1 — Full machine independence (~20 min, no publication)
- [ ] `configs/mail_ingest.json` filled (Gmail app password + SE/Zillow saved-search alerts) → the sanctioned firehose joins every sweep
- [ ] `configs/reddit.json` filled (script app from reddit.com/prefs/apps) → authenticated Reddit
- [ ] `gh secret set NETLIFY_AUTH_TOKEN -R omgitsthedm/vera-apartment-search`
- [ ] `gh secret set NETLIFY_SITE_ID -R omgitsthedm/vera-apartment-search` (fcd6f741-d479-44f4-8ee1-51da2b321227) → cloud publish; the Mac becomes optional

## Gate 2 — Open the code (publication decision)
- [ ] Decide: engine repo public? If yes: swap `README.md` for `docs/launch/README-public.md`, add topics (`nyc`, `apartments`, `housing`, `tenant-rights`, `open-data`), confirm no gitignored file ever committed (`git log --all --name-only | grep -E "mail_ingest|reddit.json|alerts/"` → empty)
- [ ] configs/user_preferences.json contains the personal search map — either genericize or accept it as the honest example

## Gate 3 — Hugging Face (account decision)
- [ ] Publish `state/transit_stations.json` + `transit_routes.json` (MTA GTFS derivations) and `app assets/geo/hoods.json` (NTA2020 simplification) as HF datasets — card drafted at `docs/launch/HF-DATASET-CARD.md`
- [ ] Optionally: the receipts archive as a living dataset (the public track record)

## Gate 4 — Tell people (the only true adoption lever)
- [ ] r/NYCapartments post — the community that named every feature demand
- [ ] Show HN — the audience that upvoted theretowhere and RentSure
- [ ] The pitch is already true: "Every claim survives 'how do you know that?'"

**Standing refusals hold at any scale: no accounts, no tracking, no urgency theater, no landlord contact, no protected-class signals — the fair-housing and corrections pages ship first-class.**
