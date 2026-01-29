import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Vehicle, VehicleSpec, FuelLog, Expense, User, VEHICLE_TYPES, FUEL_TYPES, VEHICLE_SPEC_TYPES

bp = Blueprint('vehicles', __name__, url_prefix='/vehicles')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
@login_required
def index():
    show_archived = request.args.get('archived', 'false') == 'true'
    all_vehicles = current_user.get_all_vehicles()

    if show_archived:
        vehicles = [v for v in all_vehicles if not v.is_active]
    else:
        vehicles = [v for v in all_vehicles if v.is_active]

    archived_count = len([v for v in all_vehicles if not v.is_active])

    return render_template('vehicles/index.html',
                           vehicles=vehicles,
                           show_archived=show_archived,
                           archived_count=archived_count)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        vehicle = Vehicle(
            owner_id=current_user.id,
            name=request.form.get('name'),
            vehicle_type=request.form.get('vehicle_type'),
            make=request.form.get('make'),
            model=request.form.get('model'),
            year=int(request.form.get('year')) if request.form.get('year') else None,
            registration=request.form.get('registration'),
            vin=request.form.get('vin'),
            fuel_type=request.form.get('fuel_type'),
            tank_capacity=float(request.form.get('tank_capacity')) if request.form.get('tank_capacity') else None,
            notes=request.form.get('notes')
        )

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                vehicle.image_filename = filename

        db.session.add(vehicle)
        db.session.flush()  # Get the vehicle ID

        # Handle specifications
        spec_types = request.form.getlist('spec_type[]')
        spec_labels = request.form.getlist('spec_label[]')
        spec_values = request.form.getlist('spec_value[]')

        for i, spec_type in enumerate(spec_types):
            if spec_values[i].strip():  # Only add if value is not empty
                label = spec_labels[i] if spec_type == 'custom' else dict(VEHICLE_SPEC_TYPES).get(spec_type, spec_labels[i])
                spec = VehicleSpec(
                    vehicle_id=vehicle.id,
                    spec_type=spec_type,
                    label=label,
                    value=spec_values[i].strip()
                )
                db.session.add(spec)

        db.session.commit()

        flash(f'Vehicle "{vehicle.name}" added successfully', 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle.id))

    return render_template('vehicles/form.html',
                           vehicle=None,
                           vehicle_types=VEHICLE_TYPES,
                           fuel_types=FUEL_TYPES,
                           spec_types=VEHICLE_SPEC_TYPES)


@bp.route('/<int:vehicle_id>')
@login_required
def view(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check access
    if vehicle not in current_user.get_all_vehicles():
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    # Get recent activity
    recent_logs = vehicle.fuel_logs.order_by(FuelLog.date.desc()).limit(10).all()
    recent_expenses = vehicle.expenses.order_by(Expense.date.desc()).limit(10).all()

    # Get specifications
    specs = vehicle.specs.all()

    # Get statistics
    stats = {
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_cost': vehicle.get_total_cost(),
        'total_distance': vehicle.get_total_distance(),
        'avg_consumption': vehicle.get_average_consumption(),
        'fuel_logs_count': vehicle.fuel_logs.count(),
        'expenses_count': vehicle.expenses.count()
    }

    return render_template('vehicles/view.html',
                           vehicle=vehicle,
                           recent_logs=recent_logs,
                           recent_expenses=recent_expenses,
                           specs=specs,
                           stats=stats)


@bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    if request.method == 'POST':
        vehicle.name = request.form.get('name')
        vehicle.vehicle_type = request.form.get('vehicle_type')
        vehicle.make = request.form.get('make')
        vehicle.model = request.form.get('model')
        vehicle.year = int(request.form.get('year')) if request.form.get('year') else None
        vehicle.registration = request.form.get('registration')
        vehicle.vin = request.form.get('vin')
        vehicle.fuel_type = request.form.get('fuel_type')
        vehicle.tank_capacity = float(request.form.get('tank_capacity')) if request.form.get('tank_capacity') else None
        vehicle.notes = request.form.get('notes')

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                # Delete old image
                if vehicle.image_filename:
                    old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], vehicle.image_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)

                filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                vehicle.image_filename = filename

        # Handle specifications - delete existing and recreate
        VehicleSpec.query.filter_by(vehicle_id=vehicle.id).delete()

        spec_types = request.form.getlist('spec_type[]')
        spec_labels = request.form.getlist('spec_label[]')
        spec_values = request.form.getlist('spec_value[]')

        for i, spec_type in enumerate(spec_types):
            if spec_values[i].strip():  # Only add if value is not empty
                label = spec_labels[i] if spec_type == 'custom' else dict(VEHICLE_SPEC_TYPES).get(spec_type, spec_labels[i])
                spec = VehicleSpec(
                    vehicle_id=vehicle.id,
                    spec_type=spec_type,
                    label=label,
                    value=spec_values[i].strip()
                )
                db.session.add(spec)

        db.session.commit()
        flash('Vehicle updated successfully', 'success')
        return redirect(url_for('vehicles.view', vehicle_id=vehicle.id))

    specs = vehicle.specs.all()
    return render_template('vehicles/form.html',
                           vehicle=vehicle,
                           vehicle_types=VEHICLE_TYPES,
                           fuel_types=FUEL_TYPES,
                           spec_types=VEHICLE_SPEC_TYPES,
                           specs=specs)


@bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@login_required
def delete(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    # Delete image
    if vehicle.image_filename:
        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], vehicle.image_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    db.session.delete(vehicle)
    db.session.commit()
    flash('Vehicle deleted successfully', 'success')
    return redirect(url_for('vehicles.index'))


@bp.route('/<int:vehicle_id>/share', methods=['GET', 'POST'])
@login_required
def share(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        user = User.query.filter_by(username=username).first()

        if not user:
            flash('User not found', 'error')
        elif user.id == current_user.id:
            flash('You are already the owner', 'error')
        elif user in vehicle.shared_users.all():
            flash('Vehicle already shared with this user', 'error')
        else:
            vehicle.shared_users.append(user)
            db.session.commit()
            flash(f'Vehicle shared with {user.username}', 'success')

        return redirect(url_for('vehicles.share', vehicle_id=vehicle.id))

    shared_users = vehicle.shared_users.all()
    return render_template('vehicles/share.html', vehicle=vehicle, shared_users=shared_users)


@bp.route('/<int:vehicle_id>/unshare/<int:user_id>', methods=['POST'])
@login_required
def unshare(vehicle_id, user_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    user = User.query.get_or_404(user_id)
    if user in vehicle.shared_users.all():
        vehicle.shared_users.remove(user)
        db.session.commit()
        flash(f'Sharing removed for {user.username}', 'success')

    return redirect(url_for('vehicles.share', vehicle_id=vehicle.id))


@bp.route('/<int:vehicle_id>/archive', methods=['POST'])
@login_required
def archive(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    vehicle.is_active = False
    db.session.commit()
    flash(f'Vehicle "{vehicle.name}" has been archived', 'success')
    return redirect(url_for('vehicles.index'))


@bp.route('/<int:vehicle_id>/unarchive', methods=['POST'])
@login_required
def unarchive(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Check ownership
    if vehicle.owner_id != current_user.id and not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('vehicles.index'))

    vehicle.is_active = True
    db.session.commit()
    flash(f'Vehicle "{vehicle.name}" has been restored', 'success')
    return redirect(url_for('vehicles.index'))
