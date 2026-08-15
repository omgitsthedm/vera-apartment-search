#!/usr/bin/env python3
"""Privacy-boundary tests. `python3 tests/test_public_lens.py`

public_lens.py decides what leaves this machine. It is now the single
implementation — the dashboard repo imports it rather than holding a copy —
and the cloud sweep publishes with it unattended, to a public URL, with no
human between the run and the world.

Every leak found in this system so far arrived the same way: a new section
was added and nobody remembered to treat it as private. These tests verify
the stronger rule: a field is absent unless the public schema admits it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(name)


def load():
    spec = importlib.util.spec_from_file_location("pl", ROOT / "scripts" / "public_lens.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PL = load()

PERSONAL = {
    "contact_name": "Maria Ortega",
    "contact_email": "maria@example.com",
    "contact_phone": "917-555-0142",
    "contact_brief": "call after 6pm",
    "analyst_notes": "she sounded motivated",
}


def listing(**kw):
    d = {
        "listing_uid": "u1",
        "address_normalized": "459 keap st",
        "rent": 2200,
        "overall_score": 72,
        "recommendation": "pursue",
        "listing_confidence_score": 71,
        "hpd_risk_score": 12.0,
        "dob_risk_score": 4.0,
        "source_name": "craigslist",
        "borough": "Brooklyn",
        **PERSONAL,
    }
    d.update(kw)
    return d


def test_personal_layer_never_ships() -> None:
    print("\nthe personal layer:")
    hunt = {
        "generated_at": "2026-08-04T00:00:00+00:00",
        "shortlist": [listing()],
        "manual_review": [listing(listing_uid="u2")],
        "daily_changes": {"new_listings": [listing(listing_uid="u3")],
                          "price_changes": [], "gone_listings": []},
    }
    pub = PL.build_public_payload(hunt, extras={"pool": [listing(listing_uid="u4")]})
    blob = json.dumps(pub)
    for field, value in PERSONAL.items():
        check(f"{field} is gone", field not in blob and value not in blob)


def test_four_borough_public_scope() -> None:
    print("\nthe four-borough public scope:")
    # Coordinates are authoritative, even when a source's borough label says
    # something else. No-coordinate records need an explicit allowed borough.
    coordinate_manhattan = listing(
        listing_uid="coordinate-manhattan", borough="Staten Island",
        latitude=40.7288, longitude=-73.9828,
    )
    coordinate_brooklyn = listing(
        listing_uid="coordinate-brooklyn", borough="Unknown",
        latitude=40.7143, longitude=-73.9540,
    )
    coordinate_queens = listing(
        listing_uid="coordinate-queens", borough="Unknown",
        latitude=40.7606, longitude=-73.7968,
    )
    coordinate_bronx = listing(
        listing_uid="coordinate-bronx", borough="Unknown",
        latitude=40.8448, longitude=-73.8648,
    )
    declared_queens = listing(listing_uid="declared-queens", borough="Queens")
    staten_island = listing(
        listing_uid="staten-island", borough="Brooklyn",
        latitude=40.5795, longitude=-74.1502,
    )
    unresolved_coordinates = listing(
        listing_uid="outside-polygons", borough="Manhattan",
        latitude=40.7000, longitude=-74.0000,
    )
    unknown_without_coordinates = listing(listing_uid="unknown", borough=None)
    candidates = [
        coordinate_manhattan, coordinate_brooklyn, coordinate_queens,
        coordinate_bronx, declared_queens, staten_island, unresolved_coordinates,
        unknown_without_coordinates,
    ]
    hunt = {
        "generated_at": "2026-08-04T00:00:00+00:00",
        "shortlist": candidates,
        "manual_review": candidates,
        "daily_changes": {
            "new_listings": candidates,
            "price_changes": candidates,
            "gone_listings": candidates,
        },
    }
    pub = PL.build_public_payload(hunt, extras={"pool": candidates})
    expected = {
        "coordinate-manhattan", "coordinate-brooklyn", "coordinate-queens",
        "coordinate-bronx", "declared-queens",
    }
    rows = [pub["pool"], pub["shortlist"], pub["manual_review"]]
    rows.extend(pub["daily_changes"][key] for key in ("new_listings", "price_changes", "gone_listings"))
    surface_ids = [{item["listing_uid"] for item in group} for group in rows]
    check("every public listing surface is four-borough scoped",
          all(ids == expected for ids in surface_ids), str(surface_ids))
    manhattan = next(item for item in pub["pool"] if item["listing_uid"] == "coordinate-manhattan")
    check("coordinates override a conflicting source borough", manhattan.get("borough") == "Manhattan")
    check("a no-coordinate allowed borough remains publishable",
          any(item["listing_uid"] == "declared-queens" and item.get("borough") == "Queens" for item in pub["pool"]))
    check("the completed scoped payload passes the independent audit", PL.audit_public_payload(pub) == [])

    injected = json.loads(json.dumps(pub))
    injected["pool"].append(PL.sanitize_listing(staten_island))
    check("the audit rejects an injected out-of-scope listing",
          any("four-borough public scope" in problem for problem in PL.audit_public_payload(injected)))


def test_a_section_nobody_sanitized() -> None:
    """The failure mode that has actually happened, twice."""
    print("\na section added later that nobody remembered to sanitize:")
    hunt = {
        "generated_at": "2026-08-04T00:00:00+00:00",
        "shortlist": [],
        # Neither section exists in the public schema.
        "landlord_outreach_v3": {"queue": [{"unit": "3R", **PERSONAL}]},
        "deeply": {"nested": [{"under": {"several": {"levels": PERSONAL}}}]},
    }
    pub = PL.build_public_payload(hunt)
    blob = json.dumps(pub)
    check("an unknown top-level section is stripped",
          "contact_phone" not in blob and "917-555-0142" not in blob)
    check("unknown data at arbitrary depth is stripped",
          "analyst_notes" not in blob and "she sounded motivated" not in blob)
    check("the unknown section itself is private by default",
          "landlord_outreach_v3" not in pub and "deeply" not in pub)


def test_watchlist_accusations_are_neutralized() -> None:
    print("\nowner accusations vs public record:")
    hunt = {
        "generated_at": "2026-08-04T00:00:00+00:00",
        "shortlist": [listing(
            trust_caveats=["Owner is a known scammer"],
            hpd_open_violations=19,
        )],
        "risk_watch": ["matched the bad-actor list"],
        "messages": ["blacklist hit on this BBL"],
    }
    pub = PL.build_public_payload(hunt)
    blob = json.dumps(pub)
    for word in ("known scammer", "bad-actor", "blacklist"):
        check(f"'{word}' does not ship", word.lower() not in blob.lower())
    check("the neutral phrasing replaces it", PL.NEUTRAL_RISK in blob)
    check("violation COUNTS stay — they are public record",
          pub["shortlist"][0].get("hpd_open_violations") == 19)


def test_owner_only_and_watchlist_sections() -> None:
    print("\nowner-only surfaces:")
    hunt = {"generated_at": "2026-08-04T00:00:00+00:00", "shortlist": [],
            "watchlist": {"properties": [{"address": "5 Tudor City Pl"}]}}
    pool = [listing(source_urls=["a", "b"], why_it_made_the_cut="cheap",
                    review_out_reason="too far", raw_snapshot_path="/Users/davidmarsh/x.json")]
    pub = PL.build_public_payload(hunt, extras={
        "pool": pool,
        "state_buckets": {"shortlisted": [listing()], "filtered_out": [listing(), listing()], "other": [listing()]},
    })
    check("the manual watchlist section is dropped", "watchlist" not in pub)
    got = set(pub["pool"][0].keys())
    check("owner-only pool fields are dropped",
          not (got & PL.PUBLIC_DROP_FIELDS), str(sorted(got & PL.PUBLIC_DROP_FIELDS)))
    check("no local filesystem path ships", "davidmarsh" not in json.dumps(pub))
    check("state_buckets publishes counts, not a second copy of every record",
          pub["state_buckets"] == {"shortlisted": 1, "filtered_out": 2}, str(pub["state_buckets"]))
    check("the payload is labelled as the public lens", pub.get("lens") == "public")


def test_archive_cannot_outrun_the_feed() -> None:
    print("\nthe drop archive:")
    pub = PL.build_public_payload(
        {"generated_at": "2026-08-04T00:00:00+00:00", "shortlist": []},
        extras={"pool": [listing()]},
    )
    with tempfile.TemporaryDirectory() as d:
        Path(d, "archive.json").write_text(json.dumps([{
            "date": "2026-08-03",
            "run_id": "old-run",
            "listings": [{"listing_uid": "old", "contact_phone": "917-555-0142"}],
            "private_note": "must not survive a re-publish",
        }]))
        stat = PL.maintain_archive(pub, d)
        text = (Path(d) / "archive.json").read_text()
        check("today's full-fit listing is archived", stat["archived"] == 1, str(stat))
        check("the archive carries no personal field, including prior entries",
              not any(f in text for f in PL.PERSONAL_FIELDS) and "private_note" not in text)
        # re-publishing the same day must replace, not stack
        PL.maintain_archive(pub, d)
        again = json.loads((Path(d) / "archive.json").read_text())
        check("a re-publish replaces its day rather than duplicating it",
              sum(item.get("date") == "2026-08-04" for item in again) == 1, str(len(again)))


def test_the_audit_catches_what_the_lens_would_miss() -> None:
    """The guard is independent of the lens on purpose: it is the thing that
    still works if someone bypasses build_public_payload entirely."""
    print("\nthe independent guard:")
    clean = PL.build_public_payload({"generated_at": "x", "shortlist": [listing()]})
    check("a properly built payload audits clean", PL.audit_public_payload(clean) == [])
    cloud = json.loads(json.dumps(clean))
    cloud["origin"] = "cloud"
    check("the cloud publisher's origin label audits clean", PL.audit_public_payload(cloud) == [])

    leaked = json.loads(json.dumps(clean))
    leaked["some_new_export"] = {"rows": [{"contact_phone": "917-555-0142"}]}
    problems = PL.audit_public_payload(leaked)
    check("a hand-injected personal field is caught",
          any("contact_phone" in p for p in problems), str(problems))

    accused = json.loads(json.dumps(clean))
    accused["note"] = "flagged on the bad actor list"
    check("un-neutralized watchlist wording is caught",
          any("watchlist wording" in p for p in PL.audit_public_payload(accused)))

    unlabelled = json.loads(json.dumps(clean))
    unlabelled.pop("lens")
    check("a payload not labelled 'public' is caught",
          any("lens" in p for p in PL.audit_public_payload(unlabelled)))


def test_audit_fails_closed_for_malformed_public_containers() -> None:
    print("\nmalformed known containers fail closed:")
    clean = PL.build_public_payload(
        {"generated_at": "x", "shortlist": [listing()]},
        extras={
            "pool": [listing()],
            "state_buckets": {"shortlisted": [listing()]},
            "transit_tables": {"L": [["Lorimer St", 180]]},
        },
    )
    check("the valid container shapes audit clean", PL.audit_public_payload(clean) == [])

    malformed_pool = json.loads(json.dumps(clean))
    malformed_pool["pool"] = {"not": "an array"}
    check("a non-array pool fails", any("$.pool — must be an array" in p for p in PL.audit_public_payload(malformed_pool)))

    null_pool = json.loads(json.dumps(clean))
    null_pool["pool"] = None
    check("a present null pool fails", any("$.pool — must be an array" in p for p in PL.audit_public_payload(null_pool)))

    null_daily_rows = json.loads(json.dumps(clean))
    null_daily_rows["daily_changes"] = {"new_listings": None}
    check("a present null daily listing array fails",
          any("$.daily_changes.new_listings — must be an array" in p
              for p in PL.audit_public_payload(null_daily_rows)))

    malformed_buckets = json.loads(json.dumps(clean))
    malformed_buckets["state_buckets"] = {"invented_bucket": 1, "shortlisted": "one"}
    bucket_problems = PL.audit_public_payload(malformed_buckets)
    check("unknown or non-count state buckets fail",
          any("invented_bucket" in p and "schema" in p for p in bucket_problems)
          and any("shortlisted" in p and "count" in p for p in bucket_problems), str(bucket_problems))

    malformed_transit = json.loads(json.dumps(clean))
    malformed_transit["transit_tables"] = {"L": "not a stop array", "G": [["Court Sq", -1]]}
    transit_problems = PL.audit_public_payload(malformed_transit)
    check("malformed transit tables fail",
          any("transit_tables.L" in p and "array" in p for p in transit_problems)
          and any("transit_tables.G[0]" in p for p in transit_problems), str(transit_problems))

    malformed_nested = json.loads(json.dumps(clean))
    malformed_nested["pool"][0]["transit"] = "not an object"
    check("malformed nested containers fail",
          any("pool[0].transit — must be an object" in p for p in PL.audit_public_payload(malformed_nested)))

    malformed_market = json.loads(json.dumps(clean))
    malformed_market["market_context"] = {"series": {"all_nyc": {"median_asking_rent": "not an array"}}}
    check("malformed market-series containers fail",
          any("market_context.series.all_nyc.median_asking_rent — must be an array" in p
              for p in PL.audit_public_payload(malformed_market)))

    scalar_slots = json.loads(json.dumps(clean))
    scalar_slots["generated_at"] = {"hidden": "value"}
    scalar_slots["pool"][0]["rent"] = [2200]
    scalar_slots["sources"] = [{"source_name": {"hidden": "value"}, "record_count": 1}]
    scalar_problems = PL.audit_public_payload(scalar_slots)
    check("containers cannot hide in top-level or nested scalar slots",
          any("$.generated_at — must be a finite JSON scalar" in p for p in scalar_problems)
          and any("$.pool[0].rent — must be a finite JSON scalar" in p for p in scalar_problems)
          and any("$.sources[0].source_name — must be a finite JSON scalar" in p for p in scalar_problems),
          str(scalar_problems))

    wrong_scalar_types = json.loads(json.dumps(clean))
    wrong_scalar_types["generated_at"] = 123
    wrong_scalar_types["pool"][0]["rent"] = "2200"
    wrong_scalar_types["sources"] = [{"source_name": 42, "record_count": 1}]
    wrong_type_problems = PL.audit_public_payload(wrong_scalar_types)
    check("typed scalar contracts reject the wrong primitive type",
          any("$.generated_at — must be a string" in p for p in wrong_type_problems)
          and any("$.pool[0].rent — must be a number" in p for p in wrong_type_problems)
          and any("$.sources[0].source_name — must be a string" in p for p in wrong_type_problems),
          str(wrong_type_problems))

    unguarded_listing_fields = []
    for field in PL.PUBLIC_LISTING_SCALAR_FIELDS:
        probe = json.loads(json.dumps(clean))
        probe["pool"][0][field] = {"hidden": "value"}
        if not any(f"$.pool[0].{field} — must be a finite JSON scalar" in p
                   for p in PL.audit_public_payload(probe)):
            unguarded_listing_fields.append(field)
    check("every listing scalar slot rejects containers",
          not unguarded_listing_fields, str(sorted(unguarded_listing_fields)))

    non_finite = json.loads(json.dumps(clean))
    non_finite["pool"][0]["rent"] = float("nan")
    check("non-finite numbers fail",
          any("$.pool[0].rent" in p and ("finite" in p or "valid JSON" in p)
              for p in PL.audit_public_payload(non_finite)))

    absent_optional = {"lens": "public", "generated_at": "x"}
    check("genuinely absent optional containers remain valid",
          PL.audit_public_payload(absent_optional) == [])


def test_public_schema_is_complete_and_private_by_default() -> None:
    print("\nexplicit listing schema and generic sensitive guards:")
    source = listing(
        owner_email="owner@example.com",
        unusual_safe_new_field="do not publish this yet",
        component_scores={"search_fit": 8, "private_token": "not public"},
        landlord_portfolio={"bldgs": 2, "contact_name": "Maria Ortega"},
        landlord_reason_summary=["Public landlord record match"],
        transit={"station": "Lorimer St", "lines": ["L", "G"], "phone": "917-555-0142"},
        price_history=[["2026-08-01", 2200], ["not-a-date-only"], {"rent": 2200}],
    )
    pub = PL.build_public_payload(
        {"generated_at": "x", "shortlist": [source]},
        extras={"pool": [source]},
    )
    entry = pub["pool"][0]
    check("legitimate UI fields remain",
          entry.get("listing_uid") == "u1" and entry.get("rent") == 2200
          and entry.get("landlord_reason_summary") == ["Public landlord record match"])
    check("alternate sensitive names are absent",
          "owner_email" not in entry and "unusual_safe_new_field" not in entry)
    check("nested objects are projected too",
          entry.get("component_scores") == {"search_fit": 8}
          and entry.get("landlord_portfolio") == {"bldgs": 2}
          and entry.get("transit") == {"station": "Lorimer St", "lines": ["L", "G"]})
    check("malformed nested value shapes are absent", entry.get("price_history") == [["2026-08-01", 2200]])
    check("clean projection passes the independent audit", PL.audit_public_payload(pub) == [])

    aggregate = json.loads(json.dumps(pub))
    aggregate["pool"][0]["contact_reuse_count"] = 3
    check("the approved contact-reuse aggregate audits clean",
          PL.audit_public_payload(aggregate) == [])

    injected = json.loads(json.dumps(pub))
    injected["pool"][0]["alternate_contact_channel"] = "owner@example.com"
    injected["pool"][0]["component_scores"]["future_metric"] = 9
    injected["pool"][0]["trust_caveats"] = ["Call +1 (917) 555-0142"]
    problems = PL.audit_public_payload(injected)
    check("generic sensitive key and value checks reject alternate names",
          any("alternate_contact_channel" in p for p in problems)
          and any("email-like value" in p for p in problems)
          and any("phone-like value" in p for p in problems), str(problems))
    check("nested unknown keys are rejected",
          any("component_scores.future_metric" in p for p in problems), str(problems))

    personal_contact = json.loads(json.dumps(aggregate))
    personal_contact["pool"][0]["contact_email"] = "owner@example.com"
    check("contact-like personal keys still fail",
          any("contact_email" in p for p in PL.audit_public_payload(personal_contact)))


def test_audit_scans_every_listing_not_only_the_first_400() -> None:
    print("\nthe complete publication traversal:")
    clean = PL.build_public_payload(
        {"generated_at": "x", "shortlist": [listing()]},
        extras={"pool": [listing()]},
    )
    base = clean["pool"][0]
    clean["pool"] = [dict(base, listing_uid=f"u{index}") for index in range(401)]
    clean["pool"].append(dict(base, listing_uid="leak-after-400", contact_phone="917-555-0142"))
    problems = PL.audit_public_payload(clean)
    check("a leak after item 400 is caught",
          any("pool[401].contact_phone" in p for p in problems), str(problems))


def test_hunt_lens_stays_private_by_contrast() -> None:
    """The hunt lens is the OWNER's view — it should keep contact details.
    If this ever starts stripping them, the private view has silently lost
    the data David actually needs to call a landlord."""
    print("\nthe hunt lens (private, by contrast):")
    payload = {"generated_at": "x", "shortlist": [listing()], "reviewed_out": []}
    hunt = PL.build_hunt_payload(payload)
    check("the owner still gets the phone number",
          hunt["shortlist"][0].get("contact_phone") == "917-555-0142")
    check("but the public lens over it does not",
          "917-555-0142" not in json.dumps(PL.build_public_payload(hunt)))


if __name__ == "__main__":
    test_personal_layer_never_ships()
    test_four_borough_public_scope()
    test_a_section_nobody_sanitized()
    test_watchlist_accusations_are_neutralized()
    test_owner_only_and_watchlist_sections()
    test_archive_cannot_outrun_the_feed()
    test_the_audit_catches_what_the_lens_would_miss()
    test_audit_fails_closed_for_malformed_public_containers()
    test_public_schema_is_complete_and_private_by_default()
    test_audit_scans_every_listing_not_only_the_first_400()
    test_hunt_lens_stays_private_by_contrast()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        sys.exit(1)
    print("all public-lens tests passed")
