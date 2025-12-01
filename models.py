from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
from io import BytesIO
import base64
from sqlalchemy import func

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(1024))
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(20), nullable=False, default='user')  # 'user', 'organizer', 'admin', 'super_admin'
    organizer_request_status = db.Column(db.String(20), nullable=True)  # 'pending', 'approved', 'rejected', None
    organizer_request_date = db.Column(db.DateTime, nullable=True)
    organizer_request_message = db.Column(db.Text, nullable=True)
    identity_type = db.Column(db.String(50), nullable=True)  # Type de pièce d'identité
    identity_recto = db.Column(db.String(255), nullable=True)  # Chemin du fichier recto
    identity_verso = db.Column(db.String(255), nullable=True)  # Chemin du fichier verso
    organizer_request_phone = db.Column(db.String(20), nullable=True)  # Numéro de téléphone pour la demande d'organisateur
    organizer_request_identity_type = db.Column(db.String(50), nullable=True)  # Type de pièce d'identité pour la demande
    organizer_request_identity_recto = db.Column(db.String(255), nullable=True)  # Chemin du fichier recto pour la demande
    organizer_request_identity_verso = db.Column(db.String(255), nullable=True)  # Chemin du fichier verso pour la demande
    
    # Relations
    events = db.relationship('Event', backref='organizer', lazy=True)
    tickets = db.relationship('Ticket', backref='user', lazy=True)

    def __init__(self, username, email, password, first_name=None, last_name=None, phone=None):
        self.username = username
        self.email = email
        self.set_password(password)
        self.first_name = first_name
        self.last_name = last_name
        self.phone = phone
        self.role = 'user'  # Par défaut, l'utilisateur est un utilisateur simple

    def set_password(self, password):
        """Définit le mot de passe sous forme de hash."""
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        """Vérifie si le mot de passe correspond."""
        return check_password_hash(self.password_hash, password)
        
    def __repr__(self):
        return f'<User {self.username}>'

    def get_full_name(self):
        """Retourne le nom complet de l'utilisateur."""
        return f"{self.first_name} {self.last_name}"

    def is_super_admin(self):
        """Vérifie si l'utilisateur est un super administrateur."""
        return self.role == 'super_admin'

    def is_admin(self):
        """Vérifie si l'utilisateur est un administrateur ou un super administrateur."""
        return self.role in ['admin', 'super_admin']

    def is_organizer(self):
        """Vérifie si l'utilisateur est un organisateur, un admin ou un super admin."""
        return self.role in ['organizer', 'admin', 'super_admin']

    def is_user(self):
        """Vérifie si l'utilisateur est un utilisateur simple."""
        return self.role == 'user'

    def has_pending_organizer_request(self):
        """Vérifie si l'utilisateur a une demande d'organisateur en attente."""
        return self.organizer_request_status == 'pending'

    def request_organizer_status(self, message=None):
        """Demande à devenir organisateur."""
        if self.role != 'user':
            return False, "Vous êtes déjà un organisateur ou un administrateur."
        
        if self.has_pending_organizer_request():
            return False, "Vous avez déjà une demande en attente."
        
        self.organizer_request_status = 'pending'
        self.organizer_request_date = datetime.utcnow()
        self.organizer_request_message = message
        db.session.commit()
        return True, "Votre demande a été envoyée avec succès."

    def approve_organizer_request(self):
        """Approuve la demande d'organisateur."""
        if not self.has_pending_organizer_request():
            return False, "Aucune demande en attente."
        
        self.role = 'organizer'
        self.organizer_request_status = 'approved'
        self.organizer_request_date = datetime.utcnow()
        db.session.commit()
        return True, "La demande a été approuvée."

    def reject_organizer_request(self):
        """Rejette la demande d'organisateur."""
        if not self.has_pending_organizer_request():
            return False, "Aucune demande en attente."
        
        self.organizer_request_status = 'rejected'
        self.organizer_request_date = datetime.utcnow()
        db.session.commit()
        return True, "La demande a été rejetée."

    def can_manage_users(self):
        """Vérifie si l'utilisateur peut gérer les utilisateurs."""
        return self.role in ['admin', 'super_admin']

    def can_manage_organizers(self):
        """Vérifie si l'utilisateur peut gérer les organisateurs."""
        return self.role == 'super_admin'

