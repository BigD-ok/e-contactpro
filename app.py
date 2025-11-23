# app.py

from flask import Flask, render_template, request, redirect, url_for, send_file, session, make_response, jsonify
import qrcode
import io
import os
import json
from werkzeug.utils import secure_filename
import uuid
import re 
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, desc, asc
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base

# --- Configuration des Fichiers et Extensions Autorisées ---
UPLOAD_FOLDER = 'static/uploads'
BACKUP_FOLDER = 'backups' 
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

# --- Configuration de la Base de Données ---
engine = create_engine('sqlite:///profil.db')
Base = declarative_base()
Session = sessionmaker(bind=engine)
session_db = Session() 

# --- Modèles de Base de Données (RÉTABLIS AU MODÈLE FINAL) ---

class Profil(Base):
    __tablename__ = 'profils'
    id = Column(Integer, primary_key=True) 
    slug = Column(String(50), unique=True, default='mon-profil')
    nom = Column(String(100), default='')
    titre = Column(String(100), default='')
    biographie = Column(Text, default='')
    email = Column(String(100), default='')
    telephone = Column(String(50), default='')
    photo_url = Column(String(255), default='')
    couleur_principale = Column(String(7), default='#001F3F')
    couleur_fond = Column(String(7), default='#E9ECEF')
    couleur_texte_h1 = Column(String(7), default='#001F3F')
    couleur_texte_bio = Column(String(7), default='#444444')
    photo_position_x = Column(String(5), default='50%')
    photo_position_y = Column(String(5), default='50%')
    
    liens = relationship("Lien", backref="profil", cascade="all, delete-orphan", order_by="Lien.link_order") 

    def __repr__(self):
        return f"<Profil(nom='{self.nom}', slug='{self.slug}')>"

class Lien(Base):
    __tablename__ = 'liens'

    id = Column(Integer, primary_key=True)
    type_lien = Column(String(50), nullable=False)
    nom = Column(String(50), nullable=False)
    url = Column(String(255), nullable=False)
    link_order = Column(Integer, default=0)
    
    profil_id = Column(Integer, ForeignKey('profils.id'))
    
    def __repr__(self):
        return f"<Lien(nom='{self.nom}', url='{self.url}')>"

# Crée les tables dans la base de données si elles n'existent pas
Base.metadata.create_all(engine)

# Crée le dossier de backup s'il n'existe pas
if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)

# --- Initialisation de l'Application Flask ---
app = Flask(__name__)
app.secret_key = os.urandom(24) 
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BACKUP_FOLDER'] = BACKUP_FOLDER

# --- Fonctions Utiles (Slugs, Backup, Icônes) ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_backup(profil):
    backup_data = {
        'id': profil.id,
        'slug': profil.slug,
        'nom': profil.nom,
        'titre': profil.titre,
        'photo_url': profil.photo_url,
        'couleur_texte_h1': profil.couleur_texte_h1,
        'couleur_texte_bio': profil.couleur_texte_bio,
        'photo_position_x': profil.photo_position_x,
        'photo_position_y': profil.photo_position_y,
        'liens': [{'nom': l.nom, 'url': l.url, 'type': l.type_lien} for l in profil.liens]
    }
    try:
        timestamp = os.path.getmtime(os.path.join(app.root_path, 'profil.db'))
    except FileNotFoundError:
        timestamp = 0 
        
    backup_filename = f"{profil.slug}_{timestamp}.json"
    backup_path = os.path.join(app.config['BACKUP_FOLDER'], backup_filename)

    with open(backup_path, 'w') as f:
        json.dump(backup_data, f, indent=4)

def slugify(text):
    if not text:
        return 'default-' + uuid.uuid4().hex[:8]
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    return text

def get_or_create_profil(slug_name):
    profil = session_db.query(Profil).filter_by(slug=slug_name).first()
    
    if not profil:
        profil = Profil(
            slug=slug_name,
            nom="",
            titre="",
            biographie="",
            email="",
            telephone="",
            photo_url='',
            couleur_principale='#001F3F',
            couleur_fond='#E9ECEF',
            couleur_texte_h1='#001F3F',
            couleur_texte_bio='#444444'
        )
        session_db.add(profil)
        session_db.commit()
    return profil

