from app import create_app, db
from app.models import CategoryFlash
app = create_app()
with app.app_context():
    db.create_all()
    print("✅ Table CategoryFlash ajoutée !")
