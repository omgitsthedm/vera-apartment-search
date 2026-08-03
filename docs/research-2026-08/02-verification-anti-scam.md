# Verifying a Private NYC Landlord & Listing — August 2026

Research agent report, 2026-08-03. Claims carry sources; uncertainties marked.

## 1. Ownership verification

**Chain of proof:** (a) Latest deed from **ACRIS** (a836-acris.nyc.gov, DOF, records to 1966) by address/BBL — grantee on most recent deed = legal owner. (b) **HPD Multiple Dwelling Registration** (HPDOnline; required annually for 3+ unit buildings and non-owner-occupied 1–2 family) — names Head Officer, Managing Agent, Site Contact, who must be real people. The counterparty should match the deed name, an HPD-registered contact, or be traceably employed by them. (c) If deed says LLC: exact name through **NYS DOS Business Entity Search** (formation date, status, service address) and portfolio map on **JustFix Who Owns What** (wow.justfix.org, built on nycdb, links buildings via shared HPD contacts). ACRIS mortgage signature pages often reveal the human member who signed for the LLC. (Sources: DwellCheck, RegWatch, MetroDeeds guides.)

**NY LLC Transparency Act (verified):** Signed Dec 2023; the March 1, 2024 chapter amendment (Ch. 102) killed the public database — BOI sits in a secure, NON-public DOS database, law-enforcement/court-order access only. Effective Jan 1, 2026 (pre-2026 LLCs file by end of 2026). Hochul vetoed the decoupling bill Dec 19, 2025, keeping NY tied to the federal CTA — and since FinCEN's Mar 26, 2025 interim rule limited "reporting company" to foreign entities, Holland & Knight's Jan 2026 read: NYLTA now effectively covers only non-U.S. LLCs. **Bottom line: a renter cannot unmask an LLC via the NYLTA in Aug 2026.** Use HPD registration humans + ACRIS signatures + DOS search instead. *(Scope-narrowing is a firm interpretation of an evolving situation — uncertain.)*

## 2. Fake-listing fingerprints, 2026

- **Volume:** FTC Dec 2025 spotlight: ~65,000 reports, ~$65M losses since 2020, median $1,000; ~50% start on Facebook, 16% Craigslist; ages 18–29 3x likelier to lose money. NYS: 589 rental-scam complaints 2025 (+55% vs 2023).
- **AI photos ("housefishing"):** common enough that Mayor Mamdani's July 2026 "Rental Ripoff Report" (2,400+ testimonies, 23 policy proposals) proposes mandatory "clear and conspicuous" AI-alteration disclosure via DCWP with StreetEasy/Zillow — **proposed, not yet law**. Detection: impossible views, melted text, mismatched fixtures; classifier APIs (Hive, AI-or-Not) — probabilistic.
- **Cloned listings:** hijacked StreetEasy photos reposted on CL/FB at different address/price. Automatable: reverse image (Lens, TinEye/Bing APIs) or perceptual hashing (pHash) surviving crops/recolors; ~40% of clones stay live 20+ hours (industry data).
- **Bait pricing / payment:** ~$1,000+ under comps; "out-of-town landlord" who can't show; Zelle/CashApp/Venmo/wire "good-faith deposit" pre-viewing (no chargeback).

## 3. Building health — per-address, queryable (Socrata, data.cityofnewyork.us)

| Signal | Dataset ID | Notes |
|---|---|---|
| HPD violations A/B/C/I | wvxf-dwi5 | open + class-C density per unit |
| HPD complaints | uwyv-629c | |
| DOB complaints | eabe-havv | |
| DOB violations / ECB | 3h2n-5cm9 / mkgf-zjhb, ECB 6bgk-3dad | |
| 311 heat/hot-water | erm2-nwe9 (complaint_type filter) | winter clustering = neglect; 246K+ heat complaints 2024 |
| Bedbugs | wz6d-d3jb (LL69/2017 owner filings) | underreported |
| HPD litigation | 59kj-x8nc | 7A/harassment/heat |
| CONH list | bzxi-2tsw | harassment scrutiny flag |
| Vacate orders | tb8q-a3ar | live vacate = do not rent |

