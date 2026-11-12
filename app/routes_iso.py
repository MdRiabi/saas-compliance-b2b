import json

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.auth import WRITE_ROLES, roles_required
from app.audit import add_audit_event
from app.models import Iso27001Control

iso_bp = Blueprint("iso", __name__)
STATUS_OPTIONS = ("Non démarré", "En cours", "Implémenté", "À revoir", "Non applicable")
CONTROL_STATUSES = set(STATUS_OPTIONS)
LEGACY_STATUS_MAP = {
    "Non implémenté": "Non démarré",
    "Partiel": "En cours",
    "À faire": "Non démarré",
    "Implemente": "Implémenté",
}
ISO_CONTROL_CATALOG = (
    {
        "id": "A.5.1",
        "domain": "Organisationnel",
        "title": "Politique de sécurité de l’information",
        "summary": "Définir et faire approuver des orientations de sécurité adaptées aux risques de l’organisation.",
    },
    {
        "id": "A.5.2",
        "domain": "Organisationnel",
        "title": "Rôles et responsabilités de sécurité",
        "summary": "Attribuer clairement les responsabilités liées à la sécurité de l’information.",
    },
    {
        "id": "A.5.9",
        "domain": "Organisationnel",
        "title": "Inventaire des actifs informationnels",
        "summary": "Tenir un inventaire des informations et actifs associés avec un responsable identifié.",
    },
    {
        "id": "A.5.15",
        "domain": "Organisationnel",
        "title": "Gestion des accès",
        "summary": "Définir des règles d’accès fondées sur les besoins métiers et le moindre privilège.",
    },
    {
        "id": "A.5.23",
        "domain": "Organisationnel",
        "title": "Sécurité des services cloud",
        "summary": "Encadrer l’acquisition, l’utilisation, le suivi et la sortie des services cloud.",
    },
    {
        "id": "A.5.24",
        "domain": "Organisationnel",
        "title": "Préparation à la gestion des incidents",
        "summary": "Préparer les rôles, procédures et moyens nécessaires au traitement des incidents.",
    },
    {
        "id": "A.6.3",
        "domain": "Personnel",
        "title": "Sensibilisation et formation",
        "summary": "Former les collaborateurs aux règles et pratiques de sécurité qui les concernent.",
    },
    {
        "id": "A.7.4",
        "domain": "Physique",
        "title": "Surveillance des locaux",
        "summary": "Surveiller les locaux et zones sensibles de manière proportionnée aux risques.",
    },
    {
        "id": "A.8.8",
        "domain": "Technologique",
        "title": "Gestion des vulnérabilités techniques",
        "summary": "Identifier les vulnérabilités pertinentes et organiser leur évaluation et traitement.",
    },
    {
        "id": "A.8.13",
        "domain": "Technologique",
        "title": "Sauvegarde des informations",
        "summary": "Protéger les sauvegardes et vérifier périodiquement que les restaurations fonctionnent.",
    },
    {
        "id": "A.8.15",
        "domain": "Technologique",
        "title": "Journalisation des événements",
        "summary": "Enregistrer les événements utiles à la surveillance et aux investigations.",
    },
    {
        "id": "A.8.16",
        "domain": "Technologique",
        "title": "Surveillance des activités",
        "summary": "Détecter les comportements anormaux et organiser leur revue.",
    },
)


def _request_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else request.form


def _normalize_status(status):
    if not isinstance(status, str):
        return "À revoir"
    status = LEGACY_STATUS_MAP.get(status, status)
    return status if status in CONTROL_STATUSES else "À revoir"


def _catalog_control(control_id):
    return next((item for item in ISO_CONTROL_CATALOG if item["id"] == control_id), None)


@iso_bp.route("/controls", methods=["GET"])
@roles_required("admin", "compliance", "auditor")
def get_controls():
    controls = Iso27001Control.query.filter_by(tenant_id=current_user.tenant_id).all()
    return jsonify(
        [
            {
                "id": control.id,
                "name": control.control_title,
                "status": _normalize_status(control.implementation_status),
            }
            for control in controls
        ]
    )


