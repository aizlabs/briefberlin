"""Host adapter hook. Call only from a transport-authenticated event handler."""

import hmac
from collections.abc import Callable
from dataclasses import dataclass

from .review import ACTIONS, callback_bytes, callback_key, identity


@dataclass(frozen=True)
class Control:
    request_id: str
    story_id: str
    version: int
    verb: str
    rating: int | None = None


def signed_event(*, metadata: dict, event_id: str, message_id: str, control_id: str,
                 lookup_control: Callable[[str, str, str, str, str], Control | None],
                 note: str = "") -> dict:
    """Resolve an opaque delivered control in the host outbox, then sign its stored decision."""
    identity(metadata)
    if not all(isinstance(x, str) and 1 <= len(x.strip()) <= 512 for x in (event_id, message_id, control_id)):
        raise ValueError("authenticated event, message and control identifiers required")
    control = lookup_control(metadata["transport"], metadata["account"], metadata["conversation"],
                             message_id, control_id)
    if control is None or control.verb not in ACTIONS:
        raise ValueError("unknown delivered review control")
    payload = dict(metadata=dict(metadata), event_id=event_id, request_id=control.request_id,
                   story_id=control.story_id, version=control.version, verb=control.verb,
                   rating=control.rating, note=note)
    signature = hmac.digest(callback_key(), callback_bytes(payload), "sha256").hex()
    return {"payload": payload, "signature": signature}