class TicketType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # VIP, Standard, etc.
    price = db.Column(db.Float, nullable=False)
    total_quantity = db.Column(db.Integer, nullable=False)
    available_quantity = db.Column(db.Integer, nullable=False)
    
    # Relations
    tickets = db.relationship('Ticket', backref='ticket_type', lazy=True)
    
    def __repr__(self):
        return f'<TicketType {self.name} for Event {self.event_id}>'

    def get_tickets_sold(self):
        """Retourne le nombre de tickets vendus pour ce type."""
        return self.total_quantity - self.available_quantity

    def get_revenue(self):
        """Retourne le revenu total pour ce type de ticket."""
        return self.get_tickets_sold() * self.price

    def is_available(self, quantity=1):
        """Vérifie si le nombre de tickets demandé est disponible."""
        return self.available_quantity >= quantity

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image_url = db.Column(db.String(255), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relations
    tickets = db.relationship('Ticket', backref='event', lazy=True)
    ticket_types = db.relationship('TicketType', backref='event', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Event {self.title}>'

    def get_end_date(self):
        """Retourne la date de fin de l'événement (24h après la date de début)."""
        from datetime import timedelta
        return self.date + timedelta(hours=24)

    def is_upcoming(self):
        """Vérifie si l'événement est à venir."""
        return self.date > datetime.now()

    def is_ongoing(self):
        """Vérifie si l'événement est en cours."""
        now = datetime.now()
        return self.date <= now <= self.get_end_date()

    def is_past(self):
        """Vérifie si l'événement est passé."""
        return self.get_end_date() < datetime.now()

    def get_status(self):
        """Retourne le statut de l'événement."""
        if self.is_upcoming():
            return 'upcoming'
        elif self.is_ongoing():
            return 'ongoing'
        else:
            return 'past'

    def get_status_display(self):
        """Retourne le texte du statut en français."""
        status = self.get_status()
        if status == 'upcoming':
            return 'À venir'
        elif status == 'ongoing':
            return 'En cours'
        else:
            return 'Passé'

    def get_status_color(self):
        """Retourne la couleur Bootstrap correspondant au statut."""
        status = self.get_status()
        if status == 'upcoming':
            return 'primary'
        elif status == 'ongoing':
            return 'success'
        else:
            return 'secondary'

    def get_total_tickets_sold(self):
        """Retourne le nombre total de tickets vendus pour l'événement."""
        return db.session.query(func.sum(Ticket.quantity)).filter_by(event_id=self.id).scalar() or 0

    def get_total_revenue(self):
        """Retourne le revenu total de l'événement."""
        return db.session.query(func.sum(Ticket.total_price)).filter_by(event_id=self.id).scalar() or 0

    def get_available_tickets(self):
        """Retourne le nombre total de tickets disponibles."""
        return sum(ticket_type.available_quantity for ticket_type in self.ticket_types)

    def get_total_tickets(self):
        """Retourne le nombre total de tickets."""
        return sum(ticket_type.total_quantity for ticket_type in self.ticket_types)

    def is_sold_out(self):
        """Vérifie si l'événement est complet."""
        return self.get_available_tickets() == 0

    def can_be_deleted(self):
        """Vérifie si l'événement peut être supprimé (aucun ticket vendu)."""
        return self.get_total_tickets_sold() == 0

class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ticket_type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    purchase_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    total_price = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), nullable=False, default='en_attente')
    payment_reference = db.Column(db.String(100), nullable=True)
    payment_date = db.Column(db.DateTime, nullable=True)
    qr_code = db.Column(db.Text, nullable=True)

    def generate_qr_code(self):
        # Créer les données pour le QR code
        ticket_data = {
            'ticket_id': self.id,
            'event_id': self.event_id,
            'user_id': self.user_id,
            'purchase_date': self.purchase_date.isoformat()
        }
        
        # Générer le QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(str(ticket_data))
        qr.make(fit=True)
        
        # Créer l'image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convertir en base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        self.qr_code = img_str
        return img_str

    def __repr__(self):
        return f'<Ticket {self.id} for Event {self.event_id}>'

    def is_paid(self):
        """Vérifie si le ticket est payé."""
        return self.payment_status == 'payé'

    def is_cancelled(self):
        """Vérifie si le ticket est annulé."""
        return self.payment_status == 'annulé'

    def is_pending(self):
        """Vérifie si le ticket est en attente de paiement."""
        return self.payment_status == 'en_attente' 