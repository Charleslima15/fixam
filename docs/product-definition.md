# FixAm — Product Definition v0.5

**Name:** FixAm (Pidgin for "fix it")
**Market:** Buea, Cameroon (single-city pilot)
**Status:** Pre-build. Phase 0 validation not yet run.
**Purpose of this document:** Freeze the product decisions so technical design can begin against a fixed target.

---

## 1. What this is

A curated, WhatsApp-accessed network that connects people who need a local service done to vetted providers who can do it, and charges the provider for the introduction.

A customer describes a problem in natural language, by text, voice note, or photo. The system identifies the trade, the area, and the urgency, then dispatches the request to a small number of vetted providers. The first provider to accept pays one lead credit and receives the customer's contact details. The two parties handle the job between themselves.

The platform sells **introductions**, not jobs.

---

## 2. What changed from the original concept, and why

This is a deliberate narrowing of the earlier product-discovery concept. The reasoning is recorded here so we don't drift back to the wider version by accident.

| Original framing | Current framing | Why |
|---|---|---|
| Products (bread, oil, groceries) | Services (plumbing, electrical, repair) | Search cost for staples is near zero. People already know where the boutique is. Search cost for a trusted plumber is genuinely high. |
| Merchant pings are an interruption to be minimised | Provider pings are inbound work | A shopkeeper serving a customer resents the ping. An idle tradesman wants it. This inverts the response-rate problem. |
| Thousands of merchants per quarter | Under 200 providers, town-wide | Supply acquisition becomes weeks of fieldwork, not a permanent data operation. |
| Live inventory freshness is the core problem | Provider profiles are near-static | No inventory to maintain. Freshness collapses to availability, which providers volunteer. |
| Households as primary demand | One customer type; high-frequency customers recruited first | A household needs a plumber twice a year. A landlord with twelve rooms needs someone weekly. The system treats them identically; frequency only decides who we recruit first. |
| Monetisation deferred to "Phase 6" | Monetisation is in the MVP | Pre-paid lead credits work from day one and don't depend on tracking offline cash transactions. |
| Open directory, coverage as a goal | Closed and curated, trust as a goal | Recourse is what referral chains provide and directories don't. Fifteen vetted providers beat two hundred unvetted ones. |

---

## 3. Users

**Provider.** A tradesperson: plumber, electrician, phone/laptop technician, mechanic, carpenter, tailor, appliance or generator repairer. Owns a phone, uses WhatsApp, may have limited written literacy, likely code-switches between English, Pidgin and French. Pays us. Success for him is a job he wouldn't otherwise have got.

**Customer.** Anyone who needs a service done. Pays nothing, ever. Success for them is a trustworthy person on the phone within minutes.

There is one customer type. The system never branches on who a customer is. What varies is **request frequency** — a landlord managing student rooms, a salon or a hotel may need someone weekly; a household twice a year — and frequency is already captured by request history. Trust tiers (§7.2) are driven by that history, not by a label.

The distinction matters in exactly one place: **who we recruit during Phase 0** (§8). High-frequency customers generate enough volume to measure conversion within weeks; households alone would not.

A longer-term note: business customers can be invoiced, which makes them the only plausible route to a second revenue line. Out of scope now.

---

## 4. Scope

**In scope for pilot:** 3–4 service categories, chosen for landlord relevance. Recommended starting set — plumbing, electrical, appliance/generator repair, and one of carpentry or phone repair. Geographic scope is Buea town, with area granularity at the quarter level (Molyko, Bonduma, Great Soppo, Checkpoint, Mile 16, and so on), not GPS radius.

**Explicitly out of scope:**

- Product/goods discovery. Not now, possibly not ever.
- Payments for the job itself. Cash between customer and provider.
- Delivery logistics.
- Scheduling, calendars, quotes, invoicing for providers.
- A customer-facing mobile app or web app.
- Multi-city expansion.
- Any provider-side dashboard beyond WhatsApp.

Anything on this list that gets built before Phase 0 passes is wasted work.

---

## 5. Core flows

