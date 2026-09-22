# FixAm — Technical Requirements v0.1

**Derived from:** Product Definition v0.3
**Applies to:** v1 build, started after Phase 0 passes its kill conditions
**Status:** Draft for review

Requirements use **MUST** for things the system cannot ship without, **SHOULD** for strong defaults that can be deferred with a reason, and **MAY** for optional. Each has an ID so tickets, tests and code can point at it.

---

## 1. Scope of v1

**v1 does:** customer intake over WhatsApp (text, voice, photo), AI extraction, confirmation, wave dispatch to providers, atomic acceptance with credit deduction and contact release, provider top-up via MTN MoMo, post-job follow-up, bad-lead refunds, abuse controls, and an operator admin.

**v1 does not:** job payments, scheduling, quotes, a customer app, a provider dashboard, Orange Money, multi-city, GPS matching, Redis. See Product Definition §4.

**Scale assumption:** under 200 providers, under 200 requests per day. Requirements are written for correctness and operability, not throughput.

---

## 2. System context

**Actors**

| Actor | Channel | Identity |
|---|---|---|
| Customer | WhatsApp | Phone number (Meta-verified) |
| Provider | WhatsApp | Phone number, linked to a vetted provider record |
| Operator | Web admin | Username + password + 2FA |

**External systems**

| System | Direction | Purpose |
|---|---|---|
| WhatsApp Cloud API | In (webhooks) and out (send API) | All customer and provider messaging |
| AI model provider | Out | Intent extraction, voice handling, reply phrasing |
| MTN MoMo Collections | Out (request-to-pay, status) and in (callbacks) | Provider top-ups |
| Object storage | Out | Voice notes and photos |
| Sentry | Out | Error reporting |

**Processes:** one web process (webhooks, admin, MoMo callbacks) and one worker process (jobs). One PostgreSQL database.

---

## 3. Functional requirements

### 3.1 Inbound messaging (FR-MSG)

- **FR-MSG-01** MUST verify the signature on every Meta webhook and reject unsigned or mis-signed payloads.
- **FR-MSG-02** MUST respond 200 to Meta before doing any processing. All processing happens after the message is persisted.
- **FR-MSG-03** MUST persist each inbound message with its Meta message ID under a unique constraint. A redelivered message MUST be a no-op.
- **FR-MSG-04** MUST route each message by sender: registered provider number → provider handler; any other number → customer handler.
- **FR-MSG-05** MUST download voice notes and photos from Meta promptly (Meta media URLs expire) and store them in object storage, referenced from the message record.
- **FR-MSG-06** MUST handle message types it doesn't support (location, contacts, documents, stickers) with a fixed reply, never a crash or silence.
- **FR-MSG-07** MUST record delivery status webhooks (sent, delivered, read, failed) against outbound messages. Failed template sends feed the dispatch logic (FR-DSP-09).

### 3.2 Outbound messaging (FR-OUT)

- **FR-OUT-01** All outbound messages MUST go through one sending module that decides free-form vs template based on whether a 24-hour window is open for that recipient.
- **FR-OUT-02** The system MUST track, per phone number, the time of the last inbound message, to determine window state.
- **FR-OUT-03** Every outbound message MUST be logged with recipient, type (free-form or template name), related request ID, and Meta message ID.
- **FR-OUT-04** Outbound sends MUST be issued from the worker via jobs, not inline in webhook handling, so failures retry without losing state.
- **FR-OUT-05** Customer-facing and provider-facing copy MUST exist in English. Pidgin and French SHOULD be supported for fixed replies; language is chosen from the customer's own messages.

### 3.3 Customer intake and conversation (FR-INT)

