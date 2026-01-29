import csv
import io
import json
import os
import sqlite3
import tempfile
from functools import wraps
from datetime import datetime
from flask import Blueprint, jsonify, request, send_from_directory, current_app, url_for, render_template, Response, flash, redirect
from flask_login import login_required, current_user
from app import db
from app.models import User, Vehicle, VehicleSpec, FuelLog, Expense, EXPENSE_CATEGORIES

bp = Blueprint('api', __name__, url_prefix='/api')


# =============================================================================
# API Documentation
# =============================================================================

@bp.route('/docs')
@login_required
def docs():
    """API Documentation page"""
    return render_template('api/docs.html')


# =============================================================================
# API Authentication
# =============================================================================

def api_auth_required(f):
    """Decorator for API key authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = None

        # Check Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            api_key = auth_header[7:]

        # Check X-API-Key header
        if not api_key:
            api_key = request.headers.get('X-API-Key')

        if not api_key:
            return jsonify({'error': 'API key required', 'code': 'missing_api_key'}), 401

        user = User.get_by_api_key(api_key)
        if not user:
            return jsonify({'error': 'Invalid API key', 'code': 'invalid_api_key'}), 401

        # Attach user to request context
        request.api_user = user
        return f(*args, **kwargs)

    return decorated_function


def get_api_user():
    """Get the authenticated API user"""
    return getattr(request, 'api_user', None)


# =============================================================================
# API Key Management (Web UI routes)
# =============================================================================

@bp.route('/toggle-dark-mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    """Toggle dark mode for the current user"""
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return jsonify({'dark_mode': current_user.dark_mode})


@bp.route('/key/generate', methods=['POST'])
@login_required
def generate_api_key():
    """Generate a new API key for the current user"""
    api_key = current_user.generate_api_key()
    db.session.commit()
    return jsonify({
        'api_key': api_key,
        'created_at': current_user.api_key_created_at.isoformat()
    })


@bp.route('/key/revoke', methods=['POST'])
@login_required
def revoke_api_key():
    """Revoke the current user's API key"""
    current_user.revoke_api_key()
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Notification Testing
# =============================================================================

@bp.route('/notifications/test', methods=['POST'])
@login_required
def test_notification():
    """Send a test notification using the form values (not saved settings)"""
    from app.services.notifications import NotificationService

    # Get the method and settings from the form
    method = request.form.get('notification_method', 'email')
    title = "Test Notification from May"
    message = "This is a test notification to verify your settings are working correctly."

    if method == 'email':
        success, error = NotificationService.send_email(
            current_user.email,
            title,
            message,
            f"<html><body><h2>{title}</h2><p>{message}</p></body></html>"
        )
    elif method == 'ntfy':
        topic = request.form.get('ntfy_topic')
        if not topic:
            return jsonify({'success': False, 'error': 'Please enter an ntfy topic'})
        success, error = NotificationService.send_ntfy(topic, title, message)
    elif method == 'pushover':
        user_key = request.form.get('pushover_user_key')
        if not user_key:
            return jsonify({'success': False, 'error': 'Please enter your Pushover user key'})
        success, error = NotificationService.send_pushover(user_key, title, message)
    elif method == 'webhook':
        webhook_url = request.form.get('webhook_url')
        if not webhook_url:
            return jsonify({'success': False, 'error': 'Please enter a webhook URL'})
        payload = {
            'title': title,
            'message': message,
            'user_email': current_user.email,
            'test': True,
        }
        success, error = NotificationService.send_webhook(webhook_url, payload)
    else:
        return jsonify({'success': False, 'error': f'Unknown method: {method}'})

    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': error})


@bp.route('/smtp/test', methods=['POST'])
@login_required
def test_smtp():
    """Test SMTP settings (admin only)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Access denied'})

    from app.services.notifications import NotificationService

    config = {
        'host': request.form.get('smtp_host'),
        'port': request.form.get('smtp_port', '587'),
        'username': request.form.get('smtp_username'),
        'password': request.form.get('smtp_password'),
        'use_tls': request.form.get('smtp_tls') == 'true',
        'use_ssl': request.form.get('smtp_ssl') == 'true',
    }

    success, message = NotificationService.test_smtp(config)

    if success:
        # If connection test passed, try sending an actual test email
        from app.models import AppSettings
        sender = request.form.get('smtp_sender') or config['username']
        sender_name = request.form.get('smtp_sender_name') or 'May'

        # Temporarily set the config for sending
        old_config = NotificationService.get_smtp_config()
        AppSettings.set('smtp_host', config['host'])
        AppSettings.set('smtp_port', config['port'])
        AppSettings.set('smtp_username', config['username'])
        AppSettings.set('smtp_password', config['password'])
        AppSettings.set('smtp_sender', sender)
        AppSettings.set('smtp_sender_name', sender_name)
        AppSettings.set('smtp_tls', 'true' if config['use_tls'] else 'false')
        AppSettings.set('smtp_ssl', 'true' if config['use_ssl'] else 'false')

        send_success, send_error = NotificationService.send_email(
            current_user.email,
            "Test Email from May",
            "This is a test email to verify your SMTP settings are configured correctly.",
            "<html><body><h2>Test Email</h2><p>This is a test email to verify your SMTP settings are configured correctly.</p></body></html>"
        )

        if send_success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': f'Connection OK, but send failed: {send_error}'})
    else:
        return jsonify({'success': False, 'error': message})


# =============================================================================
# File Serving
# =============================================================================

@bp.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    """Serve uploaded files"""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


# =============================================================================
# Internal API (for web UI, session-authenticated)
# =============================================================================

@bp.route('/vehicles/<int:vehicle_id>/stats')
@login_required
def vehicle_stats(vehicle_id):
    """Get statistics for a specific vehicle (for charts)"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'error': 'Access denied'}), 403

    logs = vehicle.fuel_logs.filter_by(is_full_tank=True).order_by(FuelLog.date).all()
    consumption_data = []
    for log in logs:
        consumption = log.get_consumption()
        if consumption:
            consumption_data.append({
                'date': log.date.isoformat(),
                'consumption': round(consumption, 2),
                'odometer': log.odometer
            })

    expenses = vehicle.expenses.all()
    category_totals = {}
    for exp in expenses:
        if exp.category in category_totals:
            category_totals[exp.category] += exp.cost
        else:
            category_totals[exp.category] = exp.cost

    return jsonify({
        'consumption': consumption_data,
        'expenses_by_category': category_totals,
        'total_fuel_cost': vehicle.get_total_fuel_cost(),
        'total_expense_cost': vehicle.get_total_expense_cost(),
        'total_distance': vehicle.get_total_distance(),
        'avg_consumption': vehicle.get_average_consumption()
    })


