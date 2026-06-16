"""Request state machine + alert lifecycle definitions.

Centralising allowed transitions prevents illegal state jumps from any caller.
"""
from fastapi import HTTPException

# ---------- Request transitions ----------
# Maps current_state -> set of allowed next states.
# 'auto' transitions happen inside business endpoints (e.g. receive auto-closes).
REQUEST_TRANSITIONS = {
    "pending_approval": {"approved", "rejected"},
    "approved":         {"dispatched", "backorder", "cancelled"},
    "backorder":        {"dispatched", "cancelled"},
    "dispatched":       {"partially_received", "received"},
    "partially_received": {"partially_received", "received"},
    "received":         {"closed"},          # auto-closed on full receipt
    "closed":           set(),
    "rejected":         set(),
    "cancelled":        set(),
}


def validate_request_transition(current: str, target: str) -> None:
    """Raise HTTP 409 if `target` is not a legal next state from `current`."""
    allowed = REQUEST_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Illegal state transition: '{current}' -> '{target}'. "
                   f"Allowed: {sorted(allowed) or 'none (terminal state)'}",
        )


# ---------- Alert lifecycle ----------
ALERT_TRANSITIONS = {
    "open":         {"acknowledged", "in_progress", "resolved"},
    "acknowledged": {"in_progress", "resolved"},
    "in_progress":  {"resolved"},
    "resolved":     {"closed"},
    "closed":       set(),
}


def validate_alert_transition(current: str, target: str) -> None:
    allowed = ALERT_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Illegal alert transition: '{current}' -> '{target}'. "
                   f"Allowed: {sorted(allowed) or 'none (terminal)'}",
        )