### 5.1 Customer request

1. Customer messages the platform number. Text, voice note, or photo with caption.
2. System extracts: **trade**, **area**, **urgency**, **problem description**. If the trade or area is unclear, it asks one clarifying question, not three.
3. System states back what it understood and asks for a single explicit confirmation before dispatching. This is the primary spam filter and is not optional — see §7.2.
4. On confirmation, request enters dispatch.

No provider names, numbers, or counts are shared at this stage. The customer may be told that providers cover the area and how many are available, nothing more. A user who asks for a list is redirected, not refused: *"I don't share contacts directly — tell me what you need and I'll get someone to take the job."*

### 5.2 Dispatch and acceptance

1. System selects a ranked shortlist of eligible providers: correct trade, covers that area, currently marked available, sufficient credit balance, in good standing.
2. Request is offered in **waves** (proposed default, to be validated by pilot data — see §5.6).
3. First provider to accept is assigned. One credit is deducted at the moment of acceptance.
4. Provider receives customer name, phone number, area, and problem description.
5. Customer receives provider name, phone number, trade, and rating.
6. Remaining providers are told the request is taken. No charge.
7. The assigned provider can report a bad lead within a short window: unreachable number, nobody at the location. This triggers the refund path in §6 and the abuse signal in §7.2.

**No-response handling.** If nobody accepts within the timeout, this is a **failure state**, not a feature. It is logged, counted, and worked against.

- Do not hand the customer a list of provider contacts. That gives away the inventory we sell, and once providers notice customers getting numbers free, they stop buying leads.
- Escalate the shortlist, then hand to a human operator who works the phone directly.
- Only as a last resort, after a genuine wait, offer to keep trying or to connect them the following day.

**No-response rate is a primary operational metric.** Above roughly 20% it means a supply-depth problem in that category or quarter, and the answer is recruitment, not a better fallback message.

### 5.3 Post-job follow-up

1. A set interval after assignment, the system asks the customer whether the job was done and how it went.
2. The response feeds the provider's rating and, critically, our own conversion-rate measurement.
3. A failed or disputed job flags for human review. It does not automatically penalise the provider.

This follow-up is not a nice-to-have. It is the only source of ground truth we will ever have about whether the introduction produced work, and the conversion rate it yields is the number the whole business model rests on.

### 5.4 Provider onboarding

Manual, in person, by us. ID verification, evidence of past work, at least two references contacted by phone, trade and coverage areas recorded, WhatsApp number verified. Provider is issued a starter balance of free credits.

Onboarding does not happen through WhatsApp. It happens on foot. This is a deliberate cost we are choosing to pay.

**Collected per provider:** name; WhatsApp number (confirmed by messaging him on the spot); trades and quarters covered (fixed lists); base landmark; rough price range for common jobs; usual availability; MTN MoMo number. Vetting record: ID checked and ID type, two references with whether they were reached and what they said, evidence of past work seen, who vetted and when. Consent to terms and to data storage, with date.

**Record that ID was checked, not the ID number or a photo.** Copies of national IDs are sensitive data we don't need.

**Collection method:** a form feeding the sheet (KoboToolbox, which works offline, or Google Forms), with dropdowns for trade and quarter. Not typing into a spreadsheet in the field.

**Sourcing:** hardware and building-materials shops, the landlords recruited as customers, quarter chiefs, and referrals from vetted providers. A referral earns an interview, not a pass.

### 5.5 Top-up and payment

1. Provider chooses a bundle by replying to a WhatsApp prompt.
2. System issues an MTN MoMo **request-to-pay** to his registered number.
3. MTN prompts him on his handset, outside WhatsApp. He approves with his PIN. We never see or handle his PIN or account details.
4. On MTN's confirmation, one `purchase` row is written to the credit ledger, keyed by the MTN transaction reference, and the provider is told his new balance.
5. When he reaches one remaining credit he is warned, so he never hits zero by surprise.

**Failure handling:**

