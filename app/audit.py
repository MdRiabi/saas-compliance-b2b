from datetime import datetime, timezone

from app import db
from app.models import AuditLog


AUDIT_RESULTS = frozenset({"success", "failure", "partial"})


def add_audit_event(
    *,
    tenant_id,
    actor_email,
    action,
    result="success",
    resource_type=None,
    resource_id=None,
):
    if result not in AUDIT_RESULTS:
        raise ValueError("Invalid audit event result.")
    if not isinstance(action, str) or not action or len(action) > 255:
        raise ValueError("Audit event action must contain 1 to 255 characters.")

    event = AuditLog(
        tenant_id=tenant_id,
        user_email=actor_email,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id)[:128] if resource_id is not None else None,
        result=result,
        timestamp=datetime.now(timezone.utc),
    )
    db.session.add(event)
    return event
