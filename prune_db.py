"""Purge les anciennes données pour éviter la surcharge du VPS.

Conservation (surchargable via variables d'environnement) :
  - KEEP_ARTICLES_PER_CAT : derniers articles gardés par catégorie (défaut 300)
  - KEEP_BRIEFINGS_PER_CAT : derniers briefings gardés par catégorie (défaut 5)
  - KEEP_FLASHES_PER_CAT : derniers flashs gardés par catégorie (défaut 5)
  - KEEP_GLOBAL_FLASHES : derniers flashs globaux gardés (défaut 5)

Seules les données anciennes, jamais affichées (l'interface ne lit que
les plus récentes), sont supprimées. Suivi d'un VACUUM pour rendre
l'espace disque à SQLite.

Usage (dans le conteneur) :
    python prune_db.py           # purge + vacuum
    python prune_db.py --dry-run # affiche ce qui serait supprimé, sans rien toucher
"""
import os
import sys

from sqlalchemy import text

from app import db
from app.models import Article, Category, DailyBriefing, CategoryFlash, GlobalFlash, ScrapeJob
from datetime import datetime, timedelta


def _keep_ids(query_ids, keep):
    """Retourne l'ensemble des IDs à conserver (les `keep` plus récents)."""
    return {r[0] for r in query_ids.limit(max(int(keep), 1)).all()}


def prune_all(dry_run=False):
    keep_articles = int(os.environ.get('KEEP_ARTICLES_PER_CAT', 300))
    keep_briefings = int(os.environ.get('KEEP_BRIEFINGS_PER_CAT', 5))
    keep_flashes = int(os.environ.get('KEEP_FLASHES_PER_CAT', 5))
    keep_global = int(os.environ.get('KEEP_GLOBAL_FLASHES', 5))
    total_deleted = 0

    for cat in Category.query.all():
        # Articles : les plus récents par date de publication
        q = (db.session.query(Article.id)
             .filter_by(category_id=cat.id)
             .order_by(Article.pub_date.desc(), Article.id.desc()))
        keep = _keep_ids(q, keep_articles)
        n_art = Article.query.filter(
            Article.category_id == cat.id, ~Article.id.in_(keep)).count() if keep else 0
        # Briefings : les plus récents par date de génération
        qb = (db.session.query(DailyBriefing.id)
              .filter_by(category_id=cat.id)
              .order_by(DailyBriefing.date.desc(), DailyBriefing.id.desc()))
        keep_b = _keep_ids(qb, keep_briefings)
        n_b = DailyBriefing.query.filter(
            DailyBriefing.category_id == cat.id, ~DailyBriefing.id.in_(keep_b)).count() if keep_b else 0
        # Flashs catégorie
        qf = (db.session.query(CategoryFlash.id)
              .filter_by(category_id=cat.id)
              .order_by(CategoryFlash.date.desc(), CategoryFlash.id.desc()))
        keep_f = _keep_ids(qf, keep_flashes)
        n_f = CategoryFlash.query.filter(
            CategoryFlash.category_id == cat.id, ~CategoryFlash.id.in_(keep_f)).count() if keep_f else 0

        print(f"{cat.name} : -{n_art} articles, -{n_b} briefings, -{n_f} flashs"
              f" (gardés : {len(keep)}/{len(keep_b)}/{len(keep_f)})")
        if not dry_run:
            if n_art:
                Article.query.filter(
                    Article.category_id == cat.id, ~Article.id.in_(keep)).delete(
                    synchronize_session=False)
            if n_b:
                DailyBriefing.query.filter(
                    DailyBriefing.category_id == cat.id, ~DailyBriefing.id.in_(keep_b)).delete(
                    synchronize_session=False)
            if n_f:
                CategoryFlash.query.filter(
                    CategoryFlash.category_id == cat.id, ~CategoryFlash.id.in_(keep_f)).delete(
                    synchronize_session=False)
            total_deleted += n_art + n_b + n_f

    # Flashs globaux (sans catégorie)
    qg = db.session.query(GlobalFlash.id).order_by(
        GlobalFlash.date.desc(), GlobalFlash.id.desc())
    keep_g = _keep_ids(qg, keep_global)
    n_g = GlobalFlash.query.filter(~GlobalFlash.id.in_(keep_g)).count() if keep_g else 0
    print(f"Flashs globaux : -{n_g} (gardés : {len(keep_g)})")
    if not dry_run and n_g:
        GlobalFlash.query.filter(~GlobalFlash.id.in_(keep_g)).delete(synchronize_session=False)
        total_deleted += n_g

    # Historique des runs du robot : 7 derniers jours maximum
    cutoff = datetime.utcnow() - timedelta(days=7)
    n_j = ScrapeJob.query.filter(ScrapeJob.started_at < cutoff).count()
    print(f"Runs du robot : -{n_j} (gardés : 7 derniers jours)")
    if not dry_run and n_j:
        ScrapeJob.query.filter(ScrapeJob.started_at < cutoff).delete(synchronize_session=False)
        total_deleted += n_j

    if dry_run:
        print("DRY-RUN : rien n'a été supprimé.")
        return 0

    db.session.commit()
    # Rend l'espace disque (hors transaction)
    try:
        with db.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            conn.execute(text('VACUUM'))
        print("VACUUM effectué.")
    except Exception as e:
        print(f"VACUUM impossible (non bloquant) : {type(e).__name__}")
    print(f"TERMINE : {total_deleted} ligne(s) supprimée(s).")
    return total_deleted


if __name__ == '__main__':
    from app import create_app
    dry = '--dry-run' in sys.argv
    app = create_app()
    with app.app_context():
        prune_all(dry_run=dry)