@iso_bp.route("/controls", methods=["POST"])
@roles_required(*WRITE_ROLES)
def add_control():
    data = _request_data()
    catalog_id = data.get("catalog_id")
    catalog_control = _catalog_control(catalog_id) if catalog_id else None
    raw_status = data.get("status", "Non démarré")
    if not isinstance(raw_status, str) or raw_status not in CONTROL_STATUSES | set(LEGACY_STATUS_MAP):
        abort(400, description="Invalid control status.")
    status = _normalize_status(raw_status)
    if catalog_id and catalog_control is None:
        abort(400, description="Unknown ISO control.")

    name = (
        catalog_control["title"]
        if catalog_control
        else data.get("name") or data.get("control_title")
    )
    company_name = current_user.tenant_id
    control_domain = (
        f'{catalog_control["id"]} — {catalog_control["domain"]}'
        if catalog_control
        else data.get("control_domain", "À préciser")
    )
    evidence_notes = data.get("evidence_notes")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 200
        or status not in CONTROL_STATUSES
        or not isinstance(control_domain, str)
        or not control_domain.strip()
        or len(control_domain) > 150
        or (evidence_notes is not None and not isinstance(evidence_notes, str))
        or (evidence_notes is not None and len(evidence_notes) > 5000)
    ):
        abort(400, description="A valid control name and status are required.")

    if catalog_control and Iso27001Control.query.filter_by(
        tenant_id=current_user.tenant_id,
        control_domain=control_domain,
    ).first():
        abort(409, description="This ISO control is already on the checklist.")

    control = Iso27001Control(
        tenant_id=current_user.tenant_id,
        company_name=company_name,
        control_domain=control_domain.strip(),
        control_title=name.strip(),
        implementation_status=status,
        evidence_notes=evidence_notes,
    )
    db.session.add(control)
    db.session.flush()
    add_audit_event(
        tenant_id=current_user.tenant_id,
        actor_email=current_user.email,
        action="iso27001.control.create",
        resource_type="iso27001_control",
        resource_id=control.id,
    )
    db.session.commit()
    return jsonify({"message": "Control added", "id": control.id}), 201


