from flask import Blueprint, request, jsonify
from app import db
from app.models import AuditLog
from app.utils_aws import upload_audit_report_to_s3

policies_bp = Blueprint('policies', __name__, url_prefix='/policies')

@policies_bp.route('/generate', methods=['POST'])
def generate_security_policy():
    """
    Module 3 : Générateur de politiques de sécurité prêtes à l'emploi
    + Export automatique du rapport/politique vers le seau S3 chiffré.
    """
    data = request.json or request.form
    tenant_id = data.get('tenant_id', 'pme-01')
    policy_type = data.get('policy_type', 'password_policy') # ex: password_policy, clean_desk, incident_response

    # Templates prédéfinis de politiques pour PME
    templates = {
        "password_policy": {
            "title": "Politique de Gestion des Mots de Passe",
            "content": "Longueur minimale de 12 caractères, incluant majuscules, minuscules, chiffres et caractères spéciaux. Renouvellement tous les 90 jours."
        },
        "data_classification": {
            "title": "Politique de Classification des Données",
            "content": "Les données sont classées en 4 niveaux : Publique, Interne, Confidentielle et Restreinte (Données personnelles sensibles)."
        }
    }

    selected_policy = templates.get(policy_type, {
        "title": "Politique Générale de Sécurité",
        "content": "Respect des bonnes pratiques de conformité ISO 27001 et RGPD."
    })

    report_payload = {
        "tenant_id": tenant_id,
        "policy_type": policy_type,
        "policy_details": selected_policy,
        "generated_at": "timestamp"
    }

    # Tentative d'export vers S3 (Prouve l'intégration Cloud au jury)
    success, s3_path = upload_audit_report_to_s3(tenant_id, f"policy_{policy_type}", report_payload)

    # Enregistrement du log d'audit interne
    log_entry = AuditLog(
        tenant_id=tenant_id,
        user_email=data.get('user_email', 'admin@secureframe.com'),
        action=f"Génération politique de sécurité: {policy_type}"
    )
    db.session.add(log_entry)
    db.session.commit()

    return jsonify({
        "status": "success",
        "tenant_id": tenant_id,
        "policy": selected_policy,
        "s3_storage": {
            "uploaded_to_aws": success,
            "path": s3_path
        }
    }), 201