def get_icon(link_type):
    icons = {
        'LinkedIn': 'icons/linkedin.png',
        'YouTube': 'icons/youtube.png',
        'X': 'icons/x.png',
        'Twitter': 'icons/x.png', 
        'Instagram': 'icons/instagram.png',
        'Linktree': 'icons/linktree.png',
        'Autre': 'icons/globe.png'
    }
    path = icons.get(link_type, icons['Autre'])
    return url_for('static', filename=path) 
app.jinja_env.globals.update(get_icon=get_icon) 

# --- Routes Flask (RÉTABLIES) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion pour accéder à l'édition."""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'monmotdepasse123': 
            session['logged_in'] = True
            return redirect(url_for('profiles_list')) 
        else:
            # Assurez-vous que le template 'login.html' est bien présent
            return render_template('login.html', error="Mot de passe incorrect")
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/profiles')
def profiles_list():
    """Affiche la liste de tous les profils pour l'édition et la gestion."""
    
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    all_profiles = session_db.query(Profil).all()
    
    # Assurez-vous que le template 'profiles.html' est bien présent
    return render_template('profiles.html', profiles=all_profiles)

# NOUVELLE ROUTE : Suppression de Profil
@app.route('/profiles/delete/<slug_profil>', methods=['POST'])
def delete_profile(slug_profil):
    """Supprime un profil de la base de données."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    profil = session_db.query(Profil).filter_by(slug=slug_profil).first()
    
    if profil:
        session_db.delete(profil)
        session_db.commit()
    return redirect(url_for('profiles_list'))


@app.route('/edition/<slug_profil>', methods=['GET', 'POST']) 
@app.route('/edition', methods=['GET', 'POST'])
def edition_profil(slug_profil='mon-profil'):
    """Affiche la page d'édition simplifiée des informations (inclut les liens)."""
    
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if slug_profil.startswith('new-'):
        new_slug = 'profile-' + uuid.uuid4().hex[:8]
        profil = get_or_create_profil(new_slug)
        return redirect(url_for('edition_profil', slug_profil=new_slug))
    
    profil = get_or_create_profil(slug_profil) 

    if request.method == 'POST':
        # ... (Logique de sauvegarde) ...
        nouveau_nom = request.form.get('nom')
        nouveau_slug = slugify(nouveau_nom)
        
        if nouveau_slug != profil.slug:
            if session_db.query(Profil).filter(Profil.slug == nouveau_slug, Profil.id != profil.id).first():
                pass
            else:
                profil.slug = nouveau_slug
        
        # Le reste du POST est le code de sauvegarde complet...
        # ... (Logique de gestion de photo et de sauvegarde des champs) ...
        
        session_db.commit()
        create_backup(profil) 

        return redirect(url_for('edition_profil', slug_profil=profil.slug))
    
    all_links = session_db.query(Lien).filter_by(profil_id=profil.id).order_by(Lien.link_order).all() 
    return render_template('edition_profil.html', profil=profil, all_links=all_links)

@app.route('/live-edit/<slug_profil>', methods=['GET', 'POST'])
@app.route('/live-edit', methods=['GET', 'POST'])
def live_edit(slug_profil='mon-profil'):
    """Affiche la page d'édition en direct et gère la sauvegarde du design."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    profil = get_or_create_profil(slug_profil)
    
    # ... (Logique de sauvegarde du POST de live-edit) ...

    all_links = session_db.query(Lien).filter_by(profil_id=profil.id).all()
    return render_template('live_editor.html', profil=profil, all_links=all_links)

@app.route('/gerer_liens', methods=['POST'])
def gerer_liens():
    # ... (Logique de gestion des liens) ...
    
    profil = session_db.query(Profil).filter_by(slug=request.form.get('profil_slug')).first()
    if not profil: return "Erreur: Profil non trouvé", 404
    
    # ... (Logique d'ajout/suppression) ...
    
    return redirect(url_for('edition_profil', slug_profil=profil.slug)) 

# ... (Les autres routes sont omises pour la clarté) ...

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')