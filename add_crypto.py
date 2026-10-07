from app import create_app, db
from app.models import Source, Category

app = create_app()
with app.app_context():
    # 1. On trouve la catégorie
    cat = Category.query.filter_by(name="Finance & Crypto").first()

    if cat:
        # 2. On ajoute la source (Cointelegraph en Français ou Investing)
        # Ici un flux fiable sur la crypto
        s1 = Source(name="CoinTribune (Crypto)", url="https://www.cointribune.com/feed/", category_id=cat.id)

        db.session.add(s1)
        db.session.commit()
        print(f"✅ Source 'CoinTribune' ajoutée à la catégorie {cat.name} !")
    else:
        print("❌ Catégorie introuvable.")
