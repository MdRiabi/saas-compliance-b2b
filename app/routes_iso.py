from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from app import db
from app.models import AuditLog
from app.models import Iso27001Control
import json

# Déclaration unique du Blueprint
iso_bp = Blueprint('iso', __name__)

@iso_bp.route('/iso/checklist', methods=['POST'])
def save_iso_checklist():
    """
    Module 2 : Évaluation et suivi de la checklist ISO 27001:2022 (API / JSON)
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


@iso_bp.route('/iso27001', methods=['GET', 'POST'])
def iso_dashboard():
    """
    Module 2 : Tableau de bord web pour la gestion et l'affichage des contrôles ISO 27001
    """
    tenant_id = request.args.get('tenant_id', 'pme-client-01')
    
    if request.method == 'POST':
        tenant_id = request.form.get('tenant_id')
        company_name = request.form.get('company_name')
        control_domain = request.form.get('control_domain')
        control_title = request.form.get('control_title')
        implementation_status = request.form.get('implementation_status')
        evidence_notes = request.form.get('evidence_notes')
        
        new_control = Iso27001Control(
            tenant_id=tenant_id,
            company_name=company_name,
            control_domain=control_domain,
            control_title=control_title,
            implementation_status=implementation_status,
            evidence_notes=evidence_notes
        )
        db.session.add(new_control)
        db.session.commit()
        flash('Contrôle ISO 27001 mis à jour avec succès !', 'success')
        return redirect(url_for('iso.iso_dashboard', tenant_id=tenant_id))
        
    controls = Iso27001Control.query.filter_by(tenant_id=tenant_id).all()
    
    # Si aucun contrôle n'existe encore pour ce tenant, on initialise une checklist par défaut
    if not controls:
        default_controls = [
            ("A.5 Politiques de sécurité", "Politiques de sécurité de l'information", "Non implémenté"),
            ("A.8 Gestion des actifs", "Inventaire des actifs et responsabilité", "Non implémenté"),
            ("A.9 Contrôle d'accès", "Politique de contrôle d'accès aux réseaux et applications", "Non implémenté"),
            ("A.12 Sécurité liée à l'exploitation", "Procédures d'exploitation et gestion des vulnérabilités", "Non implémenté"),
            ("A.14 Sécurité des communications", "Sécurité des transferts de données et des services réseau", "Non implémenté")
        ]
        for domain, title, status in default_controls:
            c = Iso27001Control(
                tenant_id=tenant_id,
                company_name="Acme Corp",
                control_domain=domain,
                control_title=title,
                implementation_status=status,
                evidence_notes="À documenter"
            )
            db.session.add(c)
        db.session.commit()
        controls = Iso27001Control.query.filter_by(tenant_id=tenant_id).all()

    return render_template('iso_dashboard.html', controls=controls, tenant_id=tenant_id)