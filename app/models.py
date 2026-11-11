from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from datetime import datetime

class TenantModel(db.Model):
    """ Modèle de base pour l'isolation multi-tenant """
    __abstract__ = True
    tenant_id = db.Column(db.String(64), nullable=False, index=True)

class RgpdAudit(TenantModel):
    """ Module 1 : Enregistrement des audits RGPD approfondis par client """
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    data_processing_name = db.Column(db.String(200), nullable=False)
    data_category = db.Column(db.String(100), default="Standard")  # Standard ou Sensible (Art. 9)
    compliance_score = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(50), default="En cours")
    recommendations = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(TenantModel):
    """ Piste d'audit interne (Remplace CloudTrail/Config dans le Lab) """
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(120), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Iso27001Control(TenantModel):
    """ Module 2 : Suivi de la conformité ISO 27001 (Annexe A) """
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), nullable=False)
    control_domain = db.Column(db.String(150), nullable=False)  # Ex: A.9 Contrôle d'accès
    control_title = db.Column(db.String(200), nullable=False)
    implementation_status = db.Column(db.String(50), default="Non implémenté") # Implémenté, Partiel, Non implémenté
    evidence_notes = db.Column(db.Text, nullable=True) # Justificatifs ou politiques associées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    
    
    
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # admin, compliance, auditor
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Flask-Login requires these properties if not using default id, but UserMixin provides them.
    def get_id(self):
        return str(self.id)