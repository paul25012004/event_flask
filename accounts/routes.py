from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import User, db
from werkzeug.security import generate_password_hash, check_password_hash

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Veuillez vérifier vos identifiants et réessayer.', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=remember)
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))

    return render_template('auth/login.html')

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            current_app.logger.debug("Début du processus d'inscription")
            data = request.form
            current_app.logger.debug(f"Données reçues: {data}")

            # Vérification des champs requis
            required_fields = ['username', 'email', 'password', 'confirm_password', 'first_name', 'last_name']
            for field in required_fields:
                if not data.get(field):
                    current_app.logger.error(f"Champ requis manquant: {field}")
                    flash(f'Le champ {field} est requis.', 'danger')
                    return render_template('auth/register.html')

            # Vérification de la confirmation du mot de passe
            if data['password'] != data['confirm_password']:
                current_app.logger.error("Les mots de passe ne correspondent pas")
                flash('Les mots de passe ne correspondent pas.', 'danger')
                return render_template('auth/register.html')

            # Vérification si l'utilisateur existe déjà
            if User.query.filter_by(username=data['username']).first():
                current_app.logger.error(f"Nom d'utilisateur déjà pris: {data['username']}")
                flash('Ce nom d\'utilisateur est déjà pris.', 'danger')
                return render_template('auth/register.html')

            if User.query.filter_by(email=data['email']).first():
                current_app.logger.error(f"Email déjà utilisé: {data['email']}")
                flash('Cette adresse email est déjà utilisée.', 'danger')
                return render_template('auth/register.html')

            try:
                current_app.logger.debug("Tentative de création de l'utilisateur")
                # Création du nouvel utilisateur
                user = User(
                    username=data['username'],
                    email=data['email'],
                    password=data['password'],
                    first_name=data['first_name'],
                    last_name=data['last_name']
                )
                current_app.logger.debug(f"Utilisateur créé en mémoire: {user.__dict__}")

                # Sauvegarde dans la base de données
                current_app.logger.debug("Tentative d'ajout de l'utilisateur à la session")
                db.session.add(user)
                current_app.logger.debug("Tentative de commit de la session")
                db.session.commit()
                current_app.logger.info(f"Utilisateur enregistré avec succès: {user.username}")

                flash('Votre compte a été créé avec succès ! Vous pouvez maintenant vous connecter.', 'success')
                return redirect(url_for('auth.login'))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Erreur lors de la création de l'utilisateur: {str(e)}")
                current_app.logger.error(f"Type d'erreur: {type(e).__name__}")
                current_app.logger.error("Traceback complet:", exc_info=True)
                current_app.logger.error(f"État de la session: {db.session.is_active}")
                current_app.logger.error(f"État de la transaction: {db.session.in_transaction()}")
                flash('Une erreur est survenue lors de la création de votre compte. Veuillez réessayer.', 'danger')
                return render_template('auth/register.html')

        except Exception as e:
            current_app.logger.error(f"Erreur inattendue lors de l'inscription: {str(e)}")
            current_app.logger.error(f"Type d'erreur: {type(e).__name__}")
            current_app.logger.error("Traceback complet:", exc_info=True)
            flash('Une erreur inattendue est survenue. Veuillez réessayer.', 'danger')
            return render_template('auth/register.html')

    return render_template('auth/register.html')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('index'))

@auth.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html', user=current_user) 