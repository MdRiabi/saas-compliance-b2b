import re

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.auth import WRITE_ROLES, roles_required
from app.models import AuditLog
from app.utils_aws import upload_audit_report_to_s3

policies_bp = Blueprint("policies", __name__, url_prefix="/policies")


@policies_bp.route("/generate", methods=["POST"])
@roles_required(*WRITE_ROLES)
def generate_security_policy():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = request.form
    tenant_id = current_user.tenant_id
    policy_type = data.get("policy_type", "password_policy")
    if not isinstance(policy_type, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", policy_type):
        return jsonify({"error": "Invalid policy type."}), 400
    templates = {
        "password_policy": {
            "title": "Politique de Gestion des Mots de Passe",
            "content": "Longueur minimale de 12 caractères, incluant majuscules, minuscules, chiffres et caractères spéciaux. Renouvellement tous les 90 jours.",
        },
        "data_classification": {
            "title": "Politique de Classification des Données",
            "content": "Les données sont classées en 4 niveaux : Publique, Interne, Confidentielle et Restreinte (Données personnelles sensibles).",
        },
    }
    selected_policy = templates.get(
        policy_type,
        {
            "title": "Politique Générale de Sécurité",
            "content": "Respect des bonnes pratiques de conformité ISO 27001 et RGPD.",
        },
    )
    report_payload = {
        "tenant_id": tenant_id,
        "policy_type": policy_type,
        "policy_details": selected_policy,
        "generated_at": "timestamp",
    }
    success, s3_path = upload_audit_report_to_s3(
        tenant_id, f"policy_{policy_type}", report_payload
    )
    db.session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_email=current_user.email,
            action=f"Génération politique de sécurité: {policy_type}",
        )
    )
    db.session.commit()

    return jsonify(
        {
            "status": "success",
            "tenant_id": tenant_id,
            "policy": selected_policy,
            "s3_storage": {"uploaded_to_aws": success, "path": s3_path},
        }
    ), 201
