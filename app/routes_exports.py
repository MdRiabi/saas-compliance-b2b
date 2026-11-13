import json

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.audit import add_audit_event
from app.auth import WRITE_ROLES
from app.pdf_export import render_html_pdf
from app.utils_aws import upload_generated_export


exports_bp = Blueprint("exports", __name__, url_prefix="/exports")
MAX_EXPORT_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
AUDIT_ROLES = frozenset({"admin", "compliance", "auditor"})
EXPORT_SPECS = {
    ("audit", "json"): ("rgpd_audit_browser_json", "content", AUDIT_ROLES),
    ("audit", "csv"): ("rgpd_audit_browser_csv", "content", AUDIT_ROLES),
    ("audit", "pdf"): ("rgpd_audit_browser_pdf", "html", AUDIT_ROLES),
    ("policies", "json"): ("policy_pack_browser_json", "content", WRITE_ROLES),
    ("policies", "csv"): ("policy_pack_browser_csv", "content", WRITE_ROLES),
    ("policies", "pdf"): ("policy_pack_browser_pdf", "html", WRITE_ROLES),
}


@exports_bp.route("/<module>/<file_format>", methods=["POST"])
@login_required
def store_generated_export(module, file_format):
    spec = EXPORT_SPECS.get((module, file_format))
    if spec is None:
        abort(404)

    report_type, content_field, allowed_roles = spec
    if current_user.role not in allowed_roles:
        abort(403)
    if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
        abort(413, description="Export request is too large.")

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get(content_field), str):
        abort(400, description=f"A text field named {content_field} is required.")
    source = data[content_field]
    source_bytes = source.encode("utf-8")
    if not source.strip() or len(source_bytes) > MAX_EXPORT_BYTES:
        abort(400, description="Export content is empty or too large.")

    if file_format == "json":
        try:
            parsed = json.loads(source)
        except json.JSONDecodeError:
            abort(400, description="Export content must be valid JSON.")
        if not isinstance(parsed, dict):
            abort(400, description="Export JSON must be an object.")
        content = source_bytes
    elif file_format == "csv":
        content = source_bytes
    else:
        content = render_html_pdf(source)
        if len(content) > MAX_EXPORT_BYTES:
            abort(400, description="Generated PDF is too large.")

    result = upload_generated_export(
        current_user.tenant_id,
        report_type,
        file_format,
        content,
    )
    add_audit_event(
        tenant_id=current_user.tenant_id,
        actor_email=current_user.email,
        action="s3.export",
        result="success" if result.uploaded else "failure",
        resource_type="generated_export",
        resource_id=f"{module}.{file_format}",
    )
    db.session.commit()

    return jsonify(
        {
            "status": "success" if result.uploaded else "partial",
            "s3_storage": {
                "uploaded_to_aws": result.uploaded,
                "path": result.s3_uri,
                "local_copy_retained": bool(result.local_path),
                "error": result.error,
            },
        }
    ), 201 if result.uploaded else 502
