from flask import Flask, redirect, render_template, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
import os
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///saas_local.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_TIME_LIMIT'] = None

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    
    login_manager.login_view = 'login'

    # 1. Route racine (Page d'accueil du SaaS)
    @app.route('/')
    def index():
        return redirect(url_for('iso.iso_dashboard'))

    # IMPORT LOCAL DES BLUEPRINTS (Évite l'importation circulaire)
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
        return User.query.get(int(user_id))

    # Register Blueprints
    from app.routes_iso import iso_bp
    from app.routes_rgpd import rgpd_bp
    app.register_blueprint(iso_bp, url_prefix='/api/iso')
    app.register_blueprint(rgpd_bp, url_prefix='/api/rgpd')

    # Simplified Auth Routes for Lab Demo
    from flask import render_template_string, request, redirect, url_for
    from flask_login import login_user, logout_user, current_user

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        # Simplified login form for demonstration
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            from app.models import User
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for('index'))
            return 'Invalid credentials', 401
        return render_template_string('<form method="POST"><input name="email"><input name="password" type="password"><button>Login</button></form>')

    @app.route('/logout')
    def logout():
        logout_user()
        return 'Logged out'

    @app.route('/')
    def index():
        return 'Compliance App Running'

    return app