- Not approved or timed out: status checked with MTN, provider told, nothing written.
- Late confirmation: provider sees a waiting message; a background job polls MTN until a definite outcome. Credits are never added on a guess.
- Duplicate confirmation: rejected by transaction reference. One payment, one ledger row.
- Orange Money: not supported initially. Manual handling during the pilot.

**Phase 0 version:** provider sends money to our MoMo number, we record it in the spreadsheet by hand and text his balance.

### 5.6 Shortlist sizing and ranking (proposed default)

**Sizing: waves.** Offer to two providers; after a short timeout, three more; then all eligible. Most requests fill in wave one and cost two template messages. Width is modulated by urgency (urgent opens wider and times out faster) and by customer trust tier (unknown numbers get a wave of one or two).

**Eligibility (binary filters, no scoring):** correct trade, covers the quarter, marked available, balance ≥ 1, not suspended, not already offered this request.

**Ranking among eligible providers:**

1. Completion rate from customer follow-up — dominates everything else; the only signal tied to the outcome we sell.
2. Responsiveness — historical time to accept.
3. Customer rating.
4. Quarter-level proximity.
5. Recency penalty — a provider who took a lead recently drops, so work spreads.

**Never rank on spend.** It turns the marketplace into an auction providers will detect and resent. **Never let responsiveness outweigh completion** — instant acceptors who finish nothing would otherwise rank highest.

**Cold start:** newly vetted providers are force-included in wave one for their first several requests regardless of score.

**Pilot:** no scorer. A person chooses. Version one sorts on completion rate, then time since last lead. Nothing more until real completion data exists.

---

## 6. Monetisation mechanics

**Model:** pre-paid lead credits. Provider pays before the introduction, not after the job.

**Rules:**

- One credit is consumed per accepted request. Nothing else consumes credits.
- Credits are deducted at acceptance, not at dispatch. A provider is never charged for a request he didn't take.
- Zero balance means the provider is excluded from dispatch. He is warned before this happens.
- **Free credits: free until the provider's first customer-confirmed job, capped at 5.** The moment a customer confirms in follow-up that a job happened, free credits stop and the top-up ask is made the same day. At 30% conversion, roughly 5 in 6 providers land a job within 5 leads, and at pilot volume 5 leads fits inside the pilot window — so willingness to pay is actually measured.
- The trigger is the **customer's** confirmation, never the provider's own claim, since he'd benefit from denying it.
- A provider who exhausts 5 free leads without a job is reviewed by hand. Extra free credits are a judgement call, never automatic.
- **First paid bundle is small** — e.g. 3 credits for 1,500 FCFA. The hardest payment is the first; a small ask gets the real signal.
- Credits do not expire in the pilot. Revisit later.

**Bad-lead refunds.** Refund the credit when the customer turns out not to be real: unreachable number, fake location, nobody there. Do not refund when the customer was real and simply hired someone else, changed her mind, or rejected the price. He bought an introduction and received one.

The boundary is deliberate. Delivering a *real* customer is inside our product; delivering a customer who *hires him* is not. Filtering out fake requests is precisely what the provider is paying for, so a fake lead is a failure to deliver, not bad luck.

Three reasons this policy earns its cost:

- **Economics.** A refund costs 500 FCFA. A churned provider who would have spent 5,000 FCFA a month costs roughly 60,000 FCFA a year plus the fieldwork to replace him. Refund fifty bad leads before that trade turns against us.
- **It is our spam sensor.** Provider reports are the only downstream detection we have of fake requests. They only get filed if reporting is worth the provider's time.
- **It defuses the credit-drain attack.** Without refunds, a rival generating fake requests drains our highest-spending providers for free, and we lose exactly the providers we can least afford to lose. With refunds, the cost lands on the platform, where it is visible and countable.

Guard the policy against abuse in the other direction: track refund rate per provider. A provider claiming 40% bad leads while the cohort reports 5% is not a victim.

**Budget refunds as a spam cost, not a fault admission.** Above roughly 5% of leads, fix the intake filter rather than the policy.

**Indicative pricing:** 500 FCFA per credit, sold in bundles of 10 for 5,000 FCFA. Start here and only raise it once providers are visibly competing to accept requests.

