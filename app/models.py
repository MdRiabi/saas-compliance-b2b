from app import db
from datetime import datetime

class TenantModel(db.Model):
    """ Modèle de base pour l'isolation multi-tenant """
    __abstract__ = True
    tenant_id = db.Column(db.String(64), nullable=False, index=True)

class RgpdAudit(TenantModel):
    """ Module 1 : Enregistrement des audits RGPD par client """
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    data_processing_name = db.Column(db.String(200), nullable=False)
    compliance_score = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default="En cours")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(TenantModel):
    """ Piste d'audit interne (Remplace CloudTrail/Config dans le Lab) """
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(120), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)