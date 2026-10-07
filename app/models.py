from . import db
from flask_login import UserMixin
from datetime import datetime

# 1. Table Utilisateurs
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

# 2. Table Catégories
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    articles = db.relationship('Article', backref='category', lazy=True)
    # Relations inverses (ajoutées pour faciliter la navigation)
    # sources = relationship définie dans Source
    # briefings = relationship définie dans DailyBriefing
    # flashes = relationship définie dans CategoryFlash

# 3. Table Sources (RSS)
class Source(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(200), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    is_active = db.Column(db.Boolean, default=True)
    # Le lien vers la catégorie
    category = db.relationship('Category', backref=db.backref('sources', lazy=True))

# 4. Table Articles (Détail)
class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    original_url = db.Column(db.String(500), nullable=False, unique=True)
    image_url = db.Column(db.String(500))
    pub_date = db.Column(db.DateTime)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    click_count = db.Column(db.Integer, default=0)

# 5. Table Finance (Bourse/Crypto)
class MarketTicker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(50))
    type = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

# 6. Table Briefings (Le résumé groupé par catégorie)
class DailyBriefing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    category = db.relationship('Category', backref=db.backref('briefings', lazy=True))

# 7. Table Flash Info Global (Le mélange mondial - optionnel maintenant)
class GlobalFlash(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(500), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)

# 8. Table Category Flash (La phrase choc PAR catégorie) <-- C'EST ELLE QUI MANQUAIT
class CategoryFlash(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(300), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    category = db.relationship('Category', backref=db.backref('flashes', lazy=True))
