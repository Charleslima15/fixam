"""Service-request state machine enforcement (§4.1)."""
from __future__ import annotations

from fixam.models.enums import RequestState

_VALID: dict[RequestState, set[RequestState]] = {
    RequestState.collecting: {
        RequestState.awaiting_confirmation,
        RequestState.expired,
        RequestState.cancelled,
    },
    RequestState.awaiting_confirmation: {
        RequestState.dispatching,
        RequestState.expired,
        RequestState.cancelled,
    },
    RequestState.dispatching: {
        RequestState.assigned,
        RequestState.unfilled,
        RequestState.cancelled,
    },
    RequestState.assigned: {
        RequestState.followed_up,
    },
    RequestState.followed_up: {
        RequestState.closed,
    },
    RequestState.unfilled: {
        RequestState.assigned,
        RequestState.closed,
    },
    RequestState.expired: set(),
    RequestState.cancelled: set(),
    RequestState.closed: set(),
}

OPEN_STATES = {
    RequestState.collecting,
    RequestState.awaiting_confirmation,
    RequestState.dispatching,
    RequestState.assigned,
}

CANCELABLE_STATES = {
    RequestState.collecting,
    RequestState.awaiting_confirmation,
    RequestState.dispatching,
}


class InvalidTransition(Exception):
    def __init__(self, from_state: RequestState, to_state: RequestState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}")


def transition(current: RequestState, target: RequestState) -> RequestState:
    """Validate and return the target state, or raise InvalidTransition."""
    allowed = _VALID.get(current, set())
    if target not in allowed:
        raise InvalidTransition(current, target)
    return target
