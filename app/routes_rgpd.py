from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.auth import WRITE_ROLES, roles_required
from app.audit import add_audit_event
from app.models import RgpdAudit
from app.utils_aws import upload_audit_report_to_s3

rgpd_bp = Blueprint("rgpd", __name__, url_prefix="/rgpd")


def _flag(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "oui", "on"}


def _request_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else request.form


def _text_field(data, name, default, max_length):
    value = data.get(name, default)
    if not isinstance(value, str):
        abort(400, description=f"{name} must be text.")
    value = value.strip()
    if not value or len(value) > max_length:
        abort(400, description=f"{name} must contain between 1 and {max_length} characters.")
    return value


@rgpd_bp.route("/audit", methods=["GET"])
@roles_required("admin", "compliance", "auditor")
def audit_page():
    return render_template(
        "audit-rgpd-module1.html",
        tenant_id=current_user.tenant_id,
    )


@rgpd_bp.route("/audit", methods=["POST"])
@roles_required(*WRITE_ROLES)
def run_audit():
    data = _request_data()
    tenant_id = current_user.tenant_id
    company_name = _text_field(data, "company_name", "PME Demo", 120)
    processing_name = _text_field(data, "processing_name", "Gestion du personnel", 200)
    data_category = _text_field(data, "data_category", "Standard", 100)

    score = 0
    checks = []
    recommendations = []

    checks_config = (
        ("has_legal_basis", "Base légale (Art. 6)", "Définir une base légale claire (ex: consentement, obligation légale ou intérêt légitime)."),
        ("has_privacy_notice", "Mention d'information (Art. 13/14)", "Mettre en place une politique de confidentialité accessible aux personnes concernées."),
        ("has_retention_policy", "Politique de conservation", "Fixer une durée de conservation précise en accord avec les recommandations de la CNIL."),
        ("has_security_measures", "Sécurité & Chiffrement AWS", "Activer le chiffrement des données au repos (KMS / SSE-S3) et le contrôle d'accès RBAC."),
    )
    for field, label, recommendation in checks_config:
        if _flag(data.get(field)):
            score += 25
            checks.append({"item": label, "status": "CONFORME", "points": 25})
        else:
            checks.append({"item": label, "status": "NON_CONFORME", "points": 0})
            recommendations.append(recommendation)

    status_eval = "CONFORME" if score >= 75 else "À RISQUE"
    report_payload = {
        "tenant_id": tenant_id,
        "company_name": company_name,
        "processing_name": processing_name,
        "data_category": data_category,
        "compliance_score": f"{score}%",
        "evaluation": status_eval,
        "details": checks,
        "recommendations": recommendations,
    }

    export_result = upload_audit_report_to_s3(
        tenant_id,
        f"rgpd_audit_{processing_name.replace(' ', '_')}",
        report_payload,
    )
    audit_record = RgpdAudit(
        tenant_id=tenant_id,
        company_name=company_name,
        data_processing_name=processing_name,
        data_category=data_category,
        compliance_score=float(score),
        status=status_eval,
        recommendations=" | ".join(recommendations) if recommendations else "Aucune recommandation majeure.",
    )
    db.session.add(audit_record)
    db.session.flush()
    add_audit_event(
        tenant_id=tenant_id,
        actor_email=current_user.email,
        action="rgpd.audit.run",
        resource_type="rgpd_audit",
        resource_id=audit_record.id,
    )
    add_audit_event(
        tenant_id=tenant_id,
        actor_email=current_user.email,
        action="s3.export",
        result="success" if export_result.uploaded else "failure",
        resource_type="rgpd_audit",
        resource_id=audit_record.id,
    )
    db.session.commit()

    return jsonify(
        {
            "status": "success" if export_result.uploaded else "partial",
            "tenant_id": tenant_id,
            "processing_name": processing_name,
            "compliance_score": f"{score}%",
            "evaluation": status_eval,
            "details": checks,
            "recommendations": recommendations,
            "s3_storage": {
                "uploaded_to_aws": export_result.uploaded,
                "path": export_result.s3_uri,
                "local_copy": export_result.local_path,
                "error": export_result.error,
            },
            "audit_id": audit_record.id,
        }
    ), 201


@rgpd_bp.route("/audits", methods=["GET"])
@roles_required("admin", "compliance", "auditor")
def list_audits():
    tenant_id = current_user.tenant_id
    audits = RgpdAudit.query.filter_by(tenant_id=tenant_id).all()
    results = [
        {
            "id": audit.id,
            "company_name": audit.company_name,
            "processing_name": audit.data_processing_name,
            "data_category": audit.data_category,
            "score": audit.compliance_score,
            "status": audit.status,
            "recommendations": audit.recommendations,
            "created_at": audit.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for audit in audits
    ]
    return jsonify({"tenant_id": tenant_id, "audits": results}), 200
