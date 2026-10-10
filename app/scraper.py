import feedparser
import google.generativeai as genai
import os
import re
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
        model_name = os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash').strip() or 'gemini-3.8-flash'
        return genai.GenerativeModel(model_name)
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

# Extrait l'image d'une entrée RSS (media:content > media:thumbnail > enclosure > <img> du contenu)
def extract_feed_image(entry):
    try:
        for m in getattr(entry, 'media_content', None) or []:
            url = (m or {}).get('url')
            if url and url.startswith('http'):
                return url[:500]
        for m in getattr(entry, 'media_thumbnail', None) or []:
            url = (m or {}).get('url')
            if url and url.startswith('http'):
                return url[:500]
        for enc in getattr(entry, 'enclosures', None) or []:
            href = enc.get('href') or ''
            if (enc.get('type') or '').startswith('image') and href.startswith('http'):
                return href[:500]
        blob = entry.get('summary', '') or ''
        try:
            content = entry.get('content')
            if content:
                blob += ' ' + (content[0].get('value') or '')
        except Exception:
            pass
        m = re.search(r'<img[^>]+src=["\']([^"\']+)', blob)
        if m and m.group(1).startswith('http'):
            return m.group(1)[:500]
    except Exception:
        pass
    return None

# Image de repli : og:image de la page d'article (pour les flux sans images, ex: JA, Diplo)
def fetch_og_image(url):
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, headers={'User-Agent': 'RwazapNews/1.0'}, timeout=12)
        if r.status_code != 200 or 'text/html' not in r.headers.get('Content-Type', ''):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        for prop in ('og:image', 'twitter:image'):
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            content = (tag.get('content') or '').strip() if tag else ''
            if content.startswith('http'):
                return content[:500]
    except Exception:
        pass
    return None

def run_scraper(app):
    print("--- Démarrage Robot (Mode Multi-Flash) ---", flush=True)
    # Borne tous les appels réseau (un flux lent ne doit jamais bloquer le robot)
    import socket
    socket.setdefaulttimeout(30)
    model = configure_genai()

    with app.app_context():
        from .models import ScrapeJob
        # Tracer l'exécution pour le suivi live (widget "État du robot")
        job = ScrapeJob(status='running', total_steps=0, done_steps=0)
        db.session.add(job)
        db.session.commit()

        categories = Category.query.all()
        job.total_steps = len(categories)
        db.session.commit()

        for cat in categories:
            print(f"\n📂 Traitement : {cat.name}")
            sources = Source.query.filter_by(category_id=cat.id, is_active=True).all()
            category_buffer = []

            # 1. Lecture des flux (une source en panne ne bloque jamais les autres)
            for source in sources:
                try:
                    feed = feedparser.parse(source.url)
                except Exception as e:
                    print(f"   ⚠️ Flux inaccessible ({source.name}) : {type(e).__name__}")
                    continue
                try:
                    entries = feed.entries[:3]  # 3 articles par source
                except Exception:
                    continue
                for entry in entries:
                    # Gestion date
                    if hasattr(entry, 'published_parsed'):
                        dt = datetime.fromtimestamp(mktime(entry.published_parsed))
                    else: dt = datetime.utcnow()

                    # Sauvegarde article (+ image si disponible dans le flux)
                    exists = Article.query.filter_by(original_url=entry.link).first()
                    if not exists:
                        img = extract_feed_image(entry) or fetch_og_image(entry.link)
                        new_art = Article(title=entry.title, original_url=entry.link, summary="...", image_url=img, pub_date=dt, category_id=cat.id)
                        db.session.add(new_art)
                        db.session.commit()
                        category_buffer.append({'title': entry.title, 'link': entry.link})
                    else:
                        # Remplit l'image manquante des articles déjà connus
                        try:
                            if not exists.image_url:
                                img = extract_feed_image(entry) or fetch_og_image(entry.link)
                                if img:
                                    exists.image_url = img
                                    db.session.commit()
                        except Exception:
                            pass
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

                # Progression live pour le widget "État du robot"
                try:
                    job.done_steps = (job.done_steps or 0) + 1
                    db.session.commit()
                except Exception:
                    db.session.rollback()

                time.sleep(10) # Pause Google

        # 3. Purge automatique (évite la surcharge disque : seuils via KEEP_*_PER_CAT)
        try:
            from .prune_db import prune_all
            prune_all()
        except Exception as e:
            print(f"⚠️ Purge impossible (non bloquant) : {type(e).__name__}: {e}")

        job.status = 'done'
        job.finished_at = datetime.utcnow()
        db.session.commit()
    print("--- Terminé ---")