@bp.route('/vehicles/<int:vehicle_id>/last-odometer')
@login_required
def last_odometer(vehicle_id):
    """Get the last recorded odometer reading for a vehicle"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'error': 'Access denied'}), 403

    return jsonify({'odometer': vehicle.get_last_odometer()})


# =============================================================================
# Public API v1 - Vehicles
# =============================================================================

@bp.route('/v1/vehicles', methods=['GET'])
@api_auth_required
def api_list_vehicles():
    """
    List all vehicles

    Returns all vehicles the authenticated user has access to.
    """
    user = get_api_user()
    vehicles = user.get_all_vehicles()
    return jsonify({
        'vehicles': [v.to_dict() for v in vehicles],
        'count': len(vehicles)
    })


@bp.route('/v1/vehicles/<int:vehicle_id>', methods=['GET'])
@api_auth_required
def api_get_vehicle(vehicle_id):
    """
    Get a specific vehicle

    Returns detailed information about a single vehicle.
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    return jsonify(vehicle.to_dict())


@bp.route('/v1/vehicles', methods=['POST'])
@api_auth_required
def api_create_vehicle():
    """
    Create a new vehicle

    Required fields: name, vehicle_type
    Optional fields: make, model, year, registration, vin, fuel_type, tank_capacity
    """
    user = get_api_user()
    data = request.get_json()

    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if not data.get('name'):
        return jsonify({'error': 'name is required', 'code': 'validation_error'}), 400

    if not data.get('vehicle_type'):
        return jsonify({'error': 'vehicle_type is required', 'code': 'validation_error'}), 400

    if data['vehicle_type'] not in ['car', 'van', 'motorbike', 'scooter']:
        return jsonify({'error': 'vehicle_type must be one of: car, van, motorbike, scooter', 'code': 'validation_error'}), 400

    vehicle = Vehicle(
        owner_id=user.id,
        name=data['name'],
        vehicle_type=data['vehicle_type'],
        make=data.get('make'),
        model=data.get('model'),
        year=data.get('year'),
        registration=data.get('registration'),
        vin=data.get('vin'),
        fuel_type=data.get('fuel_type', 'petrol'),
        tank_capacity=data.get('tank_capacity')
    )

    db.session.add(vehicle)
    db.session.commit()

    return jsonify(vehicle.to_dict()), 201


