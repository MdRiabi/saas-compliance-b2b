from flask import Blueprint, request, jsonify
from app import db
from app.models import AuditLog
import json

iso_bp = Blueprint('iso', __name__, url_prefix='/iso')

@iso_bp.route('/checklist', methods=['POST'])
def save_iso_checklist():
    """
    Module 2 : Évaluation et suivi de la checklist ISO 27001:2022
    """
    data = request.get_json(silent=True) or request.form
    tenant_id = data.get('tenant_id', 'pme-01')
    controls = data.get('controls', [])  # Ex: [{"id": "A.5.1", "name": "Politiques de sécurité", "status": "Implemente"}]
    if isinstance(controls, str):
        try:
            controls = json.loads(controls)
        except ValueError:
            controls = []
    if not isinstance(controls, list):
        controls = []
    
    total_controls = len(controls) if controls else 1
    implemented = sum(1 for c in controls if c.get('status') == 'Implemente')
    score = (implemented / total_controls) * 100

    # Enregistrement du log de traçabilité interne
    log_entry = AuditLog(
        tenant_id=tenant_id,
        user_email=data.get('user_email', 'admin@secureframe.com'),
        action=f"Mise à jour Checklist ISO 27001 - Score: {score:.1f}%"
    )
    db.session.add(log_entry)
    db.session.commit()

    return jsonify({
        "status": "success",
        "tenant_id": tenant_id,
        "standard": "ISO 27001:2022",
        "compliance_score": f"{score:.1f}%",
        "controls_checked": total_controls,
        "controls_implemented": implemented
    }), 201
