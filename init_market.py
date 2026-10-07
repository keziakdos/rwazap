from app import create_app, db
from app.models import MarketTicker

app = create_app()

with app.app_context():
    print("--- DÉBUT DE L'INITIALISATION ---")

    # 1. On s'assure que la table existe
    db.create_all()

    # 2. On nettoie les anciens (au cas où) pour éviter les doublons
    try:
        MarketTicker.query.delete()
        db.session.commit()
        print("Nettoyage effectué.")
    except Exception as e:
        print(f"Table vide ou erreur : {e}")

    # 3. On ajoute les données
    print("Ajout des tickers...")
    t1 = MarketTicker(symbol='BTC-USD', name='Bitcoin', type='crypto')
    t2 = MarketTicker(symbol='EURUSD=X', name='EUR/USD', type='forex')
    t3 = MarketTicker(symbol='AAPL', name='Apple Inc.', type='stock')
    t4 = MarketTicker(symbol='GC=F', name='Or (Gold)', type='commodities')

    db.session.add(t1)
    db.session.add(t2)
    db.session.add(t3)
    db.session.add(t4)

    # 4. On valide
    db.session.commit()

    # 5. Vérification
    count = MarketTicker.query.count()
    print(f"--- SUCCÈS : {count} TICKERS SONT MAINTENANT EN BASE ---")
