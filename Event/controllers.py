from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from models import db, Event

event_bp = Blueprint('event', __name__)

@event_bp.route('/')
def list_events():
    events = Event.query.order_by(Event.date.desc()).all()
    return render_template('index.html', events=events)

@event_bp.route('/new', methods=['GET', 'POST'])
def new_event():
    if request.method == 'POST':
        event = Event(
            title=request.form['title'],
            description=request.form['description'],
            event_type=request.form['event_type'],
            date=datetime.strptime(request.form['date'], '%Y-%m-%dT%H:%M'),
            location=request.form['location']
        )
        db.session.add(event)
        db.session.commit()
        flash('Événement créé avec succès!', 'success')
        return redirect(url_for('event.list_events'))
    return render_template('new_event.html')

@event_bp.route('/<int:id>')
def event_detail(id):
    event = Event.query.get_or_404(id)
    return render_template('event_detail.html', event=event)

@event_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit_event(id):
    event = Event.query.get_or_404(id)
    if request.method == 'POST':
        event.title = request.form['title']
        event.description = request.form['description']
        event.event_type = request.form['event_type']
        event.date = datetime.strptime(request.form['date'], '%Y-%m-%dT%H:%M')
        event.location = request.form['location']
        db.session.commit()
        flash('Événement mis à jour avec succès!', 'success')
        return redirect(url_for('event.event_detail', id=event.id))
    return render_template('edit_event.html', event=event)

@event_bp.route('/<int:id>/delete', methods=['POST'])
def delete_event(id):
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    flash('Événement supprimé avec succès!', 'success')
    return redirect(url_for('event.list_events')) 