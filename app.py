from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_migrate import Migrate
from flask_login import LoginManager, login_required, current_user
from models import db, Event, Ticket, User, TicketType
from accounts.routes import auth
from datetime import datetime, timedelta
import os
import stripe
from werkzeug.utils import secure_filename
from sqlalchemy import func, or_
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import Image
from io import BytesIO
import qrcode
from PIL import Image as PILImage
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from functools import wraps
from flask.cli import with_appcontext
import click
import logging
import re

app = Flask(__name__)

# Configuration de base via variables d'environnement (prêt pour Render)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')

# Render fournit généralement DATABASE_URL pour PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql://event_posgres_user:zPUbs5d9XUQPJ7f4HkNn0BBonXmeTNuM@dpg-d4mofdk9c44c7386rlng-a.oregon-postgres.render.com/event_posgres'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # recommandé pour éviter un warning

# Debug activé seulement en local par variable d'env
app.config['DEBUG'] = os.getenv('FLASK_DEBUG', '0') == '1'
app.config['SQLALCHEMY_ECHO'] = os.getenv('SQLALCHEMY_ECHO', '0') == '1'

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

# Configuration de SQLAlchemy logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)

# Configuration de Stripe via variables d'environnement
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')
app.config['STRIPE_PUBLIC_KEY'] = os.getenv('STRIPE_PUBLIC_KEY', '')

# Configuration pour l'upload d'images
UPLOAD_FOLDER = 'static/uploads/events'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max

# Configuration pour l'upload des fichiers
UPLOAD_FOLDER_IDENTITY = os.path.join('static', 'uploads', 'identity_docs')
ALLOWED_EXTENSIONS_IDENTITY = {'png', 'jpg', 'jpeg', 'pdf'}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB max

app.config['UPLOAD_FOLDER_IDENTITY'] = UPLOAD_FOLDER_IDENTITY
app.config['MAX_CONTENT_LENGTH_IDENTITY'] = MAX_CONTENT_LENGTH

