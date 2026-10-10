import feedparser
import google.generativeai as genai
import os
import time
from datetime import datetime
from time import mktime
from . import db
from .models import Source, Article, Category, DailyBriefing, CategoryFlash # Ajout CategoryFlash

def configure_genai():
    api_key = (os.environ.get('GOOGLE_API_KEY') or '').strip()
    # Refuse les placeholders (ex: valeur d'exemple du dépôt) pour échouer vite et visiblement
    if not api_key or 'XXX' in api_key or len(api_key) < 20:
        print("⚠️ GOOGLE_API_KEY absente ou invalide : génération IA désactivée (articles RSS seuls).")
        return None
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel('gemini-2.5-flash')
    except Exception as e:
        print(f"⚠️ Impossible d'initialiser Gemini : {e}")
        return None

# 1. Génère le gros résumé (Briefing)
def generate_smart_briefing(model, category_name, articles_list):
    prompt = f"""
    Tu es rédacteur en chef. Catégorie : "{category_name}".
    Rédige un briefing HTML (sans balises <html> ou <body>).
    Structure :
    1. <h3>L'Essentiel</h3> : Intro.
    2. <h3>Les Faits</h3> : 3 paragraphes.
    3. <h3>Sources</h3> : Liste <ul> avec liens <a>.
    Articles : {articles_list}
    """
    try:
        return model.generate_content(prompt).text
    except Exception as e:
        print(f"⚠️ Échec briefing '{category_name}' : {type(e).__name__}: {e}")
        return None

# 2. Génère la phrase unique (Flash)
def generate_category_flash(model, category_name, articles_list):
    prompt = f"""
    Voici les titres de la catégorie "{category_name}" : {articles_list}
    
    Rédige UNE SEULE phrase courte (max 20 mots) type "Breaking News" qui résume l'info la plus critique.
    Ne mets pas le nom de la catégorie au début. Sois direct.
    Exemple: "Le président annonce sa démission suite aux manifestations."
    """
    try:
        txt = model.generate_content(prompt).text
        return txt.replace('\n', ' ').strip()
    except Exception as e:
        print(f"⚠️ Échec flash '{category_name}' : {type(e).__name__}: {e}")
        return None

def run_scraper(app):
    print("--- Démarrage Robot (Mode Multi-Flash) ---")
    model = configure_genai()
    
    with app.app_context():
        categories = Category.query.all()
        
        for cat in categories:
            print(f"\n📂 Traitement : {cat.name}")
            sources = Source.query.filter_by(category_id=cat.id, is_active=True).all()
            category_buffer = []

            # 1. Lecture des flux
            for source in sources:
                feed = feedparser.parse(source.url)
                for entry in feed.entries[:3]: # 3 articles par source
                    # Gestion date
                    if hasattr(entry, 'published_parsed'):
                        dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                    else: dt = datetime.utcnow()

                    # Sauvegarde article
                    exists = Article.query.filter_by(original_url=entry.link).first()
                    if not exists:
                        new_art = Article(title=entry.title, original_url=entry.link, summary="...", pub_date=dt, category_id=cat.id)
                        db.session.add(new_art)
                        db.session.commit()
                        category_buffer.append({'title': entry.title, 'link': entry.link})
                    else:
                        if len(category_buffer) < 8:
                            category_buffer.append({'title': entry.title, 'link': entry.link})

            # 2. Génération IA (Briefing + Flash)
            if category_buffer:
                if model is None:
                    print(f"   ⏭️ {len(category_buffer)} article(s) sauvé(s) sans briefing (IA non configurée).")
                # A. Le Briefing
                briefing_content = generate_smart_briefing(model, cat.name, category_buffer)
                if briefing_content:
                    db.session.add(DailyBriefing(content=briefing_content, category_id=cat.id))
                    
                # B. Le Flash (La nouveauté !)
                flash_content = generate_category_flash(model, cat.name, category_buffer)
                if flash_content:
                    db.session.add(CategoryFlash(content=flash_content, category_id=cat.id))
                    print(f"   🚨 Flash généré : {flash_content}")

                db.session.commit()
                print(f"   ✅ Catégorie {cat.name} terminée.")
                
                time.sleep(10) # Pause Google

    print("--- Terminé ---")