@bp.route('/v1/vehicles/<int:vehicle_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_vehicle(vehicle_id):
    """
    Update a vehicle

    All fields are optional. Only provided fields will be updated.
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle.owner_id != user.id:
        return jsonify({'error': 'Only the owner can update this vehicle', 'code': 'forbidden'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'name' in data:
        vehicle.name = data['name']
    if 'vehicle_type' in data:
        if data['vehicle_type'] not in ['car', 'van', 'motorbike', 'scooter']:
            return jsonify({'error': 'vehicle_type must be one of: car, van, motorbike, scooter', 'code': 'validation_error'}), 400
        vehicle.vehicle_type = data['vehicle_type']
    if 'make' in data:
        vehicle.make = data['make']
    if 'model' in data:
        vehicle.model = data['model']
    if 'year' in data:
        vehicle.year = data['year']
    if 'registration' in data:
        vehicle.registration = data['registration']
    if 'vin' in data:
        vehicle.vin = data['vin']
    if 'fuel_type' in data:
        vehicle.fuel_type = data['fuel_type']
    if 'tank_capacity' in data:
        vehicle.tank_capacity = data['tank_capacity']
    if 'is_active' in data:
        vehicle.is_active = data['is_active']

    db.session.commit()
    return jsonify(vehicle.to_dict())


@bp.route('/v1/vehicles/<int:vehicle_id>', methods=['DELETE'])
@api_auth_required
def api_delete_vehicle(vehicle_id):
    """
    Delete a vehicle

    This will also delete all associated fuel logs and expenses.
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle.owner_id != user.id:
        return jsonify({'error': 'Only the owner can delete this vehicle', 'code': 'forbidden'}), 403

    db.session.delete(vehicle)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Vehicle deleted'})


# =============================================================================
# Public API v1 - Fuel Logs
# =============================================================================

@bp.route('/v1/vehicles/<int:vehicle_id>/fuel', methods=['GET'])
@api_auth_required
def api_list_fuel_logs(vehicle_id):
    """
    List fuel logs for a vehicle

    Query parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip (default: 0)
    - sort: Sort order, 'asc' or 'desc' by date (default: desc)
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = request.args.get('offset', 0, type=int)
    sort = request.args.get('sort', 'desc')

    query = vehicle.fuel_logs
    if sort == 'asc':
        query = query.order_by(FuelLog.date.asc())
    else:
        query = query.order_by(FuelLog.date.desc())

    total = query.count()
    logs = query.offset(offset).limit(limit).all()

    return jsonify({
        'fuel_logs': [log.to_dict() for log in logs],
        'count': len(logs),
        'total': total,
        'limit': limit,
        'offset': offset
    })


@bp.route('/v1/vehicles/<int:vehicle_id>/fuel', methods=['POST'])
@api_auth_required
def api_create_fuel_log(vehicle_id):
    """
    Create a fuel log

    Required fields: date, odometer
    Optional fields: volume, price_per_unit, total_cost, is_full_tank, is_missed, station, notes
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if not data.get('date'):
        return jsonify({'error': 'date is required (YYYY-MM-DD)', 'code': 'validation_error'}), 400

    if not data.get('odometer'):
        return jsonify({'error': 'odometer is required', 'code': 'validation_error'}), 400

    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    log = FuelLog(
        vehicle_id=vehicle_id,
        user_id=user.id,
        date=date,
        odometer=float(data['odometer']),
        volume=float(data['volume']) if data.get('volume') else None,
        price_per_unit=float(data['price_per_unit']) if data.get('price_per_unit') else None,
        total_cost=float(data['total_cost']) if data.get('total_cost') else None,
        is_full_tank=data.get('is_full_tank', True),
        is_missed=data.get('is_missed', False),
        station=data.get('station'),
        notes=data.get('notes')
    )

    # Auto-calculate total cost if not provided
    if log.volume and log.price_per_unit and not log.total_cost:
        log.total_cost = round(log.volume * log.price_per_unit, 2)

    db.session.add(log)
    db.session.commit()

    return jsonify(log.to_dict()), 201


@bp.route('/v1/fuel/<int:log_id>', methods=['GET'])
@api_auth_required
def api_get_fuel_log(log_id):
    """Get a specific fuel log"""
    user = get_api_user()
    log = FuelLog.query.get_or_404(log_id)

    if log.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Fuel log not found or access denied', 'code': 'not_found'}), 404

    return jsonify(log.to_dict())


@bp.route('/v1/fuel/<int:log_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_fuel_log(log_id):
    """Update a fuel log"""
    user = get_api_user()
    log = FuelLog.query.get_or_404(log_id)

    if log.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Fuel log not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'date' in data:
        try:
            log.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if 'odometer' in data:
        log.odometer = float(data['odometer'])
    if 'volume' in data:
        log.volume = float(data['volume']) if data['volume'] else None
    if 'price_per_unit' in data:
        log.price_per_unit = float(data['price_per_unit']) if data['price_per_unit'] else None
    if 'total_cost' in data:
        log.total_cost = float(data['total_cost']) if data['total_cost'] else None
    if 'is_full_tank' in data:
        log.is_full_tank = data['is_full_tank']
    if 'is_missed' in data:
        log.is_missed = data['is_missed']
    if 'station' in data:
        log.station = data['station']
    if 'notes' in data:
        log.notes = data['notes']

    db.session.commit()
    return jsonify(log.to_dict())


@bp.route('/v1/fuel/<int:log_id>', methods=['DELETE'])
@api_auth_required
def api_delete_fuel_log(log_id):
    """Delete a fuel log"""
    user = get_api_user()
    log = FuelLog.query.get_or_404(log_id)

    if log.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Fuel log not found or access denied', 'code': 'not_found'}), 404

    db.session.delete(log)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Fuel log deleted'})


# =============================================================================
# Public API v1 - Expenses
# =============================================================================

@bp.route('/v1/vehicles/<int:vehicle_id>/expenses', methods=['GET'])
@api_auth_required
def api_list_expenses(vehicle_id):
    """
    List expenses for a vehicle

    Query parameters:
    - limit: Maximum number of results (default: 100)
    - offset: Number of results to skip (default: 0)
    - category: Filter by category
    - sort: Sort order, 'asc' or 'desc' by date (default: desc)
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    limit = min(request.args.get('limit', 100, type=int), 500)
    offset = request.args.get('offset', 0, type=int)
    category = request.args.get('category')
    sort = request.args.get('sort', 'desc')

    query = vehicle.expenses
    if category:
        query = query.filter_by(category=category)

    if sort == 'asc':
        query = query.order_by(Expense.date.asc())
    else:
        query = query.order_by(Expense.date.desc())

    total = query.count()
    expenses = query.offset(offset).limit(limit).all()

    return jsonify({
        'expenses': [exp.to_dict() for exp in expenses],
        'count': len(expenses),
        'total': total,
        'limit': limit,
        'offset': offset
    })


@bp.route('/v1/vehicles/<int:vehicle_id>/expenses', methods=['POST'])
@api_auth_required
def api_create_expense(vehicle_id):
    """
    Create an expense

    Required fields: date, category, description, cost
    Optional fields: odometer, vendor, notes
    """
    user = get_api_user()
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Vehicle not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    required = ['date', 'category', 'description', 'cost']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'{field} is required', 'code': 'validation_error'}), 400

    valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
    if data['category'] not in valid_categories:
        return jsonify({
            'error': f'category must be one of: {", ".join(valid_categories)}',
            'code': 'validation_error'
        }), 400

    try:
        date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    expense = Expense(
        vehicle_id=vehicle_id,
        user_id=user.id,
        date=date,
        category=data['category'],
        description=data['description'],
        cost=float(data['cost']),
        odometer=float(data['odometer']) if data.get('odometer') else None,
        vendor=data.get('vendor'),
        notes=data.get('notes')
    )

    db.session.add(expense)
    db.session.commit()

    return jsonify(expense.to_dict()), 201


@bp.route('/v1/expenses/<int:expense_id>', methods=['GET'])
@api_auth_required
def api_get_expense(expense_id):
    """Get a specific expense"""
    user = get_api_user()
    expense = Expense.query.get_or_404(expense_id)

    if expense.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Expense not found or access denied', 'code': 'not_found'}), 404

    return jsonify(expense.to_dict())


@bp.route('/v1/expenses/<int:expense_id>', methods=['PUT', 'PATCH'])
@api_auth_required
def api_update_expense(expense_id):
    """Update an expense"""
    user = get_api_user()
    expense = Expense.query.get_or_404(expense_id)

    if expense.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Expense not found or access denied', 'code': 'not_found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required', 'code': 'invalid_request'}), 400

    if 'date' in data:
        try:
            expense.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD', 'code': 'validation_error'}), 400

    if 'category' in data:
        valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
        if data['category'] not in valid_categories:
            return jsonify({
                'error': f'category must be one of: {", ".join(valid_categories)}',
                'code': 'validation_error'
            }), 400
        expense.category = data['category']

    if 'description' in data:
        expense.description = data['description']
    if 'cost' in data:
        expense.cost = float(data['cost'])
    if 'odometer' in data:
        expense.odometer = float(data['odometer']) if data['odometer'] else None
    if 'vendor' in data:
        expense.vendor = data['vendor']
    if 'notes' in data:
        expense.notes = data['notes']

    db.session.commit()
    return jsonify(expense.to_dict())


@bp.route('/v1/expenses/<int:expense_id>', methods=['DELETE'])
@api_auth_required
def api_delete_expense(expense_id):
    """Delete an expense"""
    user = get_api_user()
    expense = Expense.query.get_or_404(expense_id)

    if expense.vehicle not in user.get_all_vehicles():
        return jsonify({'error': 'Expense not found or access denied', 'code': 'not_found'}), 404

    db.session.delete(expense)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Expense deleted'})


# =============================================================================
# Public API v1 - Metadata
# =============================================================================

@bp.route('/v1/categories', methods=['GET'])
@api_auth_required
def api_list_categories():
    """List all expense categories"""
    return jsonify({
        'categories': [{'id': c[0], 'name': c[1]} for c in EXPENSE_CATEGORIES]
    })


# =============================================================================
# DVLA Integration (UK Vehicles)
# =============================================================================

@bp.route('/dvla/lookup', methods=['POST'])
@login_required
def dvla_lookup():
    """
    Look up vehicle information from DVLA (UK vehicles only)

    Expects JSON body with 'registration' field
    """
    from app.services.dvla import DVLAService

    if not DVLAService.is_configured():
        return jsonify({'success': False, 'error': 'DVLA integration not configured'}), 400

    data = request.get_json()
    if not data or not data.get('registration'):
        return jsonify({'success': False, 'error': 'Registration number required'}), 400

    success, result = DVLAService.lookup_vehicle(data['registration'])

    if success:
        # Convert dates to strings for JSON
        if result.get('mot_expiry_date'):
            result['mot_expiry_date'] = result['mot_expiry_date'].isoformat()
        if result.get('tax_due_date'):
            result['tax_due_date'] = result['tax_due_date'].isoformat()
        if result.get('date_of_last_v5c_issued'):
            result['date_of_last_v5c_issued'] = result['date_of_last_v5c_issued'].isoformat()
        return jsonify({'success': True, 'vehicle': result})
    else:
        return jsonify({'success': False, 'error': result}), 400


@bp.route('/dvla/test', methods=['POST'])
@login_required
def dvla_test_key():
    """Test DVLA API key (admin only)"""
    if not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    from app.services.dvla import DVLAService

    api_key = request.form.get('dvla_api_key')
    if not api_key:
        return jsonify({'success': False, 'error': 'API key required'}), 400

    success, message = DVLAService.test_api_key(api_key)
    return jsonify({'success': success, 'message': message})


@bp.route('/dvla/status')
@login_required
def dvla_status():
    """Check if DVLA integration is available"""
    from app.services.dvla import DVLAService
    return jsonify({'configured': DVLAService.is_configured()})


@bp.route('/vehicles/<int:vehicle_id>/dvla-refresh', methods=['POST'])
@login_required
def refresh_vehicle_dvla(vehicle_id):
    """
    Refresh vehicle MOT and tax status from DVLA

    Updates the vehicle's MOT and tax status fields if the vehicle has a UK registration
    """
    from app.services.dvla import DVLAService

    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle not in current_user.get_all_vehicles():
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    if not vehicle.registration:
        return jsonify({'success': False, 'error': 'Vehicle has no registration number'}), 400

    if not DVLAService.is_configured():
        return jsonify({'success': False, 'error': 'DVLA integration not configured'}), 400

    success, result = DVLAService.lookup_vehicle(vehicle.registration)

    if success:
        # Update vehicle with DVLA data
        vehicle.mot_status = result.get('mot_status')
        vehicle.mot_expiry = result.get('mot_expiry_date')
        vehicle.tax_status = result.get('tax_status')
        vehicle.tax_due = result.get('tax_due_date')
        vehicle.dvla_colour = result.get('colour')
        vehicle.dvla_last_updated = datetime.utcnow()

        # Optionally update make if empty
        if not vehicle.make and result.get('make'):
            vehicle.make = result['make']

        # Optionally update year if empty
        if not vehicle.year and result.get('year_of_manufacture'):
            vehicle.year = result['year_of_manufacture']

        db.session.commit()

        return jsonify({
            'success': True,
            'mot_status': vehicle.mot_status,
            'mot_expiry': vehicle.mot_expiry.isoformat() if vehicle.mot_expiry else None,
            'tax_status': vehicle.tax_status,
            'tax_due': vehicle.tax_due.isoformat() if vehicle.tax_due else None,
        })
    else:
        return jsonify({'success': False, 'error': result}), 400


# =============================================================================
# Data Export (Web UI routes, session-authenticated)
# =============================================================================

@bp.route('/export/csv')
@login_required
def export_csv():
    """
    Export all user data as CSV files in a ZIP archive.
    Includes: vehicles.csv, fuel_logs.csv, expenses.csv
    """
    import zipfile

    # Create a BytesIO buffer for the ZIP file
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Export Vehicles
        vehicles_csv = io.StringIO()
        writer = csv.writer(vehicles_csv)
        writer.writerow([
            'id', 'name', 'vehicle_type', 'make', 'model', 'year',
            'registration', 'vin', 'fuel_type', 'tank_capacity',
            'is_active', 'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            writer.writerow([
                vehicle.id, vehicle.name, vehicle.vehicle_type,
                vehicle.make, vehicle.model, vehicle.year,
                vehicle.registration, vehicle.vin, vehicle.fuel_type,
                vehicle.tank_capacity, vehicle.is_active, vehicle.notes,
                vehicle.created_at.isoformat() if vehicle.created_at else ''
            ])
        zip_file.writestr('vehicles.csv', vehicles_csv.getvalue())

        # Export Vehicle Specs
        specs_csv = io.StringIO()
        writer = csv.writer(specs_csv)
        writer.writerow(['vehicle_id', 'vehicle_name', 'spec_type', 'label', 'value'])
        for vehicle in current_user.get_all_vehicles():
            for spec in vehicle.specs.all():
                writer.writerow([
                    vehicle.id, vehicle.name, spec.spec_type, spec.label, spec.value
                ])
        zip_file.writestr('vehicle_specs.csv', specs_csv.getvalue())

        # Export Fuel Logs
        fuel_csv = io.StringIO()
        writer = csv.writer(fuel_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'date', 'odometer',
            'volume', 'price_per_unit', 'total_cost', 'is_full_tank',
            'is_missed', 'station', 'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for log in vehicle.fuel_logs.order_by(FuelLog.date.desc()).all():
                writer.writerow([
                    log.id, vehicle.id, vehicle.name, log.date.isoformat(),
                    log.odometer, log.volume, log.price_per_unit, log.total_cost,
                    log.is_full_tank, log.is_missed, log.station, log.notes,
                    log.created_at.isoformat() if log.created_at else ''
                ])
        zip_file.writestr('fuel_logs.csv', fuel_csv.getvalue())

        # Export Expenses
        expenses_csv = io.StringIO()
        writer = csv.writer(expenses_csv)
        writer.writerow([
            'id', 'vehicle_id', 'vehicle_name', 'date', 'category',
            'description', 'cost', 'odometer', 'vendor', 'notes', 'created_at'
        ])
        for vehicle in current_user.get_all_vehicles():
            for expense in vehicle.expenses.order_by(Expense.date.desc()).all():
                writer.writerow([
                    expense.id, vehicle.id, vehicle.name, expense.date.isoformat(),
                    expense.category, expense.description, expense.cost,
                    expense.odometer, expense.vendor, expense.notes,
                    expense.created_at.isoformat() if expense.created_at else ''
                ])
        zip_file.writestr('expenses.csv', expenses_csv.getvalue())

    zip_buffer.seek(0)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'may_export_{timestamp}.zip'

    return Response(
        zip_buffer.getvalue(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/export/json')
@login_required
def export_json():
    """
    Export all user data as a single JSON file.
    Complete backup including all vehicles, specs, fuel logs, and expenses.
    """
    export_data = {
        'export_info': {
            'exported_at': datetime.utcnow().isoformat(),
            'username': current_user.username,
            'app_version': '1.0.0'
        },
        'user_preferences': {
            'language': current_user.language,
            'distance_unit': current_user.distance_unit,
            'volume_unit': current_user.volume_unit,
            'consumption_unit': current_user.consumption_unit,
            'currency': current_user.currency
        },
        'vehicles': []
    }

    for vehicle in current_user.get_all_vehicles():
        vehicle_data = {
            'id': vehicle.id,
            'name': vehicle.name,
            'vehicle_type': vehicle.vehicle_type,
            'make': vehicle.make,
            'model': vehicle.model,
            'year': vehicle.year,
            'registration': vehicle.registration,
            'vin': vehicle.vin,
            'fuel_type': vehicle.fuel_type,
            'tank_capacity': vehicle.tank_capacity,
            'is_active': vehicle.is_active,
            'notes': vehicle.notes,
            'created_at': vehicle.created_at.isoformat() if vehicle.created_at else None,
            'specifications': [],
            'fuel_logs': [],
            'expenses': []
        }

        # Add specifications
        for spec in vehicle.specs.all():
            vehicle_data['specifications'].append({
                'spec_type': spec.spec_type,
                'label': spec.label,
                'value': spec.value
            })

        # Add fuel logs
        for log in vehicle.fuel_logs.order_by(FuelLog.date.desc()).all():
            vehicle_data['fuel_logs'].append({
                'id': log.id,
                'date': log.date.isoformat() if log.date else None,
                'odometer': log.odometer,
                'volume': log.volume,
                'price_per_unit': log.price_per_unit,
                'total_cost': log.total_cost,
                'is_full_tank': log.is_full_tank,
                'is_missed': log.is_missed,
                'station': log.station,
                'notes': log.notes,
                'created_at': log.created_at.isoformat() if log.created_at else None
            })

        # Add expenses
        for expense in vehicle.expenses.order_by(Expense.date.desc()).all():
            vehicle_data['expenses'].append({
                'id': expense.id,
                'date': expense.date.isoformat() if expense.date else None,
                'category': expense.category,
                'description': expense.description,
                'cost': expense.cost,
                'odometer': expense.odometer,
                'vendor': expense.vendor,
                'notes': expense.notes,
                'created_at': expense.created_at.isoformat() if expense.created_at else None
            })

        export_data['vehicles'].append(vehicle_data)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'may_backup_{timestamp}.json'

    return Response(
        json.dumps(export_data, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# =============================================================================
# Data Import (Web UI routes, session-authenticated)
# =============================================================================

# Hammond fuel unit mapping
HAMMOND_FUEL_UNITS = {
    'LITRE': 'L',
    'GALLON': 'gal',
    'US_GALLON': 'us_gal',
}

# Hammond fuel type mapping
HAMMOND_FUEL_TYPES = {
    'PETROL': 'petrol',
    'DIESEL': 'diesel',
    'ETHANOL': 'e85',
    'LPG': 'lpg',
    'ELECTRIC': 'electric',
    'HYBRID': 'hybrid',
}

# Hammond distance unit mapping
HAMMOND_DISTANCE_UNITS = {
    'MILES': 'mi',
    'KILOMETERS': 'km',
}

# Clarkson fuel type mapping (int to string)
CLARKSON_FUEL_TYPES = {
    1: 'petrol',
    2: 'diesel',
    3: 'e85',
    4: 'lpg',
}

# Clarkson distance unit mapping
CLARKSON_DISTANCE_UNITS = {
    1: 'mi',
    2: 'km',
}

# Clarkson fuel unit mapping
CLARKSON_FUEL_UNITS = {
    1: 'L',
    2: 'gal',
    3: 'us_gal',
}


@bp.route('/import/hammond', methods=['POST'])
@login_required
def import_hammond():
    """
    Import data from Hammond SQLite database.
    Expects a .db or .sqlite file upload.
    """
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    file = request.files['file']
    if not file.filename:
        flash('No file selected', 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    # Save uploaded file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Track import statistics
        stats = {'vehicles': 0, 'fuel_logs': 0, 'expenses': 0}
        vehicle_id_map = {}  # Hammond vehicle ID -> May vehicle ID

        # Import vehicles
        try:
            cursor.execute('SELECT * FROM vehicles')
            hammond_vehicles = cursor.fetchall()

            for hv in hammond_vehicles:
                # Map fuel type
                fuel_type = HAMMOND_FUEL_TYPES.get(hv['fuel_type'], 'petrol') if hv['fuel_type'] else 'petrol'

                vehicle = Vehicle(
                    owner_id=current_user.id,
                    name=hv['nickname'] or f"{hv['make']} {hv['model']}".strip() or 'Imported Vehicle',
                    vehicle_type='car',  # Hammond doesn't distinguish vehicle types
                    make=hv['make'],
                    model=hv['model'],
                    year=hv['year_of_manufacture'],
                    registration=hv['registration'],
                    vin=hv['vin'],
                    fuel_type=fuel_type,
                    tank_capacity=None,
                    notes=f"Imported from Hammond (ID: {hv['id']})"
                )
                db.session.add(vehicle)
                db.session.flush()
                vehicle_id_map[hv['id']] = vehicle.id
                stats['vehicles'] += 1

        except sqlite3.OperationalError:
            pass  # Table doesn't exist

        # Import fillups (fuel logs)
        try:
            cursor.execute('SELECT * FROM fillups')
            hammond_fillups = cursor.fetchall()

            for hf in hammond_fillups:
                vehicle_id = vehicle_id_map.get(hf['vehicle_id'])
                if not vehicle_id:
                    continue

                # Parse date
                try:
                    if hf['date']:
                        # Hammond stores dates as ISO strings
                        date = datetime.fromisoformat(hf['date'].replace('Z', '+00:00')).date()
                    else:
                        date = datetime.utcnow().date()
                except (ValueError, TypeError):
                    date = datetime.utcnow().date()

                log = FuelLog(
                    vehicle_id=vehicle_id,
                    user_id=current_user.id,
                    date=date,
                    odometer=float(hf['odo_reading']) if hf['odo_reading'] else 0,
                    volume=float(hf['fuel_quantity']) if hf['fuel_quantity'] else None,
                    price_per_unit=float(hf['per_unit_price']) if hf['per_unit_price'] else None,
                    total_cost=float(hf['total_amount']) if hf['total_amount'] else None,
                    is_full_tank=bool(hf['is_tank_full']) if hf['is_tank_full'] is not None else True,
                    is_missed=bool(hf['has_missed_fillup']) if hf['has_missed_fillup'] is not None else False,
                    station=hf['filling_station'],
                    notes=hf['comments']
                )
                db.session.add(log)
                stats['fuel_logs'] += 1

        except sqlite3.OperationalError:
            pass  # Table doesn't exist

        # Import expenses
        try:
            cursor.execute('SELECT * FROM expenses')
            hammond_expenses = cursor.fetchall()

            for he in hammond_expenses:
                vehicle_id = vehicle_id_map.get(he['vehicle_id'])
                if not vehicle_id:
                    continue

                # Parse date
                try:
                    if he['date']:
                        date = datetime.fromisoformat(he['date'].replace('Z', '+00:00')).date()
                    else:
                        date = datetime.utcnow().date()
                except (ValueError, TypeError):
                    date = datetime.utcnow().date()

                # Map expense type
                expense_type = (he['expense_type'] or 'other').lower()
                valid_categories = [c[0] for c in EXPENSE_CATEGORIES]
                if expense_type not in valid_categories:
                    expense_type = 'other'

                expense = Expense(
                    vehicle_id=vehicle_id,
                    user_id=current_user.id,
                    date=date,
                    category=expense_type,
                    description=he['expense_type'] or 'Imported expense',
                    cost=float(he['amount']) if he['amount'] else 0,
                    odometer=float(he['odo_reading']) if he['odo_reading'] else None,
                    notes=he['comments']
                )
                db.session.add(expense)
                stats['expenses'] += 1

        except sqlite3.OperationalError:
            pass  # Table doesn't exist

        db.session.commit()
        conn.close()

        flash(f"Hammond import complete: {stats['vehicles']} vehicles, {stats['fuel_logs']} fuel logs, {stats['expenses']} expenses", 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Import failed: {str(e)}', 'error')

    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return redirect(url_for('auth.settings') + '#integrations')


@bp.route('/import/clarkson', methods=['POST'])
@login_required
def import_clarkson():
    """
    Import data from Clarkson MySQL database.
    Expects a .sql dump file upload.
    """
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    file = request.files['file']
    if not file.filename:
        flash('No file selected', 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    try:
        # Read SQL dump content
        content = file.read().decode('utf-8', errors='ignore')

        # Track import statistics
        stats = {'vehicles': 0, 'fuel_logs': 0}
        vehicle_id_map = {}  # Clarkson vehicle ID -> May vehicle ID

        # Parse INSERT statements for Vehicles table
        # Clarkson format: INSERT INTO `Vehicles` VALUES (id, userId, name, registration, make, model, yearOfManufacture, engineSizeCC, fuelType, active)
        import re

        # Find Vehicles INSERT statements
        vehicle_pattern = r"INSERT INTO [`']?Vehicles[`']?\s+(?:VALUES\s*)?\(([^)]+)\)"
        vehicle_matches = re.findall(vehicle_pattern, content, re.IGNORECASE)

        # Also try multi-value inserts
        vehicle_multi_pattern = r"INSERT INTO [`']?Vehicles[`']?[^;]*VALUES\s*((?:\([^)]+\)\s*,?\s*)+)"
        vehicle_multi_matches = re.findall(vehicle_multi_pattern, content, re.IGNORECASE)

        for match in vehicle_multi_matches:
            # Extract individual value tuples
            tuples = re.findall(r'\(([^)]+)\)', match)
            vehicle_matches.extend(tuples)

        for values_str in vehicle_matches:
            try:
                # Parse CSV-like values (handling quoted strings)
                values = parse_sql_values(values_str)
                if len(values) >= 9:
                    clarkson_id = int(values[0]) if values[0] else None
                    name = clean_sql_string(values[2])
                    registration = clean_sql_string(values[3])
                    make = clean_sql_string(values[4])
                    model = clean_sql_string(values[5])
                    year = int(values[6]) if values[6] and values[6] != 'NULL' else None
                    fuel_type_id = int(values[8]) if values[8] and values[8] != 'NULL' else 1

                    fuel_type = CLARKSON_FUEL_TYPES.get(fuel_type_id, 'petrol')

                    vehicle = Vehicle(
                        owner_id=current_user.id,
                        name=name or f"{make} {model}".strip() or 'Imported Vehicle',
                        vehicle_type='car',
                        make=make,
                        model=model,
                        year=year,
                        registration=registration,
                        fuel_type=fuel_type,
                        notes=f"Imported from Clarkson (ID: {clarkson_id})"
                    )
                    db.session.add(vehicle)
                    db.session.flush()
                    if clarkson_id:
                        vehicle_id_map[clarkson_id] = vehicle.id
                    stats['vehicles'] += 1

            except (ValueError, IndexError) as e:
                continue

        # Find Fuel INSERT statements
        # Clarkson format: INSERT INTO `Fuel` VALUES (id, vehicleId, fuelAmount, fuelUnitCost, totalCost, odometerReading, dateTime, fullTank, missedFillUp, userId, fuelUnit, location, lat, lng)
        fuel_pattern = r"INSERT INTO [`']?Fuel[`']?\s+(?:VALUES\s*)?\(([^)]+)\)"
        fuel_matches = re.findall(fuel_pattern, content, re.IGNORECASE)

        fuel_multi_pattern = r"INSERT INTO [`']?Fuel[`']?[^;]*VALUES\s*((?:\([^)]+\)\s*,?\s*)+)"
        fuel_multi_matches = re.findall(fuel_multi_pattern, content, re.IGNORECASE)

        for match in fuel_multi_matches:
            tuples = re.findall(r'\(([^)]+)\)', match)
            fuel_matches.extend(tuples)

        for values_str in fuel_matches:
            try:
                values = parse_sql_values(values_str)
                if len(values) >= 10:
                    clarkson_vehicle_id = int(values[1]) if values[1] else None
                    vehicle_id = vehicle_id_map.get(clarkson_vehicle_id)
                    if not vehicle_id:
                        continue

                    # Parse date
                    date_str = clean_sql_string(values[6])
                    try:
                        date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').date() if date_str else datetime.utcnow().date()
                    except ValueError:
                        try:
                            date = datetime.strptime(date_str, '%Y-%m-%d').date()
                        except ValueError:
                            date = datetime.utcnow().date()

                    station = clean_sql_string(values[11]) if len(values) > 11 else None

                    log = FuelLog(
                        vehicle_id=vehicle_id,
                        user_id=current_user.id,
                        date=date,
                        odometer=float(values[5]) if values[5] and values[5] != 'NULL' else 0,
                        volume=float(values[2]) if values[2] and values[2] != 'NULL' else None,
                        price_per_unit=float(values[3]) if values[3] and values[3] != 'NULL' else None,
                        total_cost=float(values[4]) if values[4] and values[4] != 'NULL' else None,
                        is_full_tank=values[7] == '1' if values[7] else True,
                        is_missed=values[8] == '1' if values[8] else False,
                        station=station,
                    )
                    db.session.add(log)
                    stats['fuel_logs'] += 1

            except (ValueError, IndexError) as e:
                continue

        db.session.commit()
        flash(f"Clarkson import complete: {stats['vehicles']} vehicles, {stats['fuel_logs']} fuel logs", 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Import failed: {str(e)}', 'error')

    return redirect(url_for('auth.settings') + '#integrations')


def parse_sql_values(values_str):
    """Parse SQL INSERT values handling quoted strings and NULLs"""
    values = []
    current = ''
    in_quotes = False
    quote_char = None

    for char in values_str:
        if char in ("'", '"') and not in_quotes:
            in_quotes = True
            quote_char = char
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
        elif char == ',' and not in_quotes:
            values.append(current.strip())
            current = ''
            continue
        current += char

    if current:
        values.append(current.strip())

    return values


def clean_sql_string(value):
    """Clean a SQL string value, removing quotes and handling NULL"""
    if not value or value.upper() == 'NULL':
        return None
    value = value.strip()
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        value = value[1:-1]
    return value.replace("\\'", "'").replace('\\"', '"')


@bp.route('/import/fuelly', methods=['POST'])
@login_required
def import_fuelly():
    """
    Import data from Fuelly CSV export.
    Expects a CSV file with columns: Name, Model, MPG, Odometer, Miles, Gallons, Price, Fuelup Date, Date Added, Tags, Notes
    """
    if 'file' not in request.files:
        flash('No file uploaded', 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    file = request.files['file']
    if not file.filename:
        flash('No file selected', 'error')
        return redirect(url_for('auth.settings') + '#integrations')

    try:
        # Read CSV content
        content = file.read().decode('utf-8-sig', errors='ignore')  # utf-8-sig handles BOM
        reader = csv.DictReader(io.StringIO(content))

        # Track import statistics
        stats = {'vehicles': 0, 'fuel_logs': 0}
        vehicle_cache = {}  # Vehicle name -> Vehicle object

        for row in reader:
            try:
                # Get or create vehicle
                # Fuelly uses "Name" for vehicle name and "Model" for model
                vehicle_name = row.get('Name', '').strip()
                vehicle_model = row.get('Model', '').strip()

                if not vehicle_name:
                    vehicle_name = vehicle_model or 'Imported Vehicle'

                # Create a unique key for the vehicle
                vehicle_key = f"{vehicle_name}|{vehicle_model}"

                if vehicle_key not in vehicle_cache:
                    # Check if vehicle already exists for this user
                    existing = Vehicle.query.filter_by(
                        owner_id=current_user.id,
                        name=vehicle_name
                    ).first()

                    if existing:
                        vehicle_cache[vehicle_key] = existing
                    else:
                        vehicle = Vehicle(
                            owner_id=current_user.id,
                            name=vehicle_name,
                            vehicle_type='car',
                            model=vehicle_model if vehicle_model != vehicle_name else None,
                            fuel_type='petrol',
                            notes='Imported from Fuelly'
                        )
                        db.session.add(vehicle)
                        db.session.flush()
                        vehicle_cache[vehicle_key] = vehicle
                        stats['vehicles'] += 1

                vehicle = vehicle_cache[vehicle_key]

                # Parse fuel log data
                # Fuelly date formats: YYYY-MM-DD or M/D/YY or M/D/YYYY
                date_str = row.get('Fuelup Date', '').strip() or row.get('Date', '').strip()
                date = None
                if date_str:
                    for fmt in ['%Y-%m-%d', '%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d %H:%M:%S']:
                        try:
                            date = datetime.strptime(date_str, fmt).date()
                            break
                        except ValueError:
                            continue

                if not date:
                    date = datetime.utcnow().date()

                # Parse numeric values - Fuelly uses US units (gallons, miles)
                odometer_str = row.get('Odometer', '').strip().replace(',', '')
                gallons_str = row.get('Gallons', '').strip().replace(',', '')
                price_str = row.get('Price', '').strip().replace(',', '').replace('$', '')
                miles_str = row.get('Miles', '').strip().replace(',', '')

                odometer = float(odometer_str) if odometer_str else None
                gallons = float(gallons_str) if gallons_str else None
                price = float(price_str) if price_str else None

                # Calculate total cost if we have gallons and price
                total_cost = None
                if gallons and price:
                    total_cost = round(gallons * price, 2)

                # Get notes and tags
                notes = row.get('Notes', '').strip()
                tags = row.get('Tags', '').strip()
                if tags and notes:
                    notes = f"{notes} [Tags: {tags}]"
                elif tags:
                    notes = f"[Tags: {tags}]"

                # Check for partial fill indicator
                # Fuelly uses "Partial" column or notes may indicate partial fill
                is_partial = row.get('Partial', '').strip().lower() in ('1', 'yes', 'true', 'partial')
                is_full_tank = not is_partial

                # Create fuel log (only if we have meaningful data)
                if odometer or gallons:
                    log = FuelLog(
                        vehicle_id=vehicle.id,
                        user_id=current_user.id,
                        date=date,
                        odometer=odometer or 0,
                        volume=gallons,  # Store in original units (gallons)
                        price_per_unit=price,
                        total_cost=total_cost,
                        is_full_tank=is_full_tank,
                        is_missed=False,
                        notes=notes if notes else None
                    )
                    db.session.add(log)
                    stats['fuel_logs'] += 1

            except (ValueError, KeyError) as e:
                continue

        db.session.commit()
        flash(f"Fuelly import complete: {stats['vehicles']} new vehicles, {stats['fuel_logs']} fuel logs", 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Import failed: {str(e)}', 'error')

    return redirect(url_for('auth.settings') + '#integrations')