**Economics to hold in view:**

- Provider cost per acquired customer = credit price ÷ conversion rate.
- At 500 FCFA and 30% conversion, that is roughly 1,650 FCFA against a ~20,000 FCFA job. Around 8% of job value. Comfortable.
- At 5% conversion it is 10,000 FCFA against the same job. The model collapses.

Customers are never charged, for anything, at any point.

---

## 7. Trust layer

The referral chain we are replacing provides social accountability, not just information. If we don't replace that too, we are a worse phone book.

### 7.1 Provider trust

- Every provider is personally vetted before activation. No self-service signup.
- Provider identity is verified and on file.
- Every completed job is followed up with the customer.
- Ratings are visible to customers at introduction.
- A dispute route exists and a human handles it.
- Providers can be suspended, and the criteria for suspension are written down before the first suspension, not after.

Curation is the product. Coverage is not.

### 7.2 Customer trust and abuse defence

Customers pay nothing, so the cost of abuse falls on providers. The unit of harm is not a wasted message, it is **a provider spending 500 FCFA on a fake lead**. Every defence below exists to protect provider trust, not to reduce message volume.

The motivated attacker is not a bored teenager. It is a rival tradesman who works out that generating fake requests drains competitors' credit balances. Design against that case.

**Defences, in order of value per unit of build effort:**

1. **Confirmation before dispatch (§5.1).** Never dispatch on a first message from an unknown number. Costs a real customer two seconds; idle traffic does not confirm.
2. **Rate limits per number.** Two open requests at a time, a small daily cap. Trivial to build, ends volume flooding.
3. **Customer trust tiers.** A number with no history gets narrow, slower dispatch — two providers, longer timeout. A number with a completed, confirmed job gets full fast broadcast. This is a reputation ledger for customers, mirroring the one for providers. It is the piece that scales: good customers earn their way up, abusers never get past the cheap tier.
4. **Bad-lead reports (§6).** Downstream detection, run by the people with the strongest incentive to report accurately. A customer number accumulating bad-lead reports is auto-blocked pending review.
5. **Phone identity.** SIM registration means numbers cost something to farm. Not a wall, but a reason WhatsApp beats a web form as intake here.

High-frequency customers climb the trust tiers fastest simply because they use the service often; no special treatment is needed.

### 7.3 Contact release is not a model decision

Provider phone numbers must never enter the model's context window. Prompt instructions are a request, not a control, and someone will eventually phrase the extraction in Pidgin in a way the guardrail wasn't written for.

**Architectural rule:** retrieval passes the model provider IDs, trades, coverage areas and availability. Never numbers, and in the pilot not names either. Contact release is a deterministic code path triggered by the assignment state transition, executed by application logic the model cannot invoke.

The extraction attack is then not refused. It is impossible.

---

## 8. Phase 0: manual pilot

Nothing gets built until this runs.

**Setup:** Ndongo quarter, Buea. 15–25 vetted providers across 3–4 categories, recruited on foot. A plain WhatsApp Business account, not the API. Requests handled manually by two people. A spreadsheet as the database. Duration 3–4 weeks.

**The pilot sheet.** During Phase 0 the spreadsheet is the system. It mirrors the v1 data model (same fields, same fixed lists) so it can be imported by a one-time script when v1 is built. Tabs: providers, requests log (trade, quarter, who was contacted, who accepted, time to accept, follow-up outcome, rating), and ledger (free credits, payments, refunds). The requests and ledger tabs are what produce the four numbers below.

It lives in shared cloud storage (Google Sheets or OneDrive), shared with named accounts only — never by public link — with version history on.

**At v1 the sheet is retired.** Data is imported once; from then on the database is the only source of truth and the operator admin replaces the sheet. The system never reads from a spreadsheet: it cannot lock the acceptance moment, cannot keep the ledger append-only, and would drift from the database. Reporting sheets, if wanted, are read-only exports.