- **FR-INT-01** A customer record MUST be created on first contact, keyed by phone number.
- **FR-INT-02** The system MUST maintain at most one *open* request per conversation. Conversation state is stored as JSONB on the request.
- **FR-INT-03** The system MUST extract trade, area, urgency and a problem description (FR-AI). If trade or area is missing, it MUST ask **one** clarifying question at a time.
- **FR-INT-04** Area MUST resolve to a value from the fixed quarter list. A customer's last confirmed area SHOULD be offered as the default on their next request.
- **FR-INT-05** Before dispatch, the system MUST state back its understanding and require explicit confirmation (quick-reply button). No dispatch without confirmation.
- **FR-INT-06** Unconfirmed requests MUST expire after a set period and be closed.
- **FR-INT-07** After confirmation, further customer messages about that request MUST receive a short fixed status reply and MUST NOT be sent to the model (see FR-AI-06).
- **FR-INT-08** If a trade isn't served, or no provider covers the area, the system MUST say so plainly rather than dispatch to nobody.
- **FR-INT-09** Requests for provider lists or contacts MUST be redirected with the fixed copy from Product Definition §5.1.

### 3.4 AI extraction (FR-AI)

- **FR-AI-01** All model calls MUST go through a single interface with one method: message(s) in, structured result out. The provider behind it MUST be swappable by configuration.
- **FR-AI-02** Extraction MUST return JSON validated against a schema: `is_service_request`, `trade` (from the fixed category list or null), `area` (from the quarter list or null), `urgency` (now / today / this week / unknown), `description`, `language`, `confidence`. Invalid output MUST be retried once, then treated as unclear.
- **FR-AI-03** The model MUST NOT receive provider phone numbers or names, ever. Its inputs are the customer's messages, the category list, the quarter list, and at most a short recent history.
- **FR-AI-04** The model MUST NOT trigger any state change directly. Its output is data that deterministic code acts on.
- **FR-AI-05** Voice notes MUST be supported. The implementation (transcribe-then-parse vs direct audio) is decided by the Phase 0 test and hidden behind FR-AI-01.
- **FR-AI-06 (cost control)** The system MUST NOT call the model for: greetings, thanks, emoji- or sticker-only messages, "ok"-type acknowledgements (handled by rules); or any message on an already-confirmed request.
- **FR-AI-07** Each phone number MUST have a daily cap on model calls. Beyond the cap, a fixed prompt is sent and no model call is made until the next day.
- **FR-AI-08** Context passed to the model MUST be bounded: the current request's messages plus at most a few earlier ones.
- **FR-AI-09** The system SHOULD use a cheaper model for the is-this-a-service-request pass and the stronger model only for full extraction.
- **FR-AI-10** Every model call MUST be logged with input size, output, latency, cost estimate and request ID, so cost per filled request can be computed.

### 3.5 Abuse controls (FR-ABU)

- **FR-ABU-01** A number MUST NOT have more than 2 open requests at once, and MUST be capped on requests per day.
- **FR-ABU-02** Each customer MUST have a trust tier derived from history: **new** (no confirmed job), **established** (at least one confirmed job), **blocked**. Tier is computed, not hand-set, except for operator blocks and unblocks.
- **FR-ABU-03** Tier MUST drive dispatch width and timeouts (FR-DSP-03).
- **FR-ABU-04** A customer accumulating bad-lead reports past a threshold MUST be auto-blocked pending operator review. Blocked customers receive a neutral fixed reply and are never dispatched.
- **FR-ABU-05** All thresholds MUST be configuration, not constants in code.

### 3.6 Matching and dispatch (FR-DSP)

- **FR-DSP-01** Eligibility MUST be a query, not a score: provider active and not suspended, offers the trade, covers the quarter, marked available, balance ≥ 1, not already offered this request.
- **FR-DSP-02** Eligible providers MUST be ranked by the ordered rules in Product Definition §5.6. v1 ranking: completion rate, then time since last lead. The ranking function MUST be isolated so it can change without touching dispatch.
- **FR-DSP-03** Dispatch MUST proceed in waves. Wave sizes and timeouts MUST be configuration, varied by urgency and customer tier. Default: 2, then 3, then all remaining.
- **FR-DSP-04** New providers MUST be force-included in wave one for their first N offers (configurable), regardless of rank.
- **FR-DSP-05** Each offer MUST be a row in `offer` with state (see §4.2). Offers MUST be sent as an approved template with Accept and Decline quick-reply buttons carrying the offer ID.
- **FR-DSP-06** Offer content MUST include trade, quarter, urgency and a short description. It MUST NOT include the customer's name or number.
- **FR-DSP-07** Advancing to the next wave MUST be driven by a scheduled job, not a sleep in a request handler.
- **FR-DSP-08** When all waves are exhausted without acceptance, the request MUST move to `unfilled`, appear in the operator queue, and the customer MUST be told a person is handling it. The system MUST NOT send the customer any provider contacts.
- **FR-DSP-09** A failed template delivery to a provider MUST count as a non-response and MUST NOT block the wave.
- **FR-DSP-10** A provider tapping Accept on an offer that is expired, withdrawn, or already taken MUST receive a clear "already taken" reply and MUST NOT be charged.

