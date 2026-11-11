import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.auth import WRITE_ROLES, roles_required
from app.models import AuditLog, Iso27001Control

iso_bp = Blueprint("iso", __name__)
CONTROL_STATUSES = {"Non implémenté", "Partiel", "Implémenté"}


def _request_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else request.form


@iso_bp.route("/controls", methods=["GET"])
@roles_required("admin", "compliance", "auditor")
def get_controls():
    controls = Iso27001Control.query.filter_by(tenant_id=current_user.tenant_id).all()
    return jsonify(
        [
            {
                "id": control.id,
                "name": control.control_title,
                "status": control.implementation_status,
            }
            for control in controls
        ]
    )


@iso_bp.route("/controls", methods=["POST"])
@roles_required(*WRITE_ROLES)
def add_control():
    data = _request_data()
    name = data.get("name") or data.get("control_title")
    status = data.get("status", "Non implémenté")
    company_name = data.get("company_name", current_user.tenant_id)
    control_domain = data.get("control_domain", "À préciser")
    evidence_notes = data.get("evidence_notes")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 200
        or not isinstance(status, str)
        or status not in CONTROL_STATUSES
        or not isinstance(company_name, str)
        or not company_name.strip()
        or len(company_name) > 120
        or not isinstance(control_domain, str)
        or not control_domain.strip()
        or len(control_domain) > 150
        or (evidence_notes is not None and not isinstance(evidence_notes, str))
    ):
        abort(400, description="A valid control name and status are required.")

    control = Iso27001Control(
        tenant_id=current_user.tenant_id,
        company_name=company_name.strip(),
        control_domain=control_domain.strip(),
        control_title=name.strip(),
        implementation_status=status,
        evidence_notes=evidence_notes,
    )
    db.session.add(control)
    db.session.commit()
    return jsonify({"message": "Control added", "id": control.id}), 201


@iso_bp.route("/iso/checklist", methods=["POST"])
@roles_required(*WRITE_ROLES)
def save_iso_checklist():
    data = _request_data()
    controls = data.get("controls", [])
    if isinstance(controls, str):
        try:
            controls = json.loads(controls)
        except ValueError:
            abort(400, description="Controls must be a valid JSON list.")
    if not isinstance(controls, list) or any(not isinstance(control, dict) for control in controls):
        abort(400, description="Controls must be a list of objects.")

    total_controls = len(controls) or 1
    implemented = sum(
        1
        for control in controls
        if control.get("status") == "Implémenté" or control.get("status") == "Implemente"
    )
    score = implemented / total_controls * 100
    db.session.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            user_email=current_user.email,
            action=f"Mise à jour Checklist ISO 27001 - Score: {score:.1f}%",
        )
    )
    db.session.commit()

    return jsonify(
        {
            "status": "success",
            "tenant_id": current_user.tenant_id,
            "standard": "ISO 27001:2022",
            "compliance_score": f"{score:.1f}%",
            "controls_checked": total_controls,
            "controls_implemented": implemented,
        }
    ), 201


@iso_bp.route("/iso27001", methods=["GET", "POST"])
@roles_required("admin", "compliance", "auditor")
def iso_dashboard():
    tenant_id = current_user.tenant_id

    if request.method == "POST":
        if current_user.role not in WRITE_ROLES:
            abort(403)
        company_name = request.form.get("company_name", tenant_id).strip()
        control_domain = request.form.get("control_domain", "").strip()
        control_title = request.form.get("control_title", "").strip()
        implementation_status = request.form.get("implementation_status", "")
        if not company_name or not control_domain or not control_title:
            abort(400, description="Company, domain, and control title are required.")
        if len(company_name) > 120 or len(control_domain) > 150 or len(control_title) > 200:
            abort(400, description="Company, domain, or control title is too long.")
        if implementation_status not in CONTROL_STATUSES:
            abort(400, description="Invalid control status.")

        control = Iso27001Control(
            tenant_id=tenant_id,
            company_name=company_name,
            control_domain=control_domain,
            control_title=control_title,
            implementation_status=implementation_status,
            evidence_notes=request.form.get("evidence_notes"),
        )
        db.session.add(control)
        db.session.commit()
        flash("Contrôle ISO 27001 mis à jour avec succès !", "success")
        return redirect(url_for("iso.iso_dashboard"))

    controls = Iso27001Control.query.filter_by(tenant_id=tenant_id).all()
    if not controls and current_user.role in WRITE_ROLES:
        default_controls = [
            ("A.5 Politiques de sécurité", "Politiques de sécurité de l'information"),
            ("A.8 Gestion des actifs", "Inventaire des actifs et responsabilité"),
            ("A.9 Contrôle d'accès", "Politique de contrôle d'accès aux réseaux et applications"),
            ("A.12 Sécurité liée à l'exploitation", "Procédures d'exploitation et gestion des vulnérabilités"),
            ("A.14 Sécurité des communications", "Sécurité des transferts de données et des services réseau"),
        ]
        for domain, title in default_controls:
            db.session.add(
                Iso27001Control(
                    tenant_id=tenant_id,
                    company_name=tenant_id,
                    control_domain=domain,
                    control_title=title,
                    implementation_status="Non implémenté",
                    evidence_notes="À documenter",
                )
            )
        db.session.commit()
        controls = Iso27001Control.query.filter_by(tenant_id=tenant_id).all()

    return render_template(
        "iso_dashboard.html",
        controls=controls,
        tenant_id=tenant_id,
        can_write=current_user.role in WRITE_ROLES,
    )