**Name and launch framing.** The product is **FixAm** everywhere. The name is not tied to a quarter, because a quarter name reads as exclusive to that quarter and fights expansion. Ndongo appears in the *launch*, not the brand: "FixAm — now in Ndongo", then "now in Molyko", "now in Bonduma". Each new quarter is an announcement.

**How customers reach us.** One WhatsApp number for customers and providers alike. Customers reach it through a click-to-chat link (`wa.me/…` with a pre-filled first message) and its QR code: stickers in recruited landlords' buildings, quarter and student WhatsApp groups, hardware shops, and a forwardable line at the end of every follow-up. Paid click-to-WhatsApp ads only after the pilot proves the service.

In rented buildings, agree with each landlord whether tenants may request directly or only the landlord does, since the landlord usually pays the tradesman.

**Same number forever.** Get a dedicated SIM now, use it in the WhatsApp Business app for Phase 0, and migrate that same number to the Cloud API for v1. Every sticker printed during the pilot must remain valid. Check Meta's current migration process before the pilot starts.

**Before printing anything:** confirm the WhatsApp display name, domain and social handles for FixAm are available and not already used by another business.

**Demand recruitment:** focus on high-frequency customers — landlords of student rooms, salons, restaurants, hotels, schools. They generate enough weekly requests to produce measurable numbers inside the pilot window.

**Start the long-lead items now, in parallel:** Meta business verification, display name approval and template approval; MTN MoMo production API access. These are paperwork waits of potentially weeks and nothing else on the project can block us that long.

**The four numbers:**

1. **Conversion rate.** Of introductions made, how many became a job that actually happened, verified by calling the customer. This is the number that decides whether the business exists.
2. **Provider willingness to pay.** Does a provider top up with real money after a free lead converted? One real payment is worth more than fifty expressions of interest.
3. **Repeat demand.** Does the same customer come back within 90 days, and how much faster do high-frequency customers return?
4. **Time to acceptance.** How long from request to a provider accepting. If this is hours rather than minutes, the urgent use case is dead and the product is something slower and different.

**Kill conditions:** conversion below roughly 10%, or no provider pays after a converted free lead. Either one means stop, don't build.

---

## 9. Technical implications

Recording these now so architecture is designed against real constraints rather than a clean diagram.

### 9.1 Stack

Scale is tiny — tens of requests a day. Nothing here is performance-constrained. Choices are driven by correctness at the acceptance moment, reliable timers, and how few moving parts two people can operate. Most of these choices are reversible; the ones that aren't are the external approval lead times.

| Layer | Choice | Reason |
|---|---|---|
| Language / framework | Python, FastAPI | Audio and LLM tooling is Python-first, and Pidgin voice handling is the main technical uncertainty. Existing team familiarity. |
| Operator admin | `sqladmin` over SQLAlchemy models | FastAPI provides no admin. Django's admin was considered; it helps with browsing records but not with the dispute/refund workflow, so the gap is smaller than it looks. Decision recorded, not defaulted. |
| Database | PostgreSQL (managed; Supabase acceptable) | Transactions across lock + ledger write. Used as plain Postgres via SQLAlchemy and Alembic. Supabase auth, RLS, PostgREST and client libraries are not used: identity is a Meta-verified phone number and nothing but our backend touches the database. |
| Background jobs | Postgres jobs table with `FOR UPDATE SKIP LOCKED` (or `procrastinate` / `pgqueuer`) | Timers are load-bearing: waves, offer timeouts, follow-ups, MoMo polling. A job and the ledger write it triggers commit together. No separate broker to run. |
| Cache / locks | **None in v1** — Redis dropped | Postgres row locks handle the acceptance race; conversation state is a JSONB column. Add Redis only on a measured need. |
| Channel | WhatsApp Cloud API, direct | No BSP markup on per-message cost. Webhooks acknowledged immediately with 200 and processed asynchronously; handling is idempotent on Meta message ID. |
| Payments | MTN MoMo Collections (request-to-pay) | Prior integration experience. Provider approves on his own handset; no PCI surface. Orange Money later. |
| AI | One model provider behind a single-method interface | Will be swapped. Choice decided by the Pidgin voice test (§9.5). |
| Hosting | Render or Railway: one web process, one worker | Worker is a long-lived polling loop, so not serverless. Hosting in EU is fine — users never connect to our server, Meta does. |
| Errors | Sentry free tier, structured logs | Metrics dashboards only when something hurts. |