### 3.7 Acceptance and contact release (FR-ACC)

- **FR-ACC-01** Acceptance MUST be one database transaction that: locks the request row (`SELECT ... FOR UPDATE`); verifies the request is `dispatching` and the offer is `sent`; verifies provider balance ≥ 1; inserts the ledger debit; creates the assignment; marks the offer `accepted` and all other open offers `withdrawn`; moves the request to `assigned`. Any failed check aborts the whole transaction.
- **FR-ACC-02** Two simultaneous accepts on the same request MUST result in exactly one assignment and exactly one debit. This MUST be covered by an automated concurrency test.
- **FR-ACC-03** Contact release MUST happen only after the transaction commits, via jobs: provider receives customer name, number, quarter, landmark and description; customer receives provider name, number, trade and rating.
- **FR-ACC-04** Contact release MUST be implemented as deterministic code keyed on the `assigned` transition. No other path may send contact details.
- **FR-ACC-05** Withdrawn offers MUST trigger a short "this job was taken" notice to those providers.

### 3.8 Credit ledger (FR-LED)

- **FR-LED-01** The ledger MUST be append-only. No UPDATE or DELETE on ledger rows, enforced at the database level (permissions or trigger).
- **FR-LED-02** Entry kinds: `grant_free`, `purchase`, `debit_accept`, `refund_bad_lead`, `adjustment`. Each row: provider, kind, amount (signed integer credits), reference (offer, payment, or operator action), actor, timestamp, note.
- **FR-LED-03** Balance MUST be derived as the sum of the provider's entries. A cached balance MAY exist only if it is updated in the same transaction as the entry and verified by a reconciliation job.
- **FR-LED-04** Balance MUST never go below zero. Enforced inside the acceptance transaction.
- **FR-LED-05** `adjustment` entries MUST require an operator, a reason, and appear in the audit log.
- **FR-LED-06** A reconciliation job MUST run daily comparing cached balances (if any) with derived sums and payments with purchase entries, and alert on any mismatch.

### 3.9 Free credits (FR-FRE)

- **FR-FRE-01** On activation, a provider MUST receive a `grant_free` of the configured cap (default 5).
- **FR-FRE-02** When a customer confirms a completed job for a provider who has never had one, any remaining free credits MUST be removed via a negative `adjustment` with reason "first job confirmed", and a top-up prompt MUST be sent that day.
- **FR-FRE-03** The trigger MUST be the customer's follow-up confirmation. A provider's own statement MUST NOT trigger or prevent it.
- **FR-FRE-04** Providers who exhaust free credits with no confirmed job MUST appear in an operator review list.

### 3.10 Payments (FR-PAY)

- **FR-PAY-01** Bundles MUST be configuration (credits, price, whether first-purchase-only). Defaults: 3 for 1,500 FCFA (first purchase only), 10 for 5,000 FCFA.
- **FR-PAY-02** A top-up MUST create a `payment` record in `initiated` state with our own reference *before* calling MTN's request-to-pay.
- **FR-PAY-03** The provider's MoMo number MUST default to his registered number. He MAY supply another MTN number for that payment.
- **FR-PAY-04** MTN callbacks MUST be authenticated per MTN's scheme and processed idempotently on MTN's transaction reference.
- **FR-PAY-05** A polling job MUST query payment status until a terminal state for any payment not confirmed by callback within a set time.
- **FR-PAY-06** Credits MUST be written only on a confirmed successful state from MTN, in the same transaction that moves the payment to `succeeded`. Never on a pending or unknown state.
- **FR-PAY-07** A duplicate success for an already-`succeeded` payment MUST be a no-op.
- **FR-PAY-08** Payments stuck non-terminal beyond a threshold MUST surface in the operator queue.
- **FR-PAY-09** Our payment reference, MTN's reference, amount, currency, and raw callback payloads MUST be stored for dispute resolution.