@iso_bp.route("/iso27001/<int:control_id>/edit", methods=["POST"])
@roles_required(*WRITE_ROLES)
def edit_iso_control(control_id):
    control = Iso27001Control.query.filter_by(
        id=control_id,
        tenant_id=current_user.tenant_id,
    ).first_or_404()
    status = _normalize_status(request.form.get("implementation_status", ""))
    evidence_notes = request.form.get("evidence_notes", "").strip()
    if request.form.get("implementation_status") not in CONTROL_STATUSES | set(LEGACY_STATUS_MAP):
        abort(400, description="Invalid control status.")
    if len(evidence_notes) > 5000:
        abort(400, description="Evidence notes are too long.")

    control.implementation_status = status
    control.evidence_notes = evidence_notes or None
    add_audit_event(
        tenant_id=current_user.tenant_id,
        actor_email=current_user.email,
        action="iso27001.control.update",
        resource_type="iso27001_control",
        resource_id=control.id,
    )
    db.session.commit()
    flash("Le contrôle a été mis à jour.", "success")
    return redirect(url_for("iso.iso_dashboard"))


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

    valid_statuses = CONTROL_STATUSES | set(LEGACY_STATUS_MAP)
    if any(
        not isinstance(control.get("status", "Non démarré"), str)
        or control.get("status", "Non démarré") not in valid_statuses
        for control in controls
    ):
        abort(400, description="A control contains an invalid status.")
    total_controls = len(controls)
    applicable_controls = sum(
        _normalize_status(control.get("status", "Non démarré")) != "Non applicable"
        for control in controls
    )
    implemented = sum(
        _normalize_status(control.get("status", "Non démarré")) == "Implémenté"
        for control in controls
    )
    score = implemented / applicable_controls * 100 if applicable_controls else 0
    add_audit_event(
        tenant_id=current_user.tenant_id,
        actor_email=current_user.email,
        action="iso27001.checklist.evaluate",
        resource_type="iso27001_checklist",
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
        catalog_id = request.form.get("catalog_id", "")
        catalog_control = _catalog_control(catalog_id) if catalog_id else None
        if catalog_id and catalog_control is None:
            abort(400, description="Unknown ISO control.")

        implementation_status = request.form.get("implementation_status", "")
        if implementation_status not in CONTROL_STATUSES | set(LEGACY_STATUS_MAP):
            abort(400, description="Invalid control status.")

        evidence_notes = request.form.get("evidence_notes", "").strip()
        if len(evidence_notes) > 5000:
            abort(400, description="Evidence notes are too long.")

        if catalog_control:
            control_domain = f'{catalog_control["id"]} — {catalog_control["domain"]}'
            control_title = catalog_control["title"]
            if Iso27001Control.query.filter_by(
                tenant_id=tenant_id,
                control_domain=control_domain,
            ).first():
                abort(409, description="This ISO control is already on the checklist.")
            company_name = tenant_id
        else:
            company_name = request.form.get("company_name", tenant_id).strip()
            control_domain = request.form.get("control_domain", "").strip()
            control_title = request.form.get("control_title", "").strip()
            if not company_name or not control_domain or not control_title:
                abort(400, description="Company, domain, and control title are required.")
            if len(company_name) > 120 or len(control_domain) > 150 or len(control_title) > 200:
                abort(400, description="Company, domain, or control title is too long.")

        control = Iso27001Control(
            tenant_id=tenant_id,
            company_name=company_name,
            control_domain=control_domain,
            control_title=control_title,
            implementation_status=_normalize_status(implementation_status),
            evidence_notes=evidence_notes or None,
        )
        db.session.add(control)
        db.session.flush()
        add_audit_event(
            tenant_id=tenant_id,
            actor_email=current_user.email,
            action="iso27001.control.create",
            resource_type="iso27001_control",
            resource_id=control.id,
        )
        db.session.commit()
        flash("Contrôle ISO 27001 mis à jour avec succès !", "success")
        return redirect(url_for("iso.iso_dashboard"))

    controls = Iso27001Control.query.filter_by(tenant_id=tenant_id).order_by(
        Iso27001Control.control_domain,
        Iso27001Control.id,
    ).all()
    control_rows = [
        {
            "id": control.id,
            "control_domain": control.control_domain,
            "control_title": control.control_title,
            "implementation_status": _normalize_status(control.implementation_status),
            "evidence_notes": control.evidence_notes,
        }
        for control in controls
    ]
    implemented_controls = sum(
        control["implementation_status"] == "Implémenté" for control in control_rows
    )
    partial_controls = sum(
        control["implementation_status"] == "En cours" for control in control_rows
    )
    applicable_controls = sum(
        control["implementation_status"] != "Non applicable" for control in control_rows
    )
    progress = round(implemented_controls / applicable_controls * 100) if applicable_controls else 0
    existing_domains = {control["control_domain"] for control in control_rows}
    available_catalog = [
        item
        for item in ISO_CONTROL_CATALOG
        if f'{item["id"]} — {item["domain"]}' not in existing_domains
    ]

    return render_template(
        "iso_dashboard.html",
        controls=control_rows,
        tenant_id=tenant_id,
        can_write=current_user.role in WRITE_ROLES,
        catalog=ISO_CONTROL_CATALOG,
        available_catalog=available_catalog,
        implemented_controls=implemented_controls,
        partial_controls=partial_controls,
        applicable_controls=applicable_controls,
        progress=progress,
        statuses=STATUS_OPTIONS,
    )
