from app import create_app, db
from app.models import GlobalFlash
app = create_app()
with app.app_context():
    db.create_all()
    print("✅ Table GlobalFlash ajoutée !")
