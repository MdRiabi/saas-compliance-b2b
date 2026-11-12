from datetime import datetime, timezone

from app import db
from app.audit import add_audit_event
from app.models import AuditLog
from app.utils_aws import upload_audit_report_to_s3


_EXPORT_ACTION = "audit.export"


def _tenant_query(tenant_id):
    query = AuditLog.query
    if tenant_id is None:
        return query.filter(AuditLog.tenant_id.is_(None))
    return query.filter(AuditLog.tenant_id == tenant_id)


def _timestamp_text(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _serialize_event(event):
    return {
        "id": event.id,
        "timestamp_utc": _timestamp_text(event.timestamp),
        "tenant_id": event.tenant_id,
        "actor": event.user_email,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "result": event.result,
    }


def export_pending_audit_logs():
    tenant_ids = [
        row[0]
        for row in db.session.query(AuditLog.tenant_id).distinct().order_by(
            AuditLog.tenant_id
        )
    ]
    outcomes = []
    for tenant_id in tenant_ids:
        tenant_events = _tenant_query(tenant_id)
        previous_export = (
            tenant_events.filter_by(action=_EXPORT_ACTION, result="success")
            .order_by(AuditLog.id.desc())
            .first()
        )
        try:
            cursor = int(previous_export.resource_id) if previous_export else 0
        except (TypeError, ValueError) as error:
            raise RuntimeError("The audit export cursor is invalid.") from error

        pending_events = tenant_events.filter(AuditLog.id > cursor).order_by(AuditLog.id)
        high_watermark = pending_events.with_entities(db.func.max(AuditLog.id)).scalar()
        if high_watermark is None:
            continue
        events = pending_events.filter(AuditLog.id <= high_watermark).all()
        payload = {
            "tenant_id": tenant_id,
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "records": [_serialize_event(event) for event in events],
        }
        result = upload_audit_report_to_s3(
            tenant_id,
            "audit_log_batch",
            payload,
        )
        add_audit_event(
            tenant_id=tenant_id,
            actor_email="system:audit-export",
            action=_EXPORT_ACTION,
            result="success" if result.uploaded else "failure",
            resource_type="audit_log_batch",
            resource_id=high_watermark if result.uploaded else None,
        )
        db.session.commit()
        outcomes.append(
            {
                "tenant_id": tenant_id,
                "record_count": len(events),
                "uploaded": result.uploaded,
                "local_path": result.local_path,
                "s3_uri": result.s3_uri,
                "error": result.error,
            }
        )
    return outcomes
