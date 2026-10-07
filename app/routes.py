from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
# ATTENTION : La ligne ci-dessous est cruciale, elle contient CategoryFlash
from .models import User, Article, Category, Source, MarketTicker, DailyBriefing, CategoryFlash
from .scraper import run_scraper
import threading
import yfinance as yf
import re
import html as html_lib
from datetime import datetime
from urllib.parse import urlparse

main = Blueprint('main', __name__)

# ---------- Helpers d'affichage (aucune logique métier modifiée) ----------

PLACEHOLDER_SUMMARIES = {"...", "…", "En attente du briefing...", ""}

CATEGORY_COLORS = {
    'Politique Afrique': '#1d4ed8',
    'International': '#7c3aed',
    'Finance & Crypto': '#047857',
    'Écologie politique': '#15803d',
}


def category_color(name):
    return CATEGORY_COLORS.get(name, '#1d4ed8')


def slugify(text):
    import unicodedata
    text = unicodedata.normalize('NFKD', (text or '').lower())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-') or 'categorie'


def clean_text(raw):
    """Nettoie un contenu potentiellement HTML/markdown : jamais de balises brutes."""
    if not raw:
        return ''
    text = str(raw)
    # Clôtures markdown (```html ... ```) renvoyées parfois par l'IA
    text = re.sub(r'```+\s*html\s*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'```+', ' ', text)
    # Retire scripts/styles
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    # <br>, </p>, </li>, </h1..h6> -> espaces/points
    text = re.sub(r'</(p|div|h[1-6]|li|ul|ol|br)[^>]*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    # Retire toutes les balises restantes
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_lib.unescape(text)
    # Retire markdown résiduel
    text = re.sub(r'[#>*_`~]+', ' ', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Artefact "html L'Essentiel" : préfixe parasite
    text = re.sub(r'^\s*html\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def excerpt(text, length=160):
    text = clean_text(text)
    if len(text) <= length:
        return text
    cut = text[:length].rsplit(' ', 1)[0]
    return cut + '…'


def briefing_blocks(raw):
    """Découpe un briefing IA en blocs propres (titre/para/liste) pour affichage structuré.

    Retourne une liste de (kind, value) où kind vaut 'h', 'p' ou 'ul'
    (value = texte, ou liste de textes pour 'ul'). Aucun HTML brut,
    aucune clôture markdown ne subsiste.
    """
    if not raw:
        return []
    text = str(raw)
    # Clôtures markdown éventuelles (```html ... ```)
    text = re.sub(r'```+\s*html\s*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'```+', ' ', text)
    text = re.sub(r'^\s*html\s+', '', text, flags=re.IGNORECASE)

    token_re = re.compile(
        r'<h3[^>]*>(.*?)</h3>|<p[^>]*>(.*?)</p>|<li[^>]*>(.*?)</li>|<a[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE)
    blocks = []
    current_ul = []

    def flush_ul():
        if current_ul:
            blocks.append(('ul', list(current_ul)))
            current_ul.clear()

    def push_paragraphs(blob):
        cleaned = clean_text(re.sub(r'</?(ul|ol|div|br)[^>]*>', ' ', blob, flags=re.IGNORECASE))
        for para in [p.strip('` \t') for p in cleaned.split('\n') if p.strip('` \t')]:
            flush_ul()
            blocks.append(('p', para))

    pos = 0
    for m in token_re.finditer(text):
        push_paragraphs(text[pos:m.start()])
        h, p, li, a = m.group(1), m.group(2), m.group(3), m.group(4)
        if h is not None:
            t = clean_text(h).strip('` \t')
            flush_ul()
            if t:
                blocks.append(('h', t))
        elif p is not None:
            for para in [x.strip('` \t') for x in clean_text(p).split('\n') if x.strip('` \t')]:
                flush_ul()
                blocks.append(('p', para))
        elif li is not None:
            t = clean_text(li).strip('` \t')
            if t:
                current_ul.append(t)
        elif a is not None:
            t = clean_text(a).strip('` \t')
            if t:
                flush_ul()
                blocks.append(('p', t))
        pos = m.end()
    push_paragraphs(text[pos:])
    flush_ul()
    return blocks


def source_domain(url):
    try:
        netloc = urlparse(url or '').netloc.lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        return netloc or 'Source'
    except Exception:
        return 'Source'


def time_ago(dt):
    if not dt:
        return ''
    try:
        now = datetime.utcnow()
        # sqlite peut renvoyer des strings
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.split('.')[0])
        delta = now - dt
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 60:
            return "à l'instant"
        minutes = seconds // 60
        if minutes < 60:
            return f"il y a {minutes} min"
        hours = minutes // 60
        if hours < 24:
            return f"il y a {hours} h"
        days = hours // 24
        if days == 1:
            return "hier"
        if days < 7:
            return f"il y a {days} j"
        return dt.strftime('%d/%m/%Y') if hasattr(dt, 'strftime') else ''
    except Exception:
        return ''


def serialize_article(a):
    title = clean_text(getattr(a, 'title', ''))
    raw_summary = getattr(a, 'summary', '') or ''
    summary = clean_text(raw_summary) if raw_summary.strip() not in PLACEHOLDER_SUMMARIES else ''
    url = getattr(a, 'original_url', '#') or '#'
    return {
        'id': getattr(a, 'id', None),
        'title': title,
        'title_short': (title[:110].rsplit(' ', 1)[0] + '…') if len(title) > 110 else title,
        'summary': summary,
        'summary_short': excerpt(summary, 140) if summary else '',
        'url': url,
        'domain': source_domain(url),
        'image_url': (getattr(a, 'image_url', None) or '').strip() or None,
        'pub_date': getattr(a, 'pub_date', None),
        'time_ago': time_ago(getattr(a, 'pub_date', None)),
        'category_id': getattr(a, 'category_id', None),
    }

# 1. Page d'accueil
@main.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('main.login'))

