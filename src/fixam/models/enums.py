import enum


class RequestState(str, enum.Enum):
    collecting = "collecting"
    awaiting_confirmation = "awaiting_confirmation"
    dispatching = "dispatching"
    assigned = "assigned"
    followed_up = "followed_up"
    closed = "closed"
    expired = "expired"
    unfilled = "unfilled"
    cancelled = "cancelled"


class OfferState(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"
    withdrawn = "withdrawn"
    failed = "failed"


class PaymentState(str, enum.Enum):
    initiated = "initiated"
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    stuck = "stuck"


class LedgerKind(str, enum.Enum):
    grant_free = "grant_free"
    purchase = "purchase"
    debit_accept = "debit_accept"
    refund_bad_lead = "refund_bad_lead"
    adjustment = "adjustment"


class Urgency(str, enum.Enum):
    now = "now"
    today = "today"
    this_week = "this_week"
    unknown = "unknown"


class TrustTier(str, enum.Enum):
    new = "new"
    established = "established"
    blocked = "blocked"


class JobState(str, enum.Enum):
    pending = "pending"
    claimed = "claimed"
    succeeded = "succeeded"
    failed = "failed"
    dead = "dead"


class FollowupOutcome(str, enum.Enum):
    yes = "yes"
    no = "no"
    still_waiting = "still_waiting"
    no_response = "no_response"


class BadLeadReason(str, enum.Enum):
    number_unreachable = "number_unreachable"
    nobody_at_location = "nobody_at_location"
    customer_denied = "customer_denied"


class BadLeadStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    denied = "denied"
