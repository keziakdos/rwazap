from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os

# Initialisation des extensions
db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)

    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_secret')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/db/db.sqlite'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Lier la base de données à l'app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login' 

    # Ces imports doivent être DANS la fonction pour éviter les boucles
    from .models import User
    from .routes import main

    # Enregistrement des routes
    app.register_blueprint(main)

    # Création de la DB si elle n'existe pas
    with app.app_context():
        db.create_all()

    return app

@login_manager.user_loader
def load_user(id):
    from .models import User
    return User.query.get(int(id))
