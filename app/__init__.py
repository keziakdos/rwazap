from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
import os
import warnings

# Initialisation des extensions
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# En-têtes de sécurité appliqués à toutes les réponses
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'SAMEORIGIN',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    # Permissif mais utile : restreint les sources (CDN autorisés : jsdelivr, Google Fonts).
    # 'unsafe-inline' conservé car les templates utilisent des gestionnaires/attributs inline.
    'Content-Security-Policy': (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https:; "
        "form-action 'self'; "
        "frame-ancestors 'self'"
    ),
}

def create_app():
    app = Flask(__name__)

    # Configuration
    secret = os.environ.get('SECRET_KEY', '')
    if not secret or secret in ('dev_key_secret', 'cle_secrete_rwazap_2024_complexe'):
        warnings.warn(
            "SECRET_KEY faible ou valeur d'exemple : définissez une vraie clé "
            "via la variable d'environnement SECRET_KEY (sessions falsifiables sinon).")
        secret = secret or 'dev_key_secret'
    app.config['SECRET_KEY'] = secret
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/db/db.sqlite'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Cookies de session : HttpOnly + SameSite=Lax ; Secure activé via COOKIE_SECURE=1 (HTTPS).
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('COOKIE_SECURE', '0') == '1'

    # Lier la base de données à l'app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    # Protection CSRF globale (tous les formulaires POST doivent inclure le token)
    csrf.init_app(app)

    # Ces imports doivent être DANS la fonction pour éviter les boucles
    from .models import User
    from .routes import main

    # Enregistrement des routes
    app.register_blueprint(main)

    @app.after_request
    def _security_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        # Ne jamais indexer les pages d'authentification
        if response.content_type.startswith('text/html'):
            response.headers.setdefault('Cache-Control', 'no-store')
        return response

    # Création de la DB si elle n'existe pas
    with app.app_context():
        db.create_all()

    return app

@login_manager.user_loader
def load_user(id):
    from .models import User
    return User.query.get(int(id))