Verify MTN's callback semantics (stable references, timeout behaviour) from their current documentation before building reconciliation; this spec describes the shape, not their API.

### 9.2 Entities, first sketch

`provider` — identity, verification status, trades, coverage areas, availability flag, standing, WhatsApp number.
`credit_ledger` — append-only. Every grant, purchase, deduction and refund is a row. Balance is derived, never stored as a mutable field.
`service_request` — customer, trade, area, urgency, description, media, state.
`dispatch` — one row per provider a request was offered to, with offered/accepted/declined/expired outcome. This table is where matching quality gets measured.
`assignment` — the resulting introduction, and the follow-up outcome.
`payment` — MoMo transactions, reconciled against the ledger.
`customer` — phone number, area, request history, derived trust tier.
`job` — background work: kind, payload, `due_at`, attempts, status. Powers waves, timeouts, follow-ups and payment polling.
`message_log` — inbound Meta message IDs for idempotent webhook handling.

### 9.3 State machines

Both the service request and the credit ledger need explicit, enforced state transitions. The dangerous moment is acceptance: two providers tapping Accept within the same second must not both be charged and must not both be assigned.

**Resolved:** a single transaction — `SELECT ... FOR UPDATE` on the request row, check it is still open, insert the ledger debit, write the assignment, commit. The loser is told the request is taken. The lock and the money live in the same database and commit together.

### 9.4 WhatsApp constraints that shape design

**What costs money and what doesn't** (as understood before mid-2026; confirm on Meta's current pricing page):

- Messages a customer sends us: free, regardless of volume.
- Our replies inside the 24-hour window opened by the customer: free or near-free. This covers the entire customer conversation.
- Templates — messages we initiate to someone with no open window: charged per message. In this system that is almost entirely **dispatch notifications to providers**.

So cost per filled request ≈ providers notified before acceptance × Cameroon utility template rate. Compute this against 500 FCFA revenue once the rate is known. It is likely small; if so, narrow waves are justified mainly by provider annoyance and Meta quality rating rather than money.

- Messages to providers outside an open 24-hour window are paid template messages and must be pre-approved. Dispatch notifications will be templates. Template content is therefore near-fixed and cannot be freely generated per request. Design the copy accordingly.
- Meta's pricing has changed repeatedly; current Cameroon rates must be checked directly before we model cost per dispatch.
- Broadcasting to providers who don't want the request drives block rates, which degrades quality rating, which throttles messaging limits. Dispatch shortlist size is a platform-risk decision, not only a UX one.
- Distribution sits entirely with Meta. Note it as a risk, don't design around it yet.

### 9.5 AI scope

Narrow and specific. Intent and entity extraction from customer messages, including voice notes and photos, with heavy code-switching between English, Pidgin and French. That is where the model earns its cost.

Everything else is deterministic: matching, ranking, credit deduction, dispatch, state transitions. The model interprets and phrases. It never decides who gets charged or who gets the job, and per §7.3 it never holds a provider's contact details.

Trade classification across many categories is not the hard part and should not be treated as a differentiator. The bottleneck is having an available provider in the right quarter at the right hour. Category breadth is added only as supply depth allows.

**Voice: an open experiment.** Transcribe-then-parse may fail on Cameroonian Pidgin, and a bad transcript destroys the parse. The alternative is passing audio directly to a multimodal model with the category list in context. Collect ~30 real Buea voice notes during Phase 0 and test both. If neither works, the natural-language premise needs revisiting — better known in week three than month six.

### 9.6 AI cost control

Meta does not charge for chatty customers; **the model provider does**. Every message sent to the model costs money, and passing full history makes each call larger than the last. Controls:

