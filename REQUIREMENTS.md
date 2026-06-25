# flat-finder — Product Requirements

## One-line pitch
**An intelligent, autonomous agent that finds your perfect flat while you get on with your day — no more spending 20+ hours scrolling through every listing that "might work".**

## Problem
Renting in London is a part-time job. You set a few crude portal filters (price, beds, area), then manually open hundreds of listings to check the things that actually matter — floor area, EPC, whether there's a lift, which way it faces, how far the tube is, what's nearby — and the good ones are gone within hours. It's ~20+ hours of repetitive work per search, and you still miss things.

## Solution
You describe your ideal flat once, in plain English. The agent then runs continuously on your behalf: it checks for new listings every hour, enriches each one with the data humans never bother to look up, scores it against *your* specific preferences, and hands you a ranked shortlist with the reasons — plus a ready-to-send enquiry for the best matches. You review; you don't trawl.

## Goal (hackathon framing — "Hands Off")
- **Autonomous:** runs unattended on a schedule, no human in the loop to find + filter.
- **Makes money:** renters pay for the Pro feed (real-time + auto-enquiry drafts).
- **Measurable:** dashboard shows listings scanned, matches surfaced, hours saved, revenue.

---

## Scope

### In scope (MVP — what we build first)
1. **Understand the user's filtering (the brief).**
   - Accept a free-text wishlist ("1–2 bed, East London, ≤£2,500, must have a lift, south-ish facing, EPC C+, <10 min walk to a tube, gym + supermarket nearby, no basement").
   - Parse it into structured criteria: price, beds, areas, must-haves, nice-to-haves, avoids, commute target.
2. **Search for new listings every hour.**
   - Scheduled job (Modal cron) that pulls fresh listings from the portals and de-duplicates against everything already seen, so the user only ever sees genuinely new matches.
3. **Intelligent / niche enrichment (the moat).** Per listing, hydrate the fields portals don't let you filter on:
   - **Floor area (sqm)** — from the listing, or read off the floorplan, or the EPC record.
   - **EPC rating** — from the listing and the free gov.uk EPC Open Data API.
   - **Lift / no-lift, floor level** — extracted from the description.
   - **Floorplan understanding** — a vision model reads the floorplan (room count/sizes, separate kitchen, layout, aspect). *Showstopper feature.*
   - **Window facing / orientation** — best-effort, inferred from the floorplan's compass arrow. *(Clearly labelled as an estimate.)*
   - **Nearby amenities** — count gyms / supermarkets / restaurants / parks within a short walk (OpenStreetMap).
   - **Transport / commute** — nearest station, walk time, and door-to-door commute to a place the user cares about (TfL + postcodes.io).
4. **Score + rank against the brief**, with human-readable reasons ("under budget; area: Hackney; 4 min to Overground; 3 gyms nearby; lift unconfirmed").
5. **Draft the enquiry** for top matches (register interest / request a viewing) — presented for the user to approve and send.
6. **Dashboard** — ranked shortlist with reasons, listing links, the drafted enquiry, and the running stats.

### Out of scope for now (later phases — deliberately toned down)
- **Auto-sending enquiries** without approval (ToS / anti-bot / impersonation risk). MVP keeps a one-tap "approve to send".
- **Conversational negotiation with agents** + **auto-booking viewings into your calendar.** (Phase 2.)
- **Learning from feedback** (thumbs up/down to refine the model). (Phase 2 — start simple: the brief is the source of truth.)
- Multi-city / non-London. Buying (sales) as opposed to renting.

---

## Key user flow (MVP)
1. User writes a one-paragraph brief (and contact details).
2. Agent parses it into structured criteria.
3. Every hour: pull new listings → enrich → score → store.
4. New matches above a threshold appear on the dashboard, ranked, with reasons + a drafted enquiry.
5. User reviews the shortlist and one-tap approves the enquiries they like.

## Success metrics
- **Hours saved** vs. manual search (headline number for the pitch).
- # quality matches surfaced per day; precision of the shortlist (are the top 5 actually good?).
- Lead time: how quickly after a listing goes live we surface it.
- Conversion: free → paid; £ revenue.

---

## Architecture / stack
- **Modal** — always-on scheduler (hourly scan) + enrichment workers.
- **Shared memory** — a named `modal.Dict` holds briefs, seen-listings, enrichment cache, matches, and an agent-coordination blackboard; every agent in the Modal workspace attaches to it by name. (Local JSON store for offline dev.)
- **OpenAI (vision + text)** — brief parsing, floorplan reading, nuanced scoring, enquiry drafting.
- **Free data APIs** — gov.uk EPC, TfL, postcodes.io, OpenStreetMap Overpass.
- **PayPal** — subscription / success fee.
- **Wassist** — conversational layer to capture the brief from the renter (and, in Phase 2, talk to agents).
- **(Phase 2) Playwright** — enquiry submission; **Google Calendar** — viewing booking.

### Pipeline
```
brief (free text)
   → parse to structured criteria
   → [hourly] collect new listings  → de-dupe
   → enrich (EPC, floorplan vision, commute, nearby POIs)
   → score against brief (+ reasons)
   → rank → dashboard → drafted enquiry → one-tap approve
```

## Data-source notes & risks
- Portal **ToS / scraping**: Rightmove & Zoopla forbid scraping and block bots. For production, switch the data layer to **parsing the portals' own email alerts** or a licensed feed. (The collector/store split makes this swap easy.)
- **Orientation** is an estimate, not ground truth — label it as such.
- **Auto-actions** (enquiry/booking) carry impersonation + wasted-viewing risk — keep human approval in the MVP.

## Phasing
- **Phase 1 (MVP / hackathon):** brief → hourly search → enrich → score → ranked shortlist + drafted enquiry + dashboard. *(This is what's already scaffolded and running.)*
- **Phase 2:** auto-send (approved), conversational viewing booking + calendar, feedback-based preference learning.
- **Phase 3:** more portals via compliant feeds, multi-city, B2B (relocation agencies / employers).
