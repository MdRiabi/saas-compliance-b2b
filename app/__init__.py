import os
from urllib.parse import urlsplit

import click
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_user, logout_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def _safe_login_redirect(target):
    if not target or "\\" in target or any(ord(char) < 32 for char in target):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    return target


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///saas_local.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
        S3_BUCKET_NAME=os.getenv("S3_BUCKET_NAME"),
        AWS_REGION=os.getenv("AWS_REGION", "us-east-1"),
        S3_SERVER_SIDE_ENCRYPTION=os.getenv("S3_SERVER_SIDE_ENCRYPTION", "AES256"),
        S3_KMS_KEY_ID=os.getenv("S3_KMS_KEY_ID"),
        AUDIT_EXPORT_DIR=os.getenv("AUDIT_EXPORT_DIR"),
    )
    if config:
        app.config.update(config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured outside source control.")

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    csrf.init_app(app)

    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        return redirect(url_for("iso.iso_dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        from app.audit import add_audit_event

        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            from app.models import User

            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first() if email else None
            if user and password and user.check_password(password):
                add_audit_event(
                    tenant_id=user.tenant_id,
                    actor_email=user.email,
                    action="auth.login",
                    resource_type="authentication",
                )
                db.session.commit()
                login_user(user)
                return redirect(_safe_login_redirect(request.args.get("next")) or url_for("index"))
            add_audit_event(
                tenant_id=user.tenant_id if user else None,
                actor_email=user.email if user else None,
                action="auth.login",
                result="failure",
                resource_type="authentication",
            )
            db.session.commit()
            flash("Identifiants invalides.", "error")
        return render_template(
            "login.html",
            email=request.form.get("email", "").strip().lower(),
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        from app.audit import add_audit_event

        if current_user.is_authenticated:
            add_audit_event(
                tenant_id=current_user.tenant_id,
                actor_email=current_user.email,
                action="auth.logout",
                resource_type="authentication",
            )
            db.session.commit()
            logout_user()
        return redirect(url_for("login"))

    @app.cli.command("create-user")
    @click.option("--email", prompt=True)
    @click.option("--tenant-id", prompt="Identifiant du tenant")
    @click.option(
        "--role",
        type=click.Choice(["admin", "compliance", "auditor"], case_sensitive=False),
        prompt=True,
    )
    def create_user_command(email, tenant_id, role):
        """Create a tenant and user account for an authorized operator."""
        from app.models import Tenant, User

        db.create_all()
        email = email.strip().lower()
        tenant_id = tenant_id.strip()
        if not email or not tenant_id:
            raise click.ClickException("L’adresse e-mail et le tenant sont obligatoires.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("Un utilisateur avec cette adresse existe déjà.")

        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None:
            tenant = Tenant(id=tenant_id, name=tenant_id)
            db.session.add(tenant)
        password = click.prompt("Mot de passe", hide_input=True, confirmation_prompt=True)
        user = User(email=email, role=role.lower(), tenant_id=tenant_id)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Utilisateur créé pour le tenant {tenant_id}.")

    @app.cli.command("export-audit-logs")
    def export_audit_logs_command():
        """Export pending tenant audit events to local archives and S3."""
        from app.audit_export import export_pending_audit_logs

        outcomes = export_pending_audit_logs()
        if not outcomes:
            click.echo("Aucun nouvel événement d’audit à exporter.")
            return
        failures = []
        for outcome in outcomes:
            tenant_label = outcome["tenant_id"] or "unassigned"
            if outcome["uploaded"]:
                click.echo(
                    f"{tenant_label}: {outcome['record_count']} événements exportés "
                    f"vers {outcome['s3_uri']} (copie locale: {outcome['local_path']})."
                )
            else:
                message = outcome["error"] or "Échec d’export non détaillé."
                failures.append(f"{tenant_label}: {message}")
                click.echo(
                    f"{tenant_label}: échec de l’export ({message}); "
                    f"copie locale: {outcome['local_path'] or 'indisponible'}."
                )
        if failures:
            raise click.ClickException(
                f"{len(failures)} export(s) S3 ont échoué; consultez les messages ci-dessus."
            )

    @app.cli.command("verify-audit-s3")
    def verify_audit_s3_command():
        """Verify public-access blocking and default encryption on the audit bucket."""
        from botocore.exceptions import BotoCoreError, ClientError

        from app.utils_aws import verify_s3_bucket_security

        try:
            checks = verify_s3_bucket_security()
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "S3ClientError")
            raise click.ClickException(
                f"Impossible de vérifier le bucket S3 ({code}); vérifiez l’accès et les permissions."
            ) from error
        except BotoCoreError as error:
            raise click.ClickException(
                f"Impossible de contacter S3 ({type(error).__name__})."
            ) from error

        click.echo(f"Bucket: {checks['bucket']}")
        click.echo(f"Blocage de l’accès public: {checks['public_access_block_enabled']}")
        click.echo(f"Politique publique: {checks['bucket_policy_is_public']}")
        click.echo(
            "Chiffrement par défaut: "
            f"{checks['default_encryption_enabled']} ({', '.join(checks['encryption_algorithms']) or 'aucun'})"
        )
        if not checks["secure"]:
            raise click.ClickException(
                "La vérification a échoué: activez le blocage public complet et un chiffrement par défaut."
            )

    from app.routes_rgpd import rgpd_bp
    from app.routes_iso import iso_bp
    from app.routes_policies import policies_bp

    app.register_blueprint(rgpd_bp)
    app.register_blueprint(iso_bp)
    app.register_blueprint(policies_bp)

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User

    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