# 2. Login
@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            if user.is_approved:
                login_user(user)
                return redirect(url_for('main.dashboard'))
            else:
                flash('Votre compte est en attente de validation.', 'warning')
        else:
            flash('Email ou mot de passe incorrect.', 'danger')

    return render_template('login.html')

# 3. Inscription
@main.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Cet email existe déjà.', 'danger')
            return redirect(url_for('main.register'))
        
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, username=username, password=hashed_password, is_approved=False)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Compte créé ! Attendez la validation de l\'admin.', 'success')
        return redirect(url_for('main.login'))

    return render_template('register.html')

# 4. Dashboard (C'est ici qu'on gère le Ruban Flash)
@main.route('/dashboard')
@login_required
def dashboard():
    # A. Récupérer les Briefings (logique inchangée)
    categories = Category.query.all()
    briefings = {}
    briefing_excerpts = {}
    for cat in categories:
        last_briefing = DailyBriefing.query.filter_by(category_id=cat.id).order_by(DailyBriefing.date.desc()).first()
        if last_briefing:
            briefings[cat.name] = last_briefing
            briefing_excerpts[cat.name] = excerpt(last_briefing.content, 220)

    # B. Ruban Flash : version structurée (propre, sans HTML concaténé) + chaîne legacy
    flash_items = []
    flash_messages = []
    for cat in categories:
        # On cherche le dernier flash pour cette catégorie
        try:
            last_f = CategoryFlash.query.filter_by(category_id=cat.id).order_by(CategoryFlash.date.desc()).first()
            if last_f:
                clean = clean_text(last_f.content)
                if clean:
                    flash_items.append({
                        'category': cat.name,
                        'category_slug': slugify(cat.name),
                        'color': category_color(cat.name),
                        'content': clean,
                        'content_short': excerpt(clean, 140),
                        'date': last_f.date,
                        'time_ago': time_ago(last_f.date),
                    })
                    # Chaîne legacy conservée pour compatibilité
                    msg = f"<span class='text-warning fw-bold' style='margin-left:20px'>🔴 {cat.name.upper()} :</span> {clean}"
                    flash_messages.append(msg)
        except Exception as e:
            print(f"Erreur Flash pour {cat.name}: {e}")

    # On colle tous les messages bout à bout
    if flash_messages:
        full_flash_string = "   ".join(flash_messages)
    else:
        full_flash_string = "En attente des dernières nouvelles..."

    # B2. Articles récents par catégorie (données existantes, jamais inventées)
    articles_by_category = {}
    category_meta = []
    for cat in categories:
        recent = (Article.query
                  .filter_by(category_id=cat.id)
                  .order_by(Article.pub_date.desc())
                  .limit(6).all())
        serialized = [serialize_article(a) for a in recent]
        articles_by_category[cat.name] = serialized
        category_meta.append({
            'id': cat.id,
            'name': cat.name,
            'slug': slugify(cat.name),
            'color': category_color(cat.name),
            'count': len(serialized),
            'briefing_excerpt': briefing_excerpts.get(cat.name, ''),
            'briefing_date': briefings[cat.name].date if cat.name in briefings else None,
        })

    # B3. Section "À la une" : les 3 articles les plus récents toutes catégories
    hero_main = None
    hero_secondary = []
    try:
        latest = (Article.query.order_by(Article.pub_date.desc()).limit(3).all())
        serialized_latest = [serialize_article(a) for a in latest]
        # Enrichir avec le nom de catégorie
        cat_by_id = {c.id: c.name for c in categories}
        for s in serialized_latest:
            s['category_name'] = cat_by_id.get(s['category_id'], '')
            s['category_color'] = category_color(s['category_name'])
            s['category_slug'] = slugify(s['category_name'])
        if serialized_latest:
            hero_main = serialized_latest[0]
            hero_secondary = serialized_latest[1:3]
    except Exception as e:
        print(f"Erreur hero: {e}")

    # C. Finance (logique inchangée + sparklines compactes)
    market_data = []
    tickers = MarketTicker.query.filter_by(is_active=True).all()
    for t in tickers:
        try:
            data = yf.Ticker(t.symbol)
            hist = data.history(period="5d")
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                prev = hist['Open'].iloc[-1]
                change = ((current - prev) / prev) * 100
                closes = [round(float(x), 2) for x in hist['Close'].iloc[-12:].tolist()]
                market_data.append({
                    'name': t.name,
                    'price': round(float(current), 2),
                    'change': round(float(change), 2),
                    'symbol': t.symbol,
                    'spark': closes,
                })
        except Exception:
            pass

    # On envoie tout au template
    return render_template('dashboard.html',
                         user=current_user,
                         categories=categories,
                         category_meta=category_meta,
                         briefings=briefings,
                         briefing_excerpts=briefing_excerpts,
                         briefing_blocks_map={name: briefing_blocks(b.content) for name, b in briefings.items()},
                         articles_by_category=articles_by_category,
                         hero_main=hero_main,
                         hero_secondary=hero_secondary,
                         market_data=market_data,
                         flash_items=flash_items,
                         flash_info=full_flash_string)


