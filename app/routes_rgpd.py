from flask import Blueprint, request, jsonify
from app import db
from app.models import RgpdAudit, AuditLog

rgpd_bp = Blueprint('rgpd', __name__, url_prefix='/rgpd')


def _flag(value):
    """ Interprète une valeur JSON ou de formulaire comme un booléen """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ('1', 'true', 'yes', 'oui', 'on')

@rgpd_bp.route('/audit', methods=['POST'])
def run_audit():
    data = request.json or request.form

    tenant_id = data.get('tenant_id', 'pme-demo-01')
    company_name = data.get('company_name', 'PME Demo')
    processing_name = data.get('processing_name', 'Gestion du personnel')
    data_category = data.get('data_category', 'Standard')
    
    score = 0
    checks = []
    recos = []

    # 1. Base légale (25 pts)
    if data.get('has_legal_basis'):
        score += 25
        checks.append({"item": "Base légale (Art. 6)", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Base légale (Art. 6)", "status": "NON_CONFORME", "points": 0})
        recos.append("Définir une base légale claire (ex: consentement, obligation légale ou intérêt légitime).")

    # 2. Information des personnes (25 pts)
    if data.get('has_privacy_notice'):
        score += 25
        checks.append({"item": "Mention d'information (Art. 13/14)", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Mention d'information (Art. 13/14)", "status": "NON_CONFORME", "points": 0})
        recos.append("Mettre en place une politique de confidentialité accessible aux personnes concernées.")

    # 3. Durée de conservation (25 pts)
    if data.get('has_retention_policy'):
        score += 25
        checks.append({"item": "Politique de conservation", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Politique de conservation", "status": "NON_CONFORME", "points": 0})
        recos.append("Fixer une durée de conservation précise en accord avec les recommandations de la CNIL.")

    # 4. Sécurité technique & Chiffrement (25 pts)
    if data.get('has_security_measures'):
        score += 25
        checks.append({"item": "Sécurité & Chiffrement AWS", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Sécurité & Chiffrement AWS", "status": "NON_CONFORME", "points": 0})
        recos.append("Activer le chiffrement des données au repos (KMS / SSE-S3) et le contrôle d'accès RBAC.")

    status_eval = "CONFORME" if score >= 75 else "À RISQUE"

    # Enregistrement base de données
    audit_record = RgpdAudit(
        tenant_id=tenant_id,
        company_name=company_name,
        data_processing_name=processing_name,
        data_category=data_category,
        compliance_score=float(score),
        status=status_eval,
        recommendations=" | ".join(recos) if recos else "Aucune recommandation majeure."
    )
    
    db.session.add(audit_record)
    db.session.commit()

    return jsonify({
        "status": "success",
        "tenant_id": tenant_id,
        "processing_name": processing_name,
        "compliance_score": f"{score}%",
        "evaluation": status_eval,
        "details": checks,
        "recommendations": recos,
        "audit_id": audit_record.id
    }), 201

@rgpd_bp.route('/audits/<tenant_id>', methods=['GET'])
def list_audits(tenant_id):
    """ Récupère tous les audits d'un tenant spécifique """
    audits = RgpdAudit.query.filter_by(tenant_id=tenant_id).all()
    results = [
        {
            "id": a.id,
            "company_name": a.company_name,
            "processing_name": a.data_processing_name,
            "data_category": a.data_category,
            "score": a.compliance_score,
            "status": a.status,
            "recommendations": a.recommendations,
            "created_at": a.created_at.strftime('%Y-%m-%d %H:%M:%S')
        } for a in audits
    ]
    return jsonify({"tenant_id": tenant_id, "audits": results}), 200
