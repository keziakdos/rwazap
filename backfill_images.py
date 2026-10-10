"""Remplit les image_url manquantes des articles existants.

Stratégie (dans l'ordre) :
  1. Images trouvées dans les flux RSS actuels (rapide, sans requête page).
  2. Balise og:image / twitter:image de la page d'article (plus lent).

Usage (dans le conteneur) :
    python backfill_images.py [limite_par_categorie=50]

Les URLs sont tronquées à 500 caractères (taille de la colonne).
"""
import socket
import sys
import time

import feedparser
import requests
from bs4 import BeautifulSoup

from app import create_app, db
from app.models import Source, Article, Category
from app.scraper import extract_feed_image

socket.setdefaulttimeout(20)
UA = {'User-Agent': 'RwazapNews/1.0 (+https://github.com/keziakdos/rwazap)'}


def og_image(url):
    """Récupère l'image principale d'une page d'article via og:image."""
    try:
        r = requests.get(url, headers=UA, timeout=15)
        if r.status_code != 200 or 'text/html' not in r.headers.get('Content-Type', ''):
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        for prop in ('og:image', 'twitter:image'):
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            content = (tag.get('content') or '').strip() if tag else ''
            if content.startswith('http'):
                return content[:500]
    except Exception as e:
        print(f"      page inaccessible : {type(e).__name__}")
    return None


def main(limit_per_cat=50):
    app = create_app()
    with app.app_context():
        # 1) Index link -> image depuis les flux actuels
        feed_images = {}
        for src in Source.query.filter_by(is_active=True).all():
            try:
                for e in feedparser.parse(src.url).entries:
                    img = extract_feed_image(e)
                    if img and getattr(e, 'link', None):
                        feed_images.setdefault(e.link, img)
            except Exception as e:
                print(f"flux {src.name} : {type(e).__name__}")
        print(f"{len(feed_images)} images repérées dans les flux actuels.")

        # 2) Articles sans image (les plus récents d'abord)
        total = filled_feed = filled_og = 0
        for cat in Category.query.all():
            arts = (Article.query
                    .filter_by(category_id=cat.id)
                    .filter((Article.image_url.is_(None)) | (Article.image_url == ''))
                    .order_by(Article.pub_date.desc())
                    .limit(limit_per_cat).all())
            for a in arts:
                total += 1
                img = feed_images.get(a.original_url)
                if img:
                    a.image_url = img
                    filled_feed += 1
                else:
                    img = og_image(a.original_url)
                    if img:
                        a.image_url = img
                        filled_og += 1
                    time.sleep(0.3)  # politesse envers les sites sources
                if total % 20 == 0:
                    db.session.commit()
            db.session.commit()
            print(f"{cat.name} : {len(arts)} article(s) traité(s).")
        print(f"TERMINE : {total} traités, {filled_feed} via flux, {filled_og} via og:image.")


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 50)
