from app import create_app
from app.scraper import run_scraper

# On crée l'application
app = create_app()

# On lance le robot directement
if __name__ == "__main__":
    print("Lancement manuel du robot...")
    run_scraper(app)
    print("Robot terminé.")
