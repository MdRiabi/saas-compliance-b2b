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
        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            from app.models import User

            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = User.query.filter_by(email=email).first() if email else None
            if user and password and user.check_password(password):
                login_user(user)
                return redirect(_safe_login_redirect(request.args.get("next")) or url_for("index"))
            flash("Identifiants invalides.", "error")
        return render_template(
            "login.html",
            email=request.form.get("email", "").strip().lower(),
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        if current_user.is_authenticated:
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