@main.route('/categorie/<int:category_id>')
@login_required
def category_page(category_id):
    """Page 'Voir tout' d'une catégorie : tous les articles récents + briefing."""
    cat = Category.query.get_or_404(category_id)
    articles = (Article.query
                .filter_by(category_id=cat.id)
                .order_by(Article.pub_date.desc())
                .limit(30).all())
    serialized = [serialize_article(a) for a in articles]
    for s in serialized:
        s['category_name'] = cat.name
        s['category_color'] = category_color(cat.name)
    last_briefing = (DailyBriefing.query.filter_by(category_id=cat.id)
                     .order_by(DailyBriefing.date.desc()).first())
    briefing_ex = excerpt(last_briefing.content, 400) if last_briefing else ''
    return render_template('category.html',
                           user=current_user,
                           category=cat,
                           category_color=category_color(cat.name),
                           category_slug=slugify(cat.name),
                           articles=serialized,
                           briefing=last_briefing,
                           briefing_blocks=briefing_blocks(last_briefing.content) if last_briefing else [],
                           briefing_excerpt=briefing_ex)

# 5. Force Scrape
@main.route('/force-scrape')
@login_required
def force_scrape():
    if not current_user.is_admin:
        flash("Action réservée aux admins.", "danger")
        return redirect(url_for('main.dashboard'))
    
    def task(app_context):
        try:
            with app_context.app_context():
                run_scraper(app_context)
        except Exception as e:
            print(f"Erreur background : {e}")

    app = current_app._get_current_object()
    thread = threading.Thread(target=task, args=(app,))
    thread.start()
    
    flash("Le robot a démarré en arrière-plan ! Le ruban se mettra à jour dans quelques minutes.", "info")
    return redirect(url_for('main.dashboard'))

# 6. Admin Panel
@main.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash("Accès interdit.", "danger")
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_source':
            name = request.form.get('name')
            url = request.form.get('url')
            cat_id = request.form.get('category_id')
            if name and url and cat_id:
                new_source = Source(name=name, url=url, category_id=cat_id)
                db.session.add(new_source)
                db.session.commit()
                flash(f"Source '{name}' ajoutée !", "success")

        elif action == 'add_category':
            name = request.form.get('name')
            if name:
                existing = Category.query.filter_by(name=name).first()
                if not existing:
                    new_cat = Category(name=name)
                    db.session.add(new_cat)
                    db.session.commit()
                    flash(f"Catégorie '{name}' créée !", "success")
                else:
                    flash("Cette catégorie existe déjà.", "warning")

        elif action == 'add_ticker':
            symbol = request.form.get('symbol')
            name = request.form.get('name')
            if symbol and name:
                new_ticker = MarketTicker(symbol=symbol, name=name, type='stock')
                db.session.add(new_ticker)
                db.session.commit()
                flash(f"Ticker '{symbol}' ajouté !", "success")

        elif action == 'delete_source':
            s_id = request.form.get('id')
            Source.query.filter_by(id=s_id).delete()
            db.session.commit()
        elif action == 'delete_ticker':
            t_id = request.form.get('id')
            MarketTicker.query.filter_by(id=t_id).delete()
            db.session.commit()

        return redirect(url_for('main.admin_panel'))

    sources = Source.query.all()
    tickers = MarketTicker.query.all()
    categories = Category.query.all()
    
    return render_template('admin.html', user=current_user, sources=sources, tickers=tickers, categories=categories)

# 7. Logout
@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))
