# Reverse-geocoding Craigslist pins — measured, and rejected

**Status: DO NOT BUILD.** Tested 2026-08-04 against ground truth. It fails.

## The idea, and why it looks good

The cloud sweep's biggest verification loss is address quality. Of the 42
listings that qualified for enrichment on 2026-08-04, only 5 matched public
records; **27 came back `partial_address_only`**. Looking at them, the cause
is obvious — Craigslist posters fill the location field with a street name
and no house number:

```
huron            Greenpoint
rodney           Williamsburg
forsyth st.      Lower East Side
fifth ave        East Harlem (North)
saint nicholas   Harlem (South)
broadway         Upper West Side
```

And **every one of them carries coordinates**. All 223 Craigslist records in
that sweep had `lat`/`lon`. NYC GeoSearch v2 has a working reverse endpoint
that returns a house number, a street and a **BBL**:

```
GET https://geosearch.planninglabs.nyc/v2/reverse?point.lat=40.7288&point.lon=-73.9828&size=1
-> 424 EAST 11 STREET, bbl 1004380020, distance 0.011 km
```

So: reverse-geocode the pin, get the BBL, pull HPD and DOB, verify 27 more
listings a night. It looks like free coverage.

## The measurement

Craigslist pin accuracy is testable directly, because 46 of the 223 records
carry **both** a full street-number address and a pin. Those are ground
truth: reverse-geocode the pin and check whether it returns the address the
poster actually typed.

Sample of 24:

| Result | Count |
|---|---|
| **Exact house number** | **0 / 24** |
| Same street, wrong building | 17 / 24 |
| Different street entirely | 7 / 24 |

Distances were small — 2 m to 40 m — which is exactly what makes this
dangerous. The pin is always *near* and never *right*.

The worst cases were not near-misses:

```
950 Nostrand Ave #2R   -> 370 GRAHAM AVENUE      (different street, 14 m)
209 Malcolm X Blvd     -> 51 PATCHEN AVENUE      (different street,  6 m)
2129 Davidson Ave      -> 2111 GD CONCOURSE      (different street, 40 m)
818 Lexington Avenue   -> 853 LEXINTON AVENUE    (35 buildings off)
```

Craigslist deliberately offsets the map pin. That is a privacy feature for
posters, and it is working as designed.

## Why this matters more than the coverage it would buy

VERA's entire claim is that what it shows about a building is true and
cited. A BBL derived this way would be **confidently wrong**, and the
product would attach a real building's violation count, litigation history
and landlord portfolio to an apartment that is not in it.

The failure is silent and unfalsifiable from the user's side. Someone would
skip a good apartment because of another building's record, or walk into a
bad one because the building next door is clean. Twenty-seven more
"verified" listings a night is not worth one of those.

Note the asymmetry: a missing verification is visible and honest — the app
already says `partial_address_only` and explains it. A wrong verification
looks exactly like a right one.

## What the coordinates ARE good for

The same 24-row test says the pin is on the right street 17 times and within
40 m every time. That is far more precision than a neighbourhood polygon
needs, and it is already how `config/nta_lookup.py` uses it — resolving a
borough-only or wrong label to the true NTA, which was verified separately
against four mislabelled RentHop records the same day.

**Coordinates are authoritative for neighbourhood and useless for building
identity.** Both halves of that sentence are measured, not assumed.

## If someone wants to revisit this

The only version worth considering would need a real accuracy signal from
the source, not an inferred one — and Craigslist's sapi does not publish
one. Failing that, a reverse-geocoded BBL would have to be carried in its
own field, never merged into `verification_status`, and shown with wording
that makes the uncertainty impossible to miss. That is a lot of machinery to
surface a fact VERA would not be willing to stand behind, which is the
argument for not building it at all.

Reproduce the measurement: the script is in this commit's message trail —
take `raw/craigslist/craigslist_snapshot_*.json`, keep records where
`map_address` starts with a house number and `lat` is present, reverse each
pin, compare house numbers.
