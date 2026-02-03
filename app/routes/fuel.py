import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Vehicle, FuelLog, Attachment, FuelStation, FuelPriceHistory
from app.security import validate_file_upload, secure_filename_with_uuid, validate_positive_number
from app.services.tessie import TessieService

bp = Blueprint('fuel', __name__, url_prefix='/fuel')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}


def allowed_file(filename):
    """Legacy function - use validate_file_upload for new code"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
@login_required
def index():
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    # Get all fuel logs for user's vehicles
    logs = FuelLog.query.filter(
        FuelLog.vehicle_id.in_(vehicle_ids)
    ).order_by(FuelLog.date.desc()).all()

    return render_template('fuel/index.html', logs=logs, vehicles=vehicles)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash('Please add a vehicle first', 'info')
        return redirect(url_for('vehicles.new'))

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = Vehicle.query.get_or_404(vehicle_id)

        # Check access
        if vehicle not in vehicles:
            flash('Access denied', 'error')
            return redirect(url_for('fuel.index'))

        date_str = request.form.get('date')
        date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()

        # Validate numeric inputs
        odometer, err = validate_positive_number(request.form.get('odometer'), 'Odometer', max_value=9999999)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        volume, err = validate_positive_number(request.form.get('volume'), 'Volume', max_value=10000)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        price_per_unit, err = validate_positive_number(request.form.get('price_per_unit'), 'Price per unit', max_value=1000)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        total_cost, err = validate_positive_number(request.form.get('total_cost'), 'Total cost', max_value=100000)
        if err:
            flash(err, 'error')
            return render_template('fuel/new.html', vehicles=vehicles)

        log = FuelLog(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            date=date,
            odometer=odometer,
            volume=volume,
            price_per_unit=price_per_unit,
            total_cost=total_cost,
            is_full_tank=request.form.get('is_full_tank') == 'on',
            is_missed=request.form.get('is_missed') == 'on',
            station=request.form.get('station'),
            notes=request.form.get('notes')
        )

        # Calculate total cost if not provided
        if log.volume and log.price_per_unit and not log.total_cost:
            log.total_cost = round(log.volume * log.price_per_unit, 2)

        db.session.add(log)
        db.session.commit()

        # Auto-save fuel price to history if station is selected
        station_id = request.form.get('station_id', type=int)
        if station_id and log.price_per_unit:
            station = FuelStation.query.get(station_id)
            if station and station.user_id == current_user.id:
                # Save price history
                price_history = FuelPriceHistory(
                    station_id=station_id,
                    user_id=current_user.id,
                    date=log.date,
                    fuel_type=vehicle.fuel_type or 'petrol',
                    price_per_unit=log.price_per_unit
                )
                db.session.add(price_history)
                station.increment_usage()
                db.session.commit()

        # Handle attachment upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

                attachment = Attachment(
                    filename=filename,
                    original_filename=file.filename,
                    file_type=file.filename.rsplit('.', 1)[1].lower(),
                    fuel_log_id=log.id
                )
                db.session.add(attachment)
                db.session.commit()

        flash('Fuel log added successfully', 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    # Pre-select vehicle if provided
    selected_vehicle_id = request.args.get('vehicle_id', type=int)

    # Get user's fuel stations for dropdown
    stations = FuelStation.query.filter_by(user_id=current_user.id).order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    return render_template('fuel/form.html',
                           log=None,
                           vehicles=vehicles,
                           stations=stations,
                           selected_vehicle_id=selected_vehicle_id)


@bp.route('/<int:log_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(log_id):
    log = FuelLog.query.get_or_404(log_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if log.vehicle not in vehicles:
        flash('Access denied', 'error')
        return redirect(url_for('fuel.index'))

    if request.method == 'POST':
        date_str = request.form.get('date')
        log.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else log.date
        log.odometer = float(request.form.get('odometer'))
        log.volume = float(request.form.get('volume')) if request.form.get('volume') else None
        log.price_per_unit = float(request.form.get('price_per_unit')) if request.form.get('price_per_unit') else None
        log.total_cost = float(request.form.get('total_cost')) if request.form.get('total_cost') else None
        log.is_full_tank = request.form.get('is_full_tank') == 'on'
        log.is_missed = request.form.get('is_missed') == 'on'
        log.station = request.form.get('station')
        log.notes = request.form.get('notes')

        # Calculate total cost if not provided
        if log.volume and log.price_per_unit and not log.total_cost:
            log.total_cost = round(log.volume * log.price_per_unit, 2)

        # Handle attachment upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

                attachment = Attachment(
                    filename=filename,
                    original_filename=file.filename,
                    file_type=file.filename.rsplit('.', 1)[1].lower(),
                    fuel_log_id=log.id
                )
                db.session.add(attachment)

        db.session.commit()
        flash('Fuel log updated successfully', 'success')
        return redirect(url_for('vehicles.view', vehicle_id=log.vehicle_id))

    # Get user's fuel stations for dropdown
    stations = FuelStation.query.filter_by(user_id=current_user.id).order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).all()

    return render_template('fuel/form.html',
                           log=log,
                           vehicles=vehicles,
                           stations=stations,
                           selected_vehicle_id=log.vehicle_id)


@bp.route('/<int:log_id>/delete', methods=['POST'])
@login_required
def delete(log_id):
    log = FuelLog.query.get_or_404(log_id)
    vehicles = current_user.get_all_vehicles()

    # Check access
    if log.vehicle not in vehicles:
        flash('Access denied', 'error')
        return redirect(url_for('fuel.index'))

    vehicle_id = log.vehicle_id

    # Delete attachments
    for attachment in log.attachments.all():
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    db.session.delete(log)
    db.session.commit()
    flash('Fuel log deleted successfully', 'success')
    return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))


@bp.route('/quick', methods=['GET', 'POST'])
@login_required
def quick():
    """Quick entry mode - simplified single-screen fuel entry for mobile"""
    from app.models import FuelStation

    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash('Please add a vehicle first', 'info')
        return redirect(url_for('vehicles.new'))

    # Get user's fuel stations for dropdown
    stations = FuelStation.query.filter_by(user_id=current_user.id).order_by(
        FuelStation.is_favorite.desc(),
        FuelStation.times_used.desc()
    ).limit(10).all()

    if request.method == 'POST':
        vehicle_id = int(request.form.get('vehicle_id'))
        vehicle = Vehicle.query.get_or_404(vehicle_id)

        if vehicle not in vehicles:
            flash('Access denied', 'error')
            return redirect(url_for('fuel.quick'))

        log = FuelLog(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            date=datetime.now().date(),
            odometer=float(request.form.get('odometer')),
            volume=float(request.form.get('volume')) if request.form.get('volume') else None,
            total_cost=float(request.form.get('total_cost')) if request.form.get('total_cost') else None,
            is_full_tank=request.form.get('is_full_tank') == 'on',
            station=request.form.get('station'),
        )

        # Calculate price per unit
        if log.volume and log.total_cost:
            log.price_per_unit = round(log.total_cost / log.volume, 3)

        # Update station usage
        station_name = request.form.get('station')
        if station_name:
            station = FuelStation.query.filter_by(
                user_id=current_user.id,
                name=station_name
            ).first()
            if station:
                station.increment_usage()

        db.session.add(log)
        db.session.commit()

        flash('Fuel log added!', 'success')

        # Return to quick entry or vehicle page based on preference
        if request.form.get('add_another'):
            return redirect(url_for('fuel.quick', vehicle_id=vehicle_id))
        return redirect(url_for('vehicles.view', vehicle_id=vehicle_id))

    # Pre-select vehicle
    selected_vehicle_id = request.args.get('vehicle_id')
    if not selected_vehicle_id and len(vehicles) == 1:
        selected_vehicle_id = vehicles[0].id

    # Get last odometer for selected vehicle
    last_odometer = None
    if selected_vehicle_id:
        vehicle = Vehicle.query.get(selected_vehicle_id)
        if vehicle:
            last_odometer = vehicle.get_last_odometer()

    return render_template('fuel/quick.html',
                           vehicles=vehicles,
                           stations=stations,
                           selected_vehicle_id=selected_vehicle_id,
                           last_odometer=last_odometer)