- **Don't send everything to the model.** Greetings, thanks, stickers, emojis and "ok" are handled by rules or ignored.
- **Stop interpreting once a request is confirmed.** Further messages during dispatch get a short fixed reply.
- **Daily model-call cap per number.** Beyond it, a fixed prompt ("Tell me what service you need and your area") until the next day. Real customers never reach it.
- **Short context.** Current request plus a few recent messages, never full history.
- **Cheap first pass.** A small model decides whether a message is a service request; only those go to the stronger model for extraction.

Chatty customers cost model fees and are capped. Fake customers cost providers 500 FCFA and are defended against in §7.2. The second is the dangerous one.

### 9.7 External services and bills

Almost nothing is a subscription. Two fixed monthly bills; everything else scales with use.

| Service | Billing | Note |
|---|---|---|
| WhatsApp Cloud API | Per template message | Needs verified Meta Business account and a number not already on WhatsApp. |
| AI model API | Per use | Controlled by §9.6. |
| Transcription (if separate) | Per use | Only if the voice test chooses it. |
| Hosting (Render / Railway) | Fixed monthly | Web + worker. |
| Postgres + object storage | Free tier, then fixed monthly | Move to paid for backups once real money is in the ledger. |
| MTN MoMo | Fee per collection | A percentage fee hurts small bundles; keep small bundles for the first purchase only. Requires a registered business. |
| Sentry | Free tier | |
| Domain + simple site | Annual | Needed for Meta verification and a privacy policy page. |

**Phase 0 costs:** a dedicated SIM, the free WhatsApp Business app, an existing MoMo account, a spreadsheet.

**Check before committing:** Meta's Cameroon utility template rate and MTN's collection fee. Those two numbers shape margin more than anything else.

The largest real cost is not any service: it is fieldwork hours for recruiting and vetting, and operator time for disputes.

### 9.8 Location

No street addressing. Quarter-level areas plus landmarks, entered as structured values, not free text. Do not build GPS radius matching. "Opposite Checkpoint junction" is more useful to both parties than "350m away."

---

## 10. Open technical decisions

To resolve in the architecture session, in rough priority order:

1. **Dispatch shape.** *Proposed default:* waves (§5.6). Wave sizes and timeouts to be tuned from pilot data.
2. **Ranking inputs.** *Proposed default:* §5.6, with cold-start override. Pilot uses manual choice.
3. ~~Concurrency guarantee on acceptance.~~ **Resolved** — §9.3.
4. ~~Where conversation state lives.~~ **Resolved** — JSONB on the request; model sees current request plus a few recent messages (§9.6).
5. **MoMo reconciliation.** Failure modes, partial payments, manual correction path.
6. **Operator tooling.** However minimal, a human will be handling disputes, refunds and failed dispatches from week one. Decide what they use.
7. **Customer trust tiering.** What promotes a number to full dispatch, what demotes it, and whether tier is stored or derived from request history.
8. **Bad-lead report window and adjudication.** How long the provider has, what evidence if any, and which reports auto-refund versus queue for a human.

---

## 11. Principal risks

- **Conversion rate too low.** Kills the model outright. Phase 0 measures it.
- **Adverse selection on supply.** Good providers are already busy; the available ones may be available for a reason. Vetting is the only defence.
- **Frequency.** Households don't need us often enough. Mitigated by the B2B wedge and category breadth, not eliminated.
- **Trust failure.** One provider who steals a deposit, in a town this size, damages the brand faster than any marketing repairs it.
- **Credit-drain attack.** A rival generating fake requests to burn competitors' balances. Costs him nothing, hits our highest spenders hardest. Refunds and trust tiers are the defence; the residual risk is reputational damage among providers before we detect it.
- **Breadth outrunning depth.** Many categories spread thin produces a system that classifies the problem accurately and then fails to solve it. Every request falls to no-response and the product is worse than asking a neighbour.
- **Meta platform dependency.** Channel can be throttled or revoked.
- **Ops linearity.** Vetting and dispute handling don't scale with software. This may be a good cash business rather than a venture-scale one. Worth deciding which we're building before pitching it as either.
