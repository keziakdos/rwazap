from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////app/db/db.sqlite'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login' # Redirection si pas connecté

    from .models import User

    # Enregistrement des routes (C'est la nouveauté !)
    from .routes import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()

    return app

@login_manager.user_loader
def load_user(id):
    from .models import User
    return User.query.get(int(id))