Housing court: WebCivil Local (party-name search) + OCA de-identified landlord-tenant XML extracts (rolling 5 yrs, monthly). Per-case data de-identified, so tenant-side screening limited by design — but searching the LANDLORD/LLC as party in WebCivil is legal and works.

## 4. Person-level checks

Phone: Twilio Lookup / IPQS → line type (VOIP = elevated risk), carrier, spam score. Email: domain age, disposable flags, breach history (weak signal alone). **Fuzzy-matching pitfalls:** deed "123 Main St Realty LLC," HPD head officer a family member, emailer a legit property manager — exact-name mismatch is the NORM. Score a *chain* (claimed name → HPD contact → deed party → DOS filing); treat mismatch as "ask for proof of authority," not "scam." FP risk highest with family-owned small buildings and third-party managers.

## 5. Legal money rules (verified current, Aug 2026)

- **Security deposit: max 1 month** (GOL §7-108, HSTPA 2019). No first+last+security stacking.
- **Application fee: ≤$20** or actual cost, whichever less; waivable with tenant's own recent report.
- **FARE Act** (LL119/2024, eff June 11, 2025): whoever hires the broker pays; landlord's-agent fees to tenants banned; all tenant-payable fees itemized in listing + agreement. DCWP as of June 1, 2026: 2,033 complaints, 74 summonses / 100 alleged violations, ~$27K penalties, ~$15K restitution. Fines $1,000 first / $2,000 repeat.
- **Good Cause Eviction** (Apr 2024, auto in NYC): covers market units UNLESS owner ≤10 units statewide (LLC look-through: natural person's whole portfolio counts), building pre-2009, rent under ~245% FMR; leases must include good-cause notice rider. Small-building tenants may still be covered if owner's portfolio >10.
- **Stabilization:** DHCR rent-history request (free, portal.hcr.ny.gov) is ground truth — current tenant requests it; stabilized leases require the DHCR rider (RA-LR1). 2025–26 renewals: +3%/1yr, +4.5%/2yr.

## AUTOMATE vs MANUAL

| Check | Automatable? | Source | FP risk |
|---|---|---|---|
| Deed owner lookup | Semi (ACRIS scrape; no official API) | ACRIS | Low |
| HPD registration contacts | Yes | tesw-yqqr / feu5-w2e2 | Low |
| Name-chain match | Yes (fuzzy) | above | HIGH — managers/family |
| LLC unmasking via NYLTA | NO — non-public | — | n/a |
| DOS entity status | Yes (scrape) | dos.ny.gov | Low |
| Violations/complaints/litigation/vacate/CONH/bedbug/311 | Yes — Socrata IDs above | NYC Open Data | Low |
| Housing-court by landlord name | Semi (WebCivil captchas) | courts | Med |
| Reverse-image clone detection | Yes (TinEye/Bing, pHash) | photos | Med |
| AI-photo detection | Yes (classifiers) | — | Med-High |
| Price-vs-market delta | Yes (comps) | portals | Med |
| Phone/email reputation | Yes | Twilio/IPQS | Med |
| DHCR rent history | Manual only (tenant request) | DHCR | n/a |
| Broker license check | Yes (scrape) | NYS DOS licensee search | Low |
| In-person unit + keys-match-lock | Manual, non-negotiable | — | — |

## SCAM KILL-LIST (flag → detection)

1. Money before viewing (Zelle/wire/gift card/crypto) → abort. (FTC #1)
2. Rent ≥20–30% below comps → automated delta.
3. Photos found at another address → reverse-image/pHash hit.
4. "Landlord abroad," can't show unit → abort.
5. Contact matches nothing in deed + HPD + DOS + license AND refuses proof of authority.
6. VOIP-only phone + weeks-old email → soft flag, combine.
7. App fee >$20 / deposit >1 month / landlord's-broker fee → illegal either way.
8. Active vacate order (tb8q-a3ar) or unit absent from HPD/DOB records.
9. AI-glossy photos, no disclosure → classifier flag (rule proposal-stage).
10. Pressure scripting ("pay to hold") → manual judgment.

**Uncertainties:** NYLTA foreign-only scoping could shift; Mamdani AI-disclosure is proposal-stage; FARE figures point-in-time (June 2026); scam counts undercount badly.
