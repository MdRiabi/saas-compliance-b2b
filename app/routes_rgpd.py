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
    """ 
    Module 1 : Évaluation automatique de la conformité RGPD 
    """
    data = request.get_json(silent=True) or request.form

    tenant_id = data.get('tenant_id', 'pme-demo-01')
    company_name = data.get('company_name', 'PME Demo')
    processing_name = data.get('processing_name', 'Gestion du personnel')
    
    # Critères d'évaluation RGPD (Barème sur 100 points)
    score = 0
    checks = []

    # Check 1: Base légale définie (25 pts)
    if _flag(data.get('has_legal_basis')):
        score += 25
        checks.append({"item": "Base légale", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Base légale", "status": "NON_CONFORME", "points": 0})

    # Check 2: Information des personnes / Consentement (25 pts)
    if _flag(data.get('has_privacy_notice')):
        score += 25
        checks.append({"item": "Mention d'information (Art. 13/14)", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Mention d'information (Art. 13/14)", "status": "NON_CONFORME", "points": 0})

    # Check 3: Durée de conservation limitée (25 pts)
    if _flag(data.get('has_retention_policy')):
        score += 25
        checks.append({"item": "Politique de conservation", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Politique de conservation", "status": "NON_CONFORME", "points": 0})

    # Check 4: Mesures de sécurité / Chiffrement (25 pts)
    if _flag(data.get('has_security_measures')):
        score += 25
        checks.append({"item": "Sécurité & Chiffrement", "status": "CONFORME", "points": 25})
    else:
        checks.append({"item": "Sécurité & Chiffrement", "status": "NON_CONFORME", "points": 0})

    status_eval = "CONFORME" if score >= 75 else "À RISQUE"

    # Enregistrement en base de données avec isolation tenant_id
    audit_record = RgpdAudit(
        tenant_id=tenant_id,
        company_name=company_name,
        data_processing_name=processing_name,
        compliance_score=float(score),
        status=status_eval
    )
    
    # Enregistrement du log d'audit interne
    log_entry = AuditLog(
        tenant_id=tenant_id,
        user_email=data.get('user_email', 'admin@pme.com'),
        action=f"Audit RGPD exécuté pour: {processing_name} (Score: {score}%)"
    )

    db.session.add(audit_record)
    db.session.add(log_entry)
    db.session.commit()

    return jsonify({
        "status": "success",
        "tenant_id": tenant_id,
        "processing_name": processing_name,
        "compliance_score": f"{score}%",
        "evaluation": status_eval,
        "details": checks,
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
            "score": a.compliance_score,
            "status": a.status,
            "created_at": a.created_at.strftime('%Y-%m-%d %H:%M:%S')
        } for a in audits
    ]
    return jsonify({"tenant_id": tenant_id, "audits": results}), 200