### 3.11 Provider commands (FR-PRV)

Providers interact by buttons and short commands. No model is needed on the provider side in v1; unrecognised provider text receives the command list.

- **FR-PRV-01** `AVAILABLE` / `OFF` toggles availability. Current state MUST be confirmed back.
- **FR-PRV-02** `BALANCE` returns current credits and free-credit status.
- **FR-PRV-03** `TOP UP` starts the payment flow (FR-PAY).
- **FR-PRV-04** A low-balance warning MUST be sent when balance reaches 1.
- **FR-PRV-05** After accepting, the provider MUST have a "Report bad lead" button, valid for a configured window (FR-REF).
- **FR-PRV-06** A provider SHOULD be automatically set `OFF` after a configurable number of consecutive unanswered offers, with a message telling him how to turn back on. This protects dispatch speed and his own experience.

### 3.12 Follow-up and ratings (FR-FUP)

- **FR-FUP-01** A follow-up job MUST be scheduled on assignment, at a configurable delay per urgency.
- **FR-FUP-02** Follow-up asks: did the job happen (yes / no / still waiting), and if yes, a 1–5 rating. Buttons, not free text.
- **FR-FUP-03** If the follow-up falls outside the customer's 24-hour window, it MUST be sent as an approved utility template.
- **FR-FUP-04** "No" MUST prompt one follow-up question (provider didn't come / didn't agree on price / other) and create an operator review item for "didn't come". It MUST NOT automatically penalise the provider.
- **FR-FUP-05** Unanswered follow-ups MUST be retried once, then recorded as `no_response`. No-response outcomes MUST be excluded from, not counted against, completion rate.
- **FR-FUP-06** Completion rate per provider = confirmed jobs ÷ assignments with a known outcome. Rating = mean of ratings received. Both MUST be computed from assignment records, not stored as editable fields.

### 3.13 Bad-lead reports and refunds (FR-REF)

- **FR-REF-01** A provider MAY report a bad lead within the configured window after assignment, selecting a reason: number unreachable, nobody at location, customer denied requesting.
- **FR-REF-02** Reports MUST be auto-approved when the customer is in the `new` tier and the provider's historical refund rate is under a threshold; otherwise queued for operator decision.
- **FR-REF-03** An approved report MUST write `refund_bad_lead` referencing the assignment, and MUST count against the customer (FR-ABU-04).
- **FR-REF-04** Reasons "customer hired someone else" or "price disagreement" MUST NOT be offered and MUST NOT be refundable.
- **FR-REF-05** Refund rate per provider MUST be computed and shown to operators, with outliers flagged.
- **FR-REF-06** At most one report per assignment.

### 3.14 Operator admin (FR-OPS)

- **FR-OPS-01** Web admin with individual operator accounts, 2FA, and no shared logins.
- **FR-OPS-02** Providers: create (from vetting), activate, suspend with reason, edit trades and quarters, view offers, assignments, ledger, completion rate, refund rate.
- **FR-OPS-03** Customers: view requests and tier, block and unblock with reason.
- **FR-OPS-04** Queues: unfilled requests, pending bad-lead reports, "provider didn't come" follow-ups, stuck payments, providers who exhausted free credits without a job.
- **FR-OPS-05** For an unfilled request, an operator MUST be able to assign a provider manually. Manual assignment MUST use the same acceptance transaction (FR-ACC-01), including the debit, unless the operator explicitly marks it as a free assignment with a reason.
- **FR-OPS-06** Operators MUST be able to read a request's full message thread, including media.
- **FR-OPS-07** Every operator action that changes state or money MUST write an audit log row: operator, action, target, before/after, reason, time.

