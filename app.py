import os
import re
import qrcode
from io import BytesIO
import base64
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import vobject

# ============================================
# CONFIGURATION FLASK
# ============================================
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///profils.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# ✅ SÉCURITÉ: Mot de passe admin
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH') or generate_password_hash('admin123')

# Créer dossier uploads
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# ============================================
# MODÈLES
# ============================================
class Profil(db.Model):
    __tablename__ = 'profils'
    
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(150), nullable=False)
    titre = db.Column(db.String(100))
    biographie = db.Column(db.Text)
    email = db.Column(db.String(120))
    telephone = db.Column(db.String(20))
    photo_url = db.Column(db.String(200))
    
    # Positions photo (0-100)
    photo_position_x = db.Column(db.Integer, default=50)
    photo_position_y = db.Column(db.Integer, default=50)
    
    # Couleurs personnalisables
    couleur_principale = db.Column(db.String(7), default='#007bff')
    couleur_fond = db.Column(db.String(7), default='#ffffff')
    couleur_texte_h1 = db.Column(db.String(7), default='#000000')
    couleur_texte_bio = db.Column(db.String(7), default='#666666')
    
    # ✅ PARAMÈTRES AVANCÉS
    theme = db.Column(db.String(20), default='light')  # light / dark
    animations = db.Column(db.Boolean, default=True)
    layout = db.Column(db.String(20), default='vertical')  # vertical / horizontal
    template = db.Column(db.String(50), default='modern')  # modern / classic / minimal / gradient / glassmorphism
    
    # ✅ SÉCURITÉ
    is_protected = db.Column(db.Boolean, default=False)
    profil_password = db.Column(db.String(255), nullable=True)
    
    # ✅ ANALYTICS
    view_count = db.Column(db.Integer, default=0)
    
    # ✅ WEBHOOKS
    webhook_url = db.Column(db.String(500), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    liens = db.relationship('Lien', backref='profil', lazy=True, cascade='all, delete-orphan')
    analytics = db.relationship('Analytics', backref='profil', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Profil {self.nom}>'


class Lien(db.Model):
    __tablename__ = 'liens'
    
    id = db.Column(db.Integer, primary_key=True)
    profil_id = db.Column(db.Integer, db.ForeignKey('profils.id'), nullable=False)
    type_lien = db.Column(db.String(50), nullable=False)
    nom = db.Column(db.String(100))
    url = db.Column(db.String(500), nullable=False)
    link_order = db.Column(db.Integer, default=0)
    click_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Lien {self.type_lien}>'


class Analytics(db.Model):
    __tablename__ = 'analytics'
    
    id = db.Column(db.Integer, primary_key=True)
    profil_id = db.Column(db.Integer, db.ForeignKey('profils.id'), nullable=False)
    lien_id = db.Column(db.Integer, db.ForeignKey('liens.id'), nullable=True)
    event_type = db.Column(db.String(50))  # view, click
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Analytics {self.event_type}>'

# ============================================
# FONCTIONS UTILITAIRES
# ============================================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def validate_hex_color(color):
    if not color or not isinstance(color, str):
        return False
    return bool(re.match(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$', color))

def validate_email(email):
    if not email:
        return True
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def validate_phone(phone):
    if not phone:
        return True
    return bool(re.match(r'^\+?1?\d{9,15}$', phone.replace(' ', '').replace('-', '')))

def generate_slug(name):
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    return slug

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def send_webhook(profil, event_type, data=None):
    """Envoie un webhook quand un événement se produit"""
    if not profil.webhook_url:
        return
    
    try:
        import requests
        payload = {
            'event': event_type,
            'profil_slug': profil.slug,
            'timestamp': datetime.utcnow().isoformat(),
            'data': data or {}
        }
        requests.post(profil.webhook_url, json=payload, timeout=5)
    except Exception as e:
        app.logger.error(f'Webhook error: {str(e)}')

# ============================================
# ROUTES PUBLIQUES
# ============================================
@app.route('/')
def index():
    """Page d'accueil"""
    profils = Profil.query.limit(10).all()
    return render_template('index.html', profils=profils)

@app.route('/profil/<slug_profil>')
def profil_public(slug_profil):
    """Afficher un profil public"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    # Vérifier si protégé
    if profil.is_protected and session.get(f'profil_{profil.id}_unlocked') != True:
        return redirect(url_for('unlock_profil', slug_profil=slug_profil))
    
    # Enregistrer la vue
    view_event = Analytics(profil_id=profil.id, event_type='view')
    db.session.add(view_event)
    db.session.commit()
    
    liens = Lien.query.filter_by(profil_id=profil.id).order_by(Lien.link_order).all()
    template_name = f'profil_templates/{profil.template}.html'
    
    return render_template('profil_public.html', 
                         profil=profil, 
                         liens=liens,
                         template_name=template_name)

@app.route('/profil/<slug_profil>/unlock', methods=['GET', 'POST'])
def unlock_profil(slug_profil):
    """Déverrouiller un profil protégé"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    if not profil.is_protected:
        return redirect(url_for('profil_public', slug_profil=slug_profil))
    
    if request.method == 'POST':
        password = request.form.get('password')
        if profil.profil_password and check_password_hash(profil.profil_password, password):
            session[f'profil_{profil.id}_unlocked'] = True
            return redirect(url_for('profil_public', slug_profil=slug_profil))
        else:
            flash('❌ Mot de passe incorrect', 'danger')
    
    return render_template('profil_unlock.html', slug_profil=slug_profil)

@app.route('/click/<int:lien_id>')
def track_click(lien_id):
    """Enregistre un clic et redirige"""
    lien = Lien.query.get_or_404(lien_id)
    
    # Enregistrer le clic
    analytics = Analytics(
        profil_id=lien.profil_id,
        lien_id=lien_id,
        event_type='click',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')
    )
    db.session.add(analytics)
    lien.click_count += 1
    db.session.commit()
    
    # Envoyer webhook
    send_webhook(lien.profil, 'link_clicked', {'lien_id': lien_id, 'url': lien.url})
    
    return redirect(lien.url)

@app.route('/qr/<slug_profil>')
def qr_code_generator(slug_profil):
    """Génère un QR code"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    profile_url = request.url_root.rstrip('/') + url_for('profil_public', slug_profil=profil.slug)
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(profile_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color='black', back_color='white')
    img_io = BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    return send_file(img_io, mimetype='image/png')

@app.route('/vcard/<slug_profil>')
def vcard(slug_profil):
    """Télécharge la vCard"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    vcard = vobject.vCard()
    vcard.add('fn')
    vcard.fn.value = profil.nom or 'Contact'
    
    if profil.titre:
        vcard.add('title')
        vcard.title.value = profil.titre
    
    if profil.email:
        vcard.add('email')
        vcard.email.value = profil.email
        vcard.email.type_param = 'INTERNET'
    
    if profil.telephone:
        vcard.add('tel')
        vcard.tel.value = profil.telephone
        vcard.tel.type_param = 'CELL'
    
    if profil.biographie:
        vcard.add('note')
        vcard.note.value = profil.biographie[:500]
    
    vcard.add('url')
    vcard.url.value = request.url_root.rstrip('/') + url_for('profil_public', slug_profil=profil.slug)
    
    response_data = vcard.serialize()
    
    return send_file(
        BytesIO(response_data.encode('utf-8')),
        mimetype='text/vcard',
        as_attachment=True,
        download_name=f'{profil.slug}.vcf'
    )

# ============================================
# ROUTES ADMIN - AUTHENTIFICATION
# ============================================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Connexion admin"""
    if request.method == 'POST':
        password = request.form.get('password', '')
        
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin_logged_in'] = True
            flash('✅ Connexion réussie !', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('❌ Mot de passe incorrect', 'danger')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    """Déconnexion"""
    session.clear()
    flash('👋 Déconnecté avec succès', 'info')
    return redirect(url_for('index'))

# ============================================
# ROUTES ADMIN - GESTION PROFILS
# ============================================
@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Tableau de bord"""
    profils = Profil.query.order_by(Profil.updated_at.desc()).all()
    return render_template('admin/dashboard.html', profils=profils)

@app.route('/admin/profil/nouveau', methods=['GET', 'POST'])
@admin_required
def create_profil():
    """Créer un nouveau profil"""
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        
        if not nom:
            flash('❌ Le nom est requis', 'danger')
            return render_template('admin/create_profil.html')
        
        email = request.form.get('email', '').strip()
        if email and not validate_email(email):
            flash('❌ Email invalide', 'danger')
            return render_template('admin/create_profil.html')
        
        telephone = request.form.get('telephone', '').strip()
        if telephone and not validate_phone(telephone):
            flash('❌ Téléphone invalide', 'danger')
            return render_template('admin/create_profil.html')
        
        slug = generate_slug(nom)
        
        if Profil.query.filter_by(slug=slug).first():
            flash('❌ Ce nom existe déjà', 'danger')
            return render_template('admin/create_profil.html')
        
        profil = Profil(
            slug=slug,
            nom=nom,
            titre=request.form.get('titre', '').strip(),
            biographie=request.form.get('biographie', '').strip(),
            email=email,
            telephone=telephone,
            couleur_principale=request.form.get('couleur_principale', '#007bff'),
            couleur_fond=request.form.get('couleur_fond', '#ffffff'),
            couleur_texte_h1=request.form.get('couleur_texte_h1', '#000000'),
            couleur_texte_bio=request.form.get('couleur_texte_bio', '#666666'),
            template=request.form.get('template', 'modern'),
        )
        
        db.session.add(profil)
        db.session.commit()
        
        flash('✅ Profil créé avec succès !', 'success')
        send_webhook(profil, 'profile_created')
        return redirect(url_for('edit_profil', slug_profil=profil.slug))
    
    return render_template('admin/create_profil.html')

@app.route('/admin/profil/<slug_profil>/editer', methods=['GET', 'POST'])
@admin_required
def edit_profil(slug_profil):
    """Éditer un profil"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    if request.method == 'POST':
        profil.nom = request.form.get('nom', profil.nom).strip()
        profil.titre = request.form.get('titre', '').strip()
        profil.biographie = request.form.get('biographie', '').strip()
        
        email = request.form.get('email', '').strip()
        if email and not validate_email(email):
            flash('❌ Email invalide', 'danger')
            return render_template('admin/edit_profil.html', profil=profil)
        profil.email = email
        
        telephone = request.form.get('telephone', '').strip()
        if telephone and not validate_phone(telephone):
            flash('❌ Téléphone invalide', 'danger')
            return render_template('admin/edit_profil.html', profil=profil)
        profil.telephone = telephone
        
        # Couleurs
        for color_field in ['couleur_principale', 'couleur_fond', 'couleur_texte_h1', 'couleur_texte_bio']:
            color = request.form.get(color_field, '').strip()
            if color and validate_hex_color(color):
                setattr(profil, color_field, color)
        
        # Positions photo
        try:
            x = int(str(request.form.get('photo_position_x', 50)).rstrip('%'))
            y = int(str(request.form.get('photo_position_y', 50)).rstrip('%'))
            profil.photo_position_x = max(0, min(100, x))
            profil.photo_position_y = max(0, min(100, y))
        except (ValueError, TypeError):
            pass
        
        # Photo
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{profil.slug}_{datetime.utcnow().timestamp()}.{file.filename.rsplit('.', 1)[1].lower()}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                profil.photo_url = f'/static/uploads/{filename}'
        
        profil.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash('✅ Profil mis à jour !', 'success')
        send_webhook(profil, 'profile_updated')
        return render_template('admin/edit_profil.html', profil=profil)
    
    return render_template('admin/edit_profil.html', profil=profil)

@app.route('/admin/profil/<slug_profil>/supprimer', methods=['POST'])
@admin_required
def delete_profil(slug_profil):
    """Supprimer un profil"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    nom = profil.nom
    db.session.delete(profil)
    db.session.commit()
    
    flash(f'✅ Profil "{nom}" supprimé', 'success')
    return redirect(url_for('admin_dashboard'))

# ============================================
# ROUTES ADMIN - GESTION LIENS
# ============================================
@app.route('/admin/liens/<slug_profil>', methods=['GET'])
@admin_required
def manage_liens(slug_profil):
    """Page de gestion des liens avec drag & drop"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    liens = Lien.query.filter_by(profil_id=profil.id).order_by(Lien.link_order).all()
    return render_template('admin/manage_liens.html', profil=profil, liens=liens)

@app.route('/admin/profil/<int:profil_id>/lien', methods=['POST'])
@admin_required
def add_lien(profil_id):
    """Ajouter un lien"""
    profil = Profil.query.get_or_404(profil_id)
    
    type_lien = request.form.get('type_lien', '').strip()
    url = request.form.get('url', '').strip()
    nom = request.form.get('nom', type_lien).strip()
    
    if not url.startswith(('http://', 'https://', 'mailto:', 'tel:')):
        url = 'https://' + url
    
    lien = Lien(
        profil_id=profil_id,
        type_lien=type_lien,
        nom=nom,
        url=url,
        link_order=Lien.query.filter_by(profil_id=profil_id).count()
    )
    
    db.session.add(lien)
    db.session.commit()
    
    flash(f'✅ Lien {type_lien} ajouté', 'success')
    send_webhook(profil, 'link_added', {'type': type_lien})
    return redirect(url_for('manage_liens', slug_profil=profil.slug))

@app.route('/admin/lien/<int:lien_id>/update', methods=['POST'])
@admin_required
def update_lien(lien_id):
    """Mettre à jour un lien"""
    lien = Lien.query.get_or_404(lien_id)
    
    lien.nom = request.form.get('nom', lien.nom).strip()
    lien.type_lien = request.form.get('type_lien', lien.type_lien).strip()
    url = request.form.get('url', lien.url).strip()
    
    if not url.startswith(('http://', 'https://', 'mailto:', 'tel:')):
        url = 'https://' + url
    
    lien.url = url
    db.session.commit()
    
    flash('✅ Lien mis à jour', 'success')
    return redirect(url_for('manage_liens', slug_profil=lien.profil.slug))

@app.route('/admin/lien/<int:lien_id>/supprimer', methods=['POST'])
@admin_required
def delete_lien(lien_id):
    """Supprimer un lien"""
    lien = Lien.query.get_or_404(lien_id)
    profil_slug = lien.profil.slug
    db.session.delete(lien)
    db.session.commit()
    
    flash('✅ Lien supprimé', 'success')
    return redirect(url_for('manage_liens', slug_profil=profil_slug))

@app.route('/admin/liens/reorder', methods=['POST'])
@admin_required
def reorder_liens():
    """Réordonner les liens (drag & drop)"""
    data = request.get_json()
    link_ids = data.get('link_ids', [])
    
    for index, link_id in enumerate(link_ids):
        lien = Lien.query.get(link_id)
        if lien:
            lien.link_order = index
    
    db.session.commit()
    return jsonify({'success': True})

# ============================================
# ROUTES ADMIN - PARAMÈTRES AVANCÉS
# ============================================
@app.route('/admin/profil/<slug_profil>/parametres', methods=['GET', 'POST'])
@admin_required
def parametres_profil(slug_profil):
    """Paramètres avancés du profil"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    if request.method == 'POST':
        profil.theme = request.form.get('theme', 'light')
        profil.animations = request.form.get('animations') == 'on'
        profil.layout = request.form.get('layout', 'vertical')
        profil.template = request.form.get('template', 'modern')
        profil.webhook_url = request.form.get('webhook_url', '').strip() or None
        
        # Sécurité - Protection par mot de passe
        if request.form.get('is_protected') == 'on':
            profil.is_protected = True
            new_password = request.form.get('profil_password', '')
            if new_password:
                profil.profil_password = generate_password_hash(new_password)
        else:
            profil.is_protected = False
            profil.profil_password = None
        
        db.session.commit()
        flash('✅ Paramètres sauvegardés', 'success')
        send_webhook(profil, 'settings_updated')
        return redirect(url_for('parametres_profil', slug_profil=slug_profil))
    
    return render_template('admin/parametres_profil.html', profil=profil)

# ============================================
# ROUTES ADMIN - LIVE PREVIEW
# ============================================
@app.route('/admin/profil/<slug_profil>/live-preview')
@admin_required
def live_preview(slug_profil):
    """Aperçu en temps réel du profil"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    liens = Lien.query.filter_by(profil_id=profil.id).order_by(Lien.link_order).all()
    return render_template('admin/live_preview.html', profil=profil, liens=liens)

# ============================================
# ROUTES ADMIN - ANALYTICS
# ============================================
@app.route('/admin/profil/<slug_profil>/analytics')
@admin_required
def analytics_profil(slug_profil):
    """Statistiques du profil"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    # Vues totales
    view_count = Analytics.query.filter_by(profil_id=profil.id, event_type='view').count()
    
    # Clics par lien
    liens_with_clicks = []
    for lien in profil.liens:
        click_count = Analytics.query.filter_by(lien_id=lien.id, event_type='click').count()
        liens_with_clicks.append({
            'id': lien.id,
            'nom': lien.nom,
            'url': lien.url,
            'clicks': click_count
        })
    
    # 30 derniers jours
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_views = Analytics.query.filter_by(
        profil_id=profil.id, 
        event_type='view'
    ).filter(Analytics.created_at >= thirty_days_ago).count()
    
    # Données pour graphique (7 derniers jours)
    chart_data = {}
    for i in range(7, -1, -1):
        date = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
        views = Analytics.query.filter_by(profil_id=profil.id, event_type='view').filter(
            Analytics.created_at >= datetime.strptime(date, '%Y-%m-%d'),
            Analytics.created_at < datetime.strptime(date, '%Y-%m-%d') + timedelta(days=1)
        ).count()
        chart_data[date] = views
    
    return render_template('admin/analytics_profil.html', 
                         profil=profil, 
                         view_count=view_count,
                         liens_with_clicks=liens_with_clicks,
                         recent_views=recent_views,
                         chart_data=chart_data)

# ============================================
# ROUTES ADMIN - EXPORT
# ============================================
@app.route('/admin/profil/<slug_profil>/qr-download')
@admin_required
def qr_download(slug_profil):
    """Télécharge le QR code"""
    profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
    
    profile_url = request.url_root.rstrip('/') + url_for('profil_public', slug_profil=profil.slug)
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(profile_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color='black', back_color='white')
    img_io = BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    return send_file(
        img_io,
        mimetype='image/png',
        as_attachment=True,
        download_name=f'qr_{profil.slug}.png'
    )

@app.route('/admin/profil/<slug_profil>/export-pdf')
@admin_required
def export_pdf(slug_profil):
    """Exporte le profil en PDF"""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        
        profil = Profil.query.filter_by(slug=slug_profil).first_or_404()
        
        # Créer le PDF
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
        elements = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor(profil.couleur_principale),
            spaceAfter=30,
        )
        
        # Titre
        elements.append(Paragraph(profil.nom, title_style))
        
        if profil.titre:
            elements.append(Paragraph(f"<i>{profil.titre}</i>", styles['Heading3']))
        
        elements.append(Spacer(1, 0.3*inch))
        
        # Info contact
        contact_info = []
        if profil.email:
            contact_info.append(f"📧 Email: {profil.email}")
        if profil.telephone:
            contact_info.append(f"📞 Tél: {profil.telephone}")
        
        for info in contact_info:
            elements.append(Paragraph(info, styles['Normal']))
        
        elements.append(Spacer(1, 0.3*inch))
        
        # Biographie
        if profil.biographie:
            elements.append(Paragraph("<b>Biographie</b>", styles['Heading3']))
            elements.append(Paragraph(profil.biographie, styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
        
        # Liens
        if profil.liens:
            elements.append(Paragraph("<b>Liens</b>", styles['Heading3']))
            for lien in profil.liens:
                elements.append(Paragraph(f"• {lien.nom}: {lien.url}", styles['Normal']))
        
        doc.build(elements)
        pdf_buffer.seek(0)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'{profil.slug}.pdf'
        )
    except ImportError:
        flash('❌ ReportLab non installé. Installez: pip install reportlab', 'danger')
        return redirect(url_for('edit_profil', slug_profil=slug_profil))

# ============================================
# GESTION ERREURS
# ============================================
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(error):
    return render_template('500.html'), 500

# ============================================
# INITIALISATION
# ============================================
# ...existing code...

# ============================================
# INITIALISATION
# ============================================
if __name__ == '__main__':
    with app.app_context():
        # ✅ FORCER LA CRÉATION DE TOUTES LES TABLES
        print("🔄 Initialisation de la base de données...")
        db.drop_all()  # ⚠️ SUPPRIMER TOUT
        db.create_all()  # Créer les tables avec les bonnes colonnes
        print("✅ Base de données initialisée avec succès!")
    
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)