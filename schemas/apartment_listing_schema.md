# Apartment Listing Schema

This is the normalized schema used after raw discovery is converted into one common structure.

## Minimum Fields

- `listing_uid`: stable local listing identifier
- `source_name`: source family such as `streeteasy` or `craigslist`
- `source_listing_id`: source-native identifier when available
- `source_url`: canonical listing URL
- `first_seen_at`: first local time the listing was seen
- `last_seen_at`: latest local time the listing was seen
- `scraped_at`: timestamp of the raw snapshot
- `title`: normalized listing title
- `full_description`: full listing text
- `address_raw`: raw address text
- `address_normalized`: cleaned address text when possible
- `neighborhood`: normalized neighborhood
- `borough`: normalized borough
- `zip`: zip code if known
- `latitude`: latitude if known
- `longitude`: longitude if known
- `rent`: monthly rent as a number
- `beds`: numeric bedroom count
- `baths`: numeric bathroom count
- `square_feet`: square footage if known
- `fee_status`: fee or no-fee signal
- `broker_name`: broker or agent name if present
- `owner_name`: owner name if enriched
- `contact_name`: contact person name
- `contact_phone`: phone if present
- `contact_email`: email if present
- `amenities`: array of amenity strings
- `pet_policy`: pet policy text
- `laundry`: boolean or null
- `dishwasher`: boolean or null
- `furnished_flag`: boolean or null
- `sublet_flag`: boolean or null
- `room_share_flag`: boolean or null
- `by_owner_signal`: boolean or null
- `management_company_signal`: boolean or null
- `likely_independent_landlord_score`: numeric 0 to 100
- `duplicate_cluster_id`: cluster identifier after dedupe
- `verification_status`: `matched_public_records`, `partial_address_only`, `no_public_match`, or `not_qualified_for_enrichment`
- `rent_stabilized_signal`: `likely`, `possible`, `unclear`, or `not indicated`
- `hpd_risk_score`: numeric 0 to 100, where higher is riskier
- `dob_risk_score`: numeric 0 to 100, where higher is riskier
- `court_signal`: short text summary
- `overall_score`: numeric 0 to 100
- `recommendation`: `pursue`, `pursue cautiously`, or `skip`
- `analyst_notes`: concise human-readable notes

## Important Rule

When precision is weak, keep the raw text and downgrade confidence instead of inventing certainty.