---

## 4. State machines

Transitions not listed are invalid and MUST be rejected by code.

### 4.1 Service request

```
collecting ──► awaiting_confirmation ──► dispatching ──► assigned ──► followed_up ──► closed
     │                  │                    │               │
     └──► expired ◄─────┘                    └──► unfilled ──┤ (operator assigns → assigned)
                                                             └──► closed (operator closes)
     any open state ──► cancelled (customer cancels, before assigned)
```

### 4.2 Offer

```
queued ──► sent ──► accepted
             ├────► declined
             ├────► expired      (wave timeout)
             ├────► withdrawn    (another provider accepted, or request cancelled)
             └────► failed       (template delivery failed)
```

### 4.3 Payment

```
initiated ──► pending ──► succeeded   (credits written in the same transaction)
                  ├─────► failed
                  └─────► stuck ──► succeeded / failed   (operator or late poll)
```

---

## 5. Data model requirements

Core tables: `provider`, `provider_trade`, `provider_area`, `customer`, `service_request`, `offer`, `assignment`, `credit_ledger`, `payment`, `message` (inbound and outbound), `media`, `job`, `followup`, `bad_lead_report`, `operator`, `audit_log`, `config`.

Key constraints the schema MUST enforce, not just the code:

- `message.meta_message_id` unique.
- `payment.mtn_reference` unique where not null; `payment.our_reference` unique.
- One `assignment` per `service_request` (unique on request ID).
- One `bad_lead_report` per `assignment`.
- `offer` unique on (request, provider).
- `credit_ledger` insert-only.
- State columns constrained to the values in §4.
- Trades and quarters are reference tables, not free text.

Money is stored as integer FCFA. Credits as integers. Timestamps in UTC; displayed in Africa/Douala.

---

## 6. Non-functional requirements

### 6.1 Correctness and consistency

- **NFR-COR-01** Any operation touching credits MUST be a single database transaction.
- **NFR-COR-02** Every external callback and webhook handler MUST be idempotent.
- **NFR-COR-03** Jobs MUST be safe to run twice. Workers claim jobs with `FOR UPDATE SKIP LOCKED`.
- **NFR-COR-04** Jobs MUST retry with backoff and move to a dead state after a limit, visible to operators.

### 6.2 Latency targets

| Path | Target |
|---|---|
| Webhook acknowledgement to Meta | under 1 second |
| First reply to a customer message (non-model) | under 5 seconds |
| First reply involving a model call | under 15 seconds, with a holding message if longer |
| Confirmation → first wave sent | under 30 seconds |
| Accept tap → both parties receive contacts | under 30 seconds |

These are targets, not SLAs. The one that matters commercially is time from confirmation to a named provider.

### 6.3 Reliability

- **NFR-REL-01** If the worker is down, webhooks MUST still be received and persisted; work resumes on restart with no loss.
- **NFR-REL-02** If the AI provider is unavailable, the customer MUST receive a fixed "tell me the service and your area" reply and the conversation continues with button-driven intake. The model is not a single point of failure.
- **NFR-REL-03** If MTN is unavailable, top-ups fail cleanly with a message. Dispatch is unaffected.
- **NFR-REL-04** Daily automated database backups with point-in-time recovery once real money is in the ledger. A restore MUST be tested before launch.

### 6.4 Security and privacy

- **NFR-SEC-01** Secrets (Meta tokens, MTN keys, model API keys) in environment configuration, never in the repository.
- **NFR-SEC-02** Phone numbers, names and messages are personal data. Access to them is limited to the backend and authenticated operators.
- **NFR-SEC-03** Media MUST be stored privately and served to operators via short-lived signed URLs.
- **NFR-SEC-04** A retention period MUST be defined for messages and media, with automatic deletion after it.
- **NFR-SEC-05** A privacy policy page is required (also needed for Meta verification). Cameroon's personal data protection obligations MUST be checked with someone qualified before launch; this document does not establish compliance.
- **NFR-SEC-06** Provider and customer contact details MUST NOT appear in logs, Sentry events, or model inputs.

