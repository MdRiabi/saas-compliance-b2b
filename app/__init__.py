from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
from dotenv import load_dotenv
from flask import render_template

    

load_dotenv()

db = SQLAlchemy()
migrate = Migrate()



def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///saas_local.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db)

    # 1. Route racine (Page d'accueil du SaaS)
    @app.route('/')
    def index():
        return render_template('index.html')

    # IMPORT LOCAL DES BLUEPRINTS (Évite l'importation circulaire)
    from app.routes_rgpd import rgpd_bp
    from app.routes_iso import iso_bp
    from app.routes_policies import policies_bp

    app.register_blueprint(rgpd_bp)
    app.register_blueprint(iso_bp)
    app.register_blueprint(policies_bp)

    return app