# Créer le dossier d'upload s'il n'existe pas
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_file_identity(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS_IDENTITY

# Initialisation de la base de données
db.init_app(app)
migrate = Migrate(app, db)

# Initialisation de Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Enregistrement du blueprint d'authentification
app.register_blueprint(auth, url_prefix='/auth')

# Décorateur pour vérifier si l'utilisateur est admin
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Accès non autorisé. Vous devez être administrateur.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Décorateur pour vérifier si l'utilisateur est organisateur
def organizer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not (current_user.is_organizer() or current_user.is_admin()):
            flash('Accès non autorisé. Vous devez être organisateur.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    # Récupérer les paramètres de filtrage
    search = request.args.get('search', '')
    event_type = request.args.get('type', '')
    location = request.args.get('location', '')
    price_sort = request.args.get('price_sort', '')
    status = request.args.get('status', '')  # Nouveau paramètre pour le statut

    # Construire la requête de base
    query = Event.query

    # Appliquer les filtres
    if search:
        query = query.filter(
            or_(
                Event.title.ilike(f'%{search}%'),
                Event.description.ilike(f'%{search}%')
            )
        )
    
    if event_type:
        query = query.filter(Event.event_type == event_type)
    
    if location:
        query = query.filter(Event.location == location)

    # Filtrer par statut
    now = datetime.now()
    if status == 'upcoming':
        query = query.filter(Event.date > now)
    elif status == 'ongoing':
        query = query.filter(Event.date <= now, Event.date + timedelta(hours=24) >= now)
    elif status == 'past':
        query = query.filter(Event.date + timedelta(hours=24) < now)

    # Récupérer les types d'événements et lieux uniques pour les filtres
    event_types = db.session.query(Event.event_type).distinct().all()
    event_types = [t[0] for t in event_types]
    
    locations = db.session.query(Event.location).distinct().all()
    locations = [l[0] for l in locations]

    # Appliquer le tri par prix si demandé
    if price_sort == 'asc':
        query = query.order_by(Event.ticket_types.any(TicketType.price.asc()))
    elif price_sort == 'desc':
        query = query.order_by(Event.ticket_types.any(TicketType.price.desc()))
    else:
        # Par défaut, trier par date (les plus récents en premier)
        query = query.order_by(Event.date.desc())

    # Exécuter la requête
    events = query.all()

    return render_template('index.html', 
                         events=events,
                         event_types=event_types,
                         locations=locations)

@app.route('/my-events')
@login_required
def my_events():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    return render_template('my_events.html', events=events)

@app.route('/my-events-list')
@organizer_required
def my_events_list():
    events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()
    now = datetime.now()
    return render_template('my_events_list.html', events=events, now=now, timedelta=timedelta)

@app.route('/event/new', methods=['GET', 'POST'])
@login_required
def new_event():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        event_type = request.form['event_type']
        date = datetime.strptime(request.form['date'], '%Y-%m-%dT%H:%M')
        location = request.form['location']
        ticket_types_count = int(request.form['ticket_types_count'])

        # Gestion de l'upload d'image
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                image_url = f"/static/uploads/events/{filename}"

        # Création de l'événement
        event = Event(
            title=title,
            description=description,
            event_type=event_type,
            date=date,
            location=location,
            image_url=image_url,
            organizer_id=current_user.id
        )
        db.session.add(event)
        db.session.flush()  # Pour obtenir l'ID de l'événement

        # Création des types de tickets
        for i in range(ticket_types_count):
            ticket_type = TicketType(
                event_id=event.id,
                name=request.form[f'ticket_type_name_{i}'],
                price=float(request.form[f'ticket_type_price_{i}']),
                total_quantity=int(request.form[f'ticket_type_quantity_{i}']),
                available_quantity=int(request.form[f'ticket_type_quantity_{i}'])
            )
            db.session.add(ticket_type)

        db.session.commit()
        flash('Événement créé avec succès !', 'success')
        return redirect(url_for('event_detail', event_id=event.id))
    return render_template('new_event.html')

@app.route('/event/<int:event_id>')
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    ticket_types = TicketType.query.filter_by(event_id=event_id).all()
    return render_template('event_detail.html', event=event, ticket_types=ticket_types)

@app.route('/event/<int:event_id>/edit', methods=['GET', 'POST'])
@organizer_required
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        flash('Vous n\'êtes pas autorisé à modifier cet événement.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    if request.method == 'POST':
        event.title = request.form['title']
        event.description = request.form['description']
        event.event_type = request.form['event_type']
        event.date = datetime.strptime(request.form['date'], '%Y-%m-%dT%H:%M')
        event.location = request.form['location']
        
        # Gestion de l'upload d'image
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                if event.image_url:
                    old_image_path = os.path.join(app.root_path, event.image_url.lstrip('/'))
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                event.image_url = f"/static/uploads/events/{filename}"

        # Mise à jour des types de tickets
        ticket_types_count = int(request.form['ticket_types_count'])
        existing_types = TicketType.query.filter_by(event_id=event.id).all()
        
        # Supprimer les types de tickets qui ne sont plus utilisés
        for ticket_type in existing_types:
            if ticket_type.available_quantity < ticket_type.total_quantity:
                flash(f'Impossible de supprimer le type de ticket "{ticket_type.name}" car des tickets ont déjà été vendus.', 'error')
                return redirect(url_for('edit_event', event_id=event.id))
            db.session.delete(ticket_type)

        # Ajouter les nouveaux types de tickets
        for i in range(ticket_types_count):
            ticket_type = TicketType(
                event_id=event.id,
                name=request.form[f'ticket_type_name_{i}'],
                price=float(request.form[f'ticket_type_price_{i}']),
                total_quantity=int(request.form[f'ticket_type_quantity_{i}']),
                available_quantity=int(request.form[f'ticket_type_quantity_{i}'])
            )
            db.session.add(ticket_type)

        db.session.commit()
        flash('Événement mis à jour avec succès !', 'success')
        return redirect(url_for('event_detail', event_id=event.id))

    ticket_types = TicketType.query.filter_by(event_id=event.id).all()
    return render_template('edit_event.html', event=event, ticket_types=ticket_types)

@app.route('/event/<int:event_id>/delete', methods=['POST'])
@organizer_required
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.organizer_id != current_user.id:
        flash('Vous n\'êtes pas autorisé à supprimer cet événement.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    # Vérifier s'il y a des tickets vendus
    if Ticket.query.filter_by(event_id=event.id).first():
        flash('Impossible de supprimer l\'événement car des tickets ont déjà été vendus.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    db.session.delete(event)
    db.session.commit()
    flash('Événement supprimé avec succès!', 'success')
    return redirect(url_for('my_events'))

@app.route('/event/<int:event_id>/buy', methods=['POST'])
@login_required
def buy_tickets(event_id):
    event = Event.query.get_or_404(event_id)
    ticket_type_id = int(request.form['ticket_type_id'])
    quantity = int(request.form['quantity'])
    
    ticket_type = TicketType.query.get_or_404(ticket_type_id)
    
    if quantity <= 0:
        flash('La quantité doit être supérieure à 0 !', 'error')
        return redirect(url_for('event_detail', event_id=event.id))
    
    if quantity > ticket_type.available_quantity:
        flash(f'Désolé, il ne reste que {ticket_type.available_quantity} places disponibles pour ce type de ticket !', 'error')
        return redirect(url_for('event_detail', event_id=event.id))
    
    # Créer l'achat de tickets
    ticket = Ticket(
        event_id=event.id,
        user_id=current_user.id,
        ticket_type_id=ticket_type_id,
        quantity=quantity,
        total_price=quantity * ticket_type.price,
        payment_status='en_attente'
    )
    
    # Mettre à jour le nombre de tickets disponibles
    ticket_type.available_quantity -= quantity
    
    db.session.add(ticket)
    db.session.commit()
    
    # Générer le QR code
    ticket.generate_qr_code()
    db.session.commit()
    
    flash(f'Achat de {quantity} tickets effectué avec succès ! Prix total : {ticket.total_price:.2f} FCFA', 'success')
    return redirect(url_for('purchase_history'))

@app.route('/purchase-history')
@login_required
def purchase_history():
    tickets = Ticket.query.filter_by(user_id=current_user.id).order_by(Ticket.purchase_date.desc()).all()
    return render_template('purchase_history.html', tickets=tickets)

@app.route('/dashboard')
@organizer_required
def dashboard():
    # Statistiques générales
    total_events = Event.query.filter_by(organizer_id=current_user.id).count()
    total_tickets_sold = db.session.query(func.sum(Ticket.quantity)).filter(
        Ticket.event_id.in_([e.id for e in Event.query.filter_by(organizer_id=current_user.id).all()])
    ).scalar() or 0
    total_revenue = db.session.query(func.sum(Ticket.total_price)).filter(
        Ticket.event_id.in_([e.id for e in Event.query.filter_by(organizer_id=current_user.id).all()])
    ).scalar() or 0

    # Données pour les graphiques
    events = Event.query.filter_by(organizer_id=current_user.id).all()
    event_names = [event.title for event in events]
    event_sales = []
    total_available_tickets = 0

    for event in events:
        tickets_sold = event.get_total_tickets_sold()
        event_sales.append(tickets_sold)
        total_available_tickets += event.get_available_tickets()

    # Récupérer les événements récents pour le tableau
    recent_events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.date.desc()).all()

    return render_template('dashboard.html',
                         total_events=total_events,
                         total_tickets_sold=total_tickets_sold,
                         total_revenue=total_revenue,
                         event_names=event_names,
                         event_sales=event_sales,
                         total_available_tickets=total_available_tickets,
                         has_events=bool(events),
                         recent_events=recent_events)

@app.route('/event/<int:event_id>/create-payment', methods=['POST'])
@login_required
def create_payment(event_id):
    event = Event.query.get_or_404(event_id)
    ticket_type_id = request.form.get('ticket_type_id')
    quantity = request.form.get('quantity')

    if not ticket_type_id or not quantity:
        flash('Veuillez sélectionner un type de ticket et une quantité.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    try:
        ticket_type_id = int(ticket_type_id)
        quantity = int(quantity)
    except ValueError:
        flash('Quantité invalide.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    ticket_type = TicketType.query.get_or_404(ticket_type_id)
    
    # Vérifier si le type de ticket appartient bien à l'événement
    if ticket_type.event_id != event.id:
        flash('Type de ticket invalide.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    # Vérifier la disponibilité des tickets
    if ticket_type.available_quantity < quantity:
        flash('Désolé, il ne reste plus assez de tickets disponibles.', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

    try:
        # Construire les URLs de redirection
        base_url = request.url_root.rstrip('/')
        success_url = f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/payment/cancel?session_id={{CHECKOUT_SESSION_ID}}"

        # Créer la session de paiement Stripe
        stripe_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': f'Tickets pour {event.title} - {ticket_type.name}',
                        'description': f'{quantity} ticket(s) pour {event.title}',
                    },
                    'unit_amount': int(ticket_type.price * 100),  # Stripe utilise les centimes
                },
                'quantity': quantity,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'event_id': str(event.id),
                'ticket_type_id': str(ticket_type_id),
                'quantity': str(quantity),
                'user_id': str(current_user.id)
            }
        )
        
        return redirect(stripe_session.url)
    except Exception as e:
        flash(f'Erreur lors de la création du paiement : {str(e)}', 'error')
        return redirect(url_for('event_detail', event_id=event.id))

@app.route('/payment/success')
@login_required
def payment_success():
    session_id = request.args.get('session_id')
    if not session_id:
        flash('Session de paiement invalide.', 'error')
        return redirect(url_for('index'))

    try:
        # Récupérer la session Stripe
        session = stripe.checkout.Session.retrieve(session_id)
        
        # Vérifier que la session appartient à l'utilisateur actuel
        if session.metadata.get('user_id') != str(current_user.id):
            flash('Accès non autorisé.', 'error')
            return redirect(url_for('index'))

        # Vérifier que le paiement a réussi
        if session.payment_status != 'paid':
            flash('Le paiement n\'a pas été complété.', 'error')
            return redirect(url_for('event_detail', event_id=session.metadata.get('event_id')))

        # Récupérer les informations de la session
        event_id = int(session.metadata.get('event_id'))
        ticket_type_id = int(session.metadata.get('ticket_type_id'))
        quantity = int(session.metadata.get('quantity'))

        # Créer le ticket
        ticket = Ticket(
            user_id=current_user.id,
            event_id=event_id,
            ticket_type_id=ticket_type_id,
            quantity=quantity,
            total_price=session.amount_total / 100,  # Convertir les centimes en euros
            payment_status='payé',
            payment_reference=session.payment_intent,
            purchase_date=datetime.now()
        )
        db.session.add(ticket)
        db.session.flush()  # Pour obtenir l'ID du ticket

        # Générer le QR code
        ticket.generate_qr_code()

        # Mettre à jour la quantité disponible
        ticket_type = TicketType.query.get(ticket_type_id)
        ticket_type.available_quantity -= quantity

        db.session.commit()
        flash('Paiement effectué avec succès ! Vos tickets ont été ajoutés à votre compte.', 'success')
        return redirect(url_for('purchase_history'))
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors du traitement du paiement : {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/payment/cancel')
@login_required
def payment_cancel():
    session_id = request.args.get('session_id')
    if not session_id:
        flash('Session de paiement invalide.', 'error')
        return redirect(url_for('index'))

    try:
        # Récupérer la session Stripe
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        
        # Vérifier que la session appartient à l'utilisateur actuel
        if stripe_session.metadata.get('user_id') != str(current_user.id):
            flash('Accès non autorisé.', 'error')
            return redirect(url_for('index'))

        # Expirer la session Stripe
        stripe.checkout.Session.expire(session_id)
        
        # Récupérer l'ID de l'événement depuis les métadonnées
        event_id = stripe_session.metadata.get('event_id')
        
        flash('Paiement annulé.', 'info')
        return redirect(url_for('event_detail', event_id=event_id))

    except stripe.error.StripeError as e:
        flash(f'Erreur lors de l\'annulation du paiement : {str(e)}', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Une erreur inattendue s\'est produite : {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/reset-database')
def reset_database():
    with app.app_context():
        # Supprimer toutes les tables
        db.drop_all()
        # Recréer toutes les tables
        db.create_all()
        current_app.logger.info("Base de données réinitialisée avec succès")
        flash('Base de données réinitialisée avec succès !', 'success')
        return redirect(url_for('index'))

@app.route('/ticket/<int:ticket_id>/download')
@login_required
def download_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.user_id != current_user.id:
        flash('Accès non autorisé.', 'danger')
        return redirect(url_for('purchase_history'))

    # Créer le PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    # Titre
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30
    )
    elements.append(Paragraph(f"Ticket - {ticket.event.title}", title_style))

    # Informations du ticket
    info_style = ParagraphStyle(
        'CustomInfo',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=12
    )
    
    # Créer le QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(f"Ticket ID: {ticket.id}\nEvent: {ticket.event.title}\nUser: {ticket.user.username}")
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # Convertir le QR code en image PIL
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    
    # Créer une image ReportLab à partir du QR code
    qr_img = Image(qr_buffer)
    qr_img.drawHeight = 200
    qr_img.drawWidth = 200

    # Ajouter les informations du ticket
    ticket_info = [
        f"<b>Événement:</b> {ticket.event.title}",
        f"<b>Date:</b> {ticket.event.date.strftime('%d/%m/%Y %H:%M')}",
        f"<b>Lieu:</b> {ticket.event.location}",
        f"<b>Type de ticket:</b> {ticket.ticket_type.name}",
        f"<b>Quantité:</b> {ticket.quantity}",
        f"<b>Prix total:</b> {ticket.total_price} FCFA",
        f"<b>Date d'achat:</b> {ticket.purchase_date.strftime('%d/%m/%Y %H:%M')}",
        f"<b>Statut du paiement:</b> {ticket.payment_status}"
    ]

    # Ajouter les informations du ticket au PDF
    for info in ticket_info:
        elements.append(Paragraph(info, info_style))

    # Ajouter un espace avant le QR code
    elements.append(Spacer(1, 20))

    # Ajouter le QR code
    elements.append(qr_img)

    # Construire le PDF
    doc.build(elements)
    buffer.seek(0)

    # Générer le nom du fichier
    filename = f"ticket_{ticket.event.title.replace(' ', '_')}_{ticket.id}.pdf"
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )

def save_identity_file(file, user_id, side):
    if file and allowed_file_identity(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{user_id}_{side}_{timestamp}_{filename}"
        
        # Créer le dossier s'il n'existe pas
        os.makedirs(app.config['UPLOAD_FOLDER_IDENTITY'], exist_ok=True)
        
        file_path = os.path.join(app.config['UPLOAD_FOLDER_IDENTITY'], filename)
        file.save(file_path)
        return f"/static/uploads/identity_docs/{filename}"
    return None

def clean_phone_number(phone):
    """Nettoie le numéro de téléphone en ne gardant que les chiffres."""
    # Supprime tous les caractères non numériques
    cleaned = re.sub(r'\D', '', phone)
    return cleaned

@app.route('/request-organizer', methods=['GET', 'POST'])
@login_required
def request_organizer():
    if current_user.is_organizer() or current_user.is_admin():
        flash('Vous êtes déjà un organisateur ou un administrateur.', 'info')
        return redirect(url_for('index'))
    
    if current_user.has_pending_organizer_request():
        flash('Vous avez déjà une demande en attente.', 'info')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            # Validation du numéro de téléphone
            phone = request.form.get('phone', '').strip()
            cleaned_phone = clean_phone_number(phone)
            
            # Vérifie que le numéro contient au moins 8 chiffres (minimum pour un numéro valide)
            if len(cleaned_phone) < 8:
                flash('Le numéro de téléphone doit contenir au moins 8 chiffres.', 'error')
                return redirect(url_for('request_organizer'))

            # Validation du type de pièce d'identité
            identity_type = request.form.get('identity_type')
            if not identity_type or identity_type not in ['CNI', 'Passeport', 'Permis']:
                flash('Veuillez sélectionner un type de pièce d\'identité valide.', 'error')
                return redirect(url_for('request_organizer'))

            # Gestion des fichiers
            if 'identity_recto' not in request.files or 'identity_verso' not in request.files:
                flash('Les deux photos de la pièce d\'identité sont requises.', 'error')
                return redirect(url_for('request_organizer'))

            recto_file = request.files['identity_recto']
            verso_file = request.files['identity_verso']

            if not recto_file.filename or not verso_file.filename:
                flash('Les deux photos de la pièce d\'identité sont requises.', 'error')
                return redirect(url_for('request_organizer'))

            # Sauvegarde des fichiers
            recto_path = save_identity_file(recto_file, current_user.id, 'recto')
            verso_path = save_identity_file(verso_file, current_user.id, 'verso')

            if not recto_path or not verso_path:
                flash('Erreur lors de l\'upload des fichiers. Formats acceptés: JPG, PNG, PDF. Taille max: 5MB', 'error')
                return redirect(url_for('request_organizer'))

            # Mise à jour de l'utilisateur
            current_user.organizer_request_phone = phone  # On garde le format original
            current_user.organizer_request_identity_type = identity_type
            current_user.organizer_request_identity_recto = recto_path
            current_user.organizer_request_identity_verso = verso_path
            current_user.organizer_request_message = request.form.get('message', '')
            current_user.organizer_request_status = 'pending'
            current_user.organizer_request_date = datetime.utcnow()

            db.session.commit()
            flash('Votre demande a été envoyée avec succès. Elle sera examinée par nos administrateurs.', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            flash('Une erreur est survenue lors de l\'envoi de votre demande. Veuillez réessayer.', 'error')
            return redirect(url_for('request_organizer'))
    
    return render_template('request_organizer.html')

@app.route('/admin/organizer-requests')
@admin_required
def admin_organizer_requests():
    pending_requests = User.query.filter_by(organizer_request_status='pending').all()
    return render_template('admin/organizer_requests.html', requests=pending_requests)

@app.route('/admin/organizer-request/<int:user_id>/approve')
@admin_required
def approve_organizer_request(user_id):
    user = User.query.get_or_404(user_id)
    success, msg = user.approve_organizer_request()
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin_organizer_requests'))

@app.route('/admin/organizer-request/<int:user_id>/reject')
@admin_required
def reject_organizer_request(user_id):
    user = User.query.get_or_404(user_id)
    success, msg = user.reject_organizer_request()
    flash(msg, 'success' if success else 'error')
    return redirect(url_for('admin_organizer_requests'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:user_id>/toggle-role')
@admin_required
def toggle_user_role(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Vous ne pouvez pas modifier votre propre rôle.', 'error')
        return redirect(url_for('admin_users'))
    
    if user.role == 'admin':
        user.role = 'user'
        flash(f'L\'utilisateur {user.username} n\'est plus administrateur.', 'success')
    elif user.role == 'user':
        user.role = 'admin'
        flash(f'L\'utilisateur {user.username} est maintenant administrateur.', 'success')
    
    db.session.commit()
    return redirect(url_for('admin_users'))

@app.route('/event/create', methods=['GET', 'POST'])
@organizer_required
def create_event():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        date_str = request.form.get('date')
        location = request.form.get('location')
        event_type = request.form.get('event_type')
        image_url = request.form.get('image_url')

        if not all([title, description, date_str, location, event_type]):
            flash('Tous les champs obligatoires doivent être remplis.', 'error')
            return redirect(url_for('create_event'))

        try:
            date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Format de date invalide.', 'error')
            return redirect(url_for('create_event'))

        event = Event(
            title=title,
            description=description,
            date=date,
            location=location,
            event_type=event_type,
            image_url=image_url,
            organizer_id=current_user.id
        )

        db.session.add(event)
        db.session.commit()

        flash('Événement créé avec succès !', 'success')
        return redirect(url_for('event_detail', event_id=event.id))

    return render_template('create_event.html')

@app.cli.command("create-admin")
@with_appcontext
def create_admin():
    """Crée le premier administrateur du système."""
    username = input("Nom d'utilisateur de l'administrateur : ")
    email = input("Email de l'administrateur : ")
    password = input("Mot de passe de l'administrateur : ")
    
    # Vérifier si l'utilisateur existe déjà
    user = User.query.filter_by(username=username).first()
    if user:
        if user.role == 'admin':
            click.echo("Cet utilisateur est déjà administrateur.")
            return
        user.role = 'admin'
        db.session.commit()
        click.echo(f"L'utilisateur {username} est maintenant administrateur.")
        return
    
    # Créer un nouvel administrateur
    admin = User(
        username=username,
        email=email,
        password=password
    )
    admin.role = 'admin'  # Définir le rôle après la création
    db.session.add(admin)
    db.session.commit()
    click.echo(f"Administrateur {username} créé avec succès !")

if __name__ == '__main__':
    # Lancement en mode développement local
    app.run(debug=True)