### 6.5 Cost controls

- **NFR-CST-01** Model spend per day MUST be tracked, with an alert above a threshold.
- **NFR-CST-02** Template sends per day MUST be tracked, with an alert above a threshold.
- **NFR-CST-03** Cost per filled request (template + model) MUST be computable from logs.

### 6.6 Operability

- **NFR-OPS-01** Every threshold, wave size, timeout, cap, and price MUST be editable in the `config` table without a deploy.
- **NFR-OPS-02** Structured logs with request ID on every line touching a request.
- **NFR-OPS-03** Errors reported to Sentry with PII scrubbed.

---

## 7. Metrics the system MUST produce

These are the numbers the business runs on. They MUST be queryable from the database, and SHOULD be shown on a simple admin page.

| Metric | Definition |
|---|---|
| Conversion rate | Confirmed jobs ÷ assignments with known outcome |
| No-response rate | `unfilled` requests ÷ dispatched requests, by trade and quarter |
| Time to acceptance | Confirmation → accept, median and 90th percentile |
| Wave depth | Share of requests filled in wave 1, 2, 3 |
| Provider willingness to pay | Providers who purchased after first confirmed job ÷ providers who had one |
| Refund rate | Refunds ÷ assignments, overall and per provider |
| Repeat demand | Customers with a second request within 90 days |
| Cost per filled request | Template + model cost ÷ assigned requests |
| Revenue | Sum of succeeded payments, by week |

---

## 8. WhatsApp templates to submit for approval

Submit early; approval is a lead time.

| Template | Category | Recipient | Buttons |
|---|---|---|---|
| Job offer | Utility | Provider | Accept / Decline |
| Job taken | Utility | Provider | — |
| Low balance | Utility | Provider | Top up |
| Free credits ended — top up | Utility | Provider | Bundle options |
| Payment confirmed | Utility | Provider | — |
| Job follow-up | Utility | Customer | Yes / No / Still waiting |
| Rating request | Utility | Customer | 1–5 |
| Request update (unfilled, operator handling) | Utility | Customer | — |

Keep copy transactional. Anything promotional risks the marketing category, higher cost, and more blocks.

---

## 9. Acceptance scenarios

v1 is not done until these pass, most as automated tests:

1. Customer sends a Pidgin voice note, confirms, provider accepts in wave 1, both receive contacts. (End-to-end, manual on real devices.)
2. Two providers accept the same request concurrently: exactly one assignment, one debit, the other told "taken". (Automated.)
3. Meta redelivers the same webhook three times: one message record, one reply. (Automated.)
4. MTN sends a success callback twice: one purchase entry. (Automated.)
5. MTN never calls back: polling resolves the payment; credits appear only after confirmed success. (Automated.)
6. No provider accepts: request reaches `unfilled`, appears in operator queue, customer receives no contacts. (Automated.)
7. Customer asks for "all plumbers' numbers": redirected; model logs show no provider data in context. (Automated.)
8. A number sends 60 messages in an hour: model calls stop at the cap; replies continue. (Automated.)
9. First confirmed job: remaining free credits removed, top-up prompt sent. (Automated.)
10. Bad-lead report from a low-refund provider against a new customer: auto-refunded, counted against the customer. (Automated.)
11. Worker stopped for 10 minutes during dispatch: on restart, waves resume and no offer is sent twice. (Manual.)
12. AI provider unavailable: intake falls back to buttons, request still completes. (Automated with provider mocked down.)

---

## 10. Open items

1. **Wave sizes and timeouts** — defaults set; tune from pilot data.
2. **Availability decay** — should `AVAILABLE` expire automatically (e.g. end of day)? Trade-off between fresher data and provider annoyance.
3. **Follow-up delay** per urgency.
4. **Bad-lead report window** length.
5. **Retention period** for messages and media.
6. **Voice approach** — decided by the Phase 0 test.
7. **Model provider** — decided by the same test.
8. **Data protection review** — who, and when before launch.
