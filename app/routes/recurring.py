from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_babel import gettext as _
from app import db
from app.utils import parse_decimal
from app.models import RecurringExpense, Vehicle, Expense, EXPENSE_CATEGORIES
from datetime import date
from dateutil.relativedelta import relativedelta

bp = Blueprint('recurring', __name__, url_prefix='/recurring')


@bp.route('/')
@login_required
def index():
    """List all recurring expenses."""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]

    recurring = RecurringExpense.query.filter(
        RecurringExpense.vehicle_id.in_(vehicle_ids)
    ).order_by(RecurringExpense.next_due.asc()).all()

    return render_template('recurring/index.html',
                         recurring=recurring,
                         vehicles=vehicles,
                         categories=EXPENSE_CATEGORIES)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Create a new recurring expense."""
    vehicles = current_user.get_all_vehicles()

    if not vehicles:
        flash(_('Please add a vehicle first.'), 'warning')
        return redirect(url_for('vehicles.new'))

    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id', type=int)

        # Verify user has access to vehicle
        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle or vehicle not in vehicles:
            flash(_('Invalid vehicle.'), 'error')
            return redirect(url_for('recurring.new'))

        # Parse dates
        start_date = None
        next_due = None
        if request.form.get('start_date'):
            start_date = date.fromisoformat(request.form['start_date'])
            next_due = start_date

        recurring = RecurringExpense(
            vehicle_id=vehicle_id,
            user_id=current_user.id,
            name=request.form['name'],
            category=request.form['category'],
            frequency=request.form['frequency'],
            amount=parse_decimal(request.form['amount']) if request.form.get('amount') else None,
            start_date=start_date,
            next_due=next_due,
            description=request.form.get('description'),
            auto_create=request.form.get('auto_create') == 'on',
            notify_before_days=int(request.form.get('remind_days_before', 7))
        )

        db.session.add(recurring)
        db.session.commit()

        flash(_('Recurring expense created.'), 'success')
        return redirect(url_for('recurring.index'))

    return render_template('recurring/form.html',
                         vehicles=vehicles,
                         categories=EXPENSE_CATEGORIES,
                         selected_vehicle=request.args.get('vehicle'))


@bp.route('/<int:recurring_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(recurring_id):
    """Edit a recurring expense."""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]
    recurring = RecurringExpense.query.filter(
        RecurringExpense.id == recurring_id,
        RecurringExpense.vehicle_id.in_(vehicle_ids)
    ).first_or_404()

    if request.method == 'POST':
        # Parse dates
        start_date = None
        if request.form.get('start_date'):
            start_date = date.fromisoformat(request.form['start_date'])

        next_due = None
        if request.form.get('next_due'):
            next_due = date.fromisoformat(request.form['next_due'])

        recurring.name = request.form['name']
        recurring.category = request.form['category']
        recurring.frequency = request.form['frequency']
        recurring.amount = parse_decimal(request.form['amount']) if request.form.get('amount') else None
        recurring.start_date = start_date
        recurring.next_due = next_due
        recurring.description = request.form.get('description')
        recurring.auto_create = request.form.get('auto_create') == 'on'
        recurring.notify_before_days = int(request.form.get('remind_days_before', 7))

        db.session.commit()

        flash(_('Recurring expense updated.'), 'success')
        return redirect(url_for('recurring.index'))

    return render_template('recurring/form.html',
                         recurring=recurring,
                         vehicles=[recurring.vehicle],
                         categories=EXPENSE_CATEGORIES)


@bp.route('/<int:recurring_id>/delete', methods=['POST'])
@login_required
def delete(recurring_id):
    """Delete a recurring expense."""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]
    recurring = RecurringExpense.query.filter(
        RecurringExpense.id == recurring_id,
        RecurringExpense.vehicle_id.in_(vehicle_ids)
    ).first_or_404()

    db.session.delete(recurring)
    db.session.commit()

    flash(_('Recurring expense deleted.'), 'success')
    return redirect(url_for('recurring.index'))


@bp.route('/<int:recurring_id>/generate', methods=['POST'])
@login_required
def generate(recurring_id):
    """Manually generate an expense entry from a recurring expense."""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]
    recurring = RecurringExpense.query.filter(
        RecurringExpense.id == recurring_id,
        RecurringExpense.vehicle_id.in_(vehicle_ids)
    ).first_or_404()

    # Create expense entry using the recurring expense's due date
    expense = Expense(
        vehicle_id=recurring.vehicle_id,
        user_id=recurring.user_id,
        date=recurring.next_due or date.today(),
        category=recurring.category,
        cost=recurring.amount or 0,
        description=f"{recurring.name} (auto-generated)"
    )

    db.session.add(expense)

    # Update next due date
    if recurring.next_due:
        if recurring.frequency == 'monthly':
            recurring.next_due = recurring.next_due + relativedelta(months=1)
        elif recurring.frequency == 'quarterly':
            recurring.next_due = recurring.next_due + relativedelta(months=3)
        elif recurring.frequency == 'biannual':
            recurring.next_due = recurring.next_due + relativedelta(months=6)
        elif recurring.frequency == 'yearly':
            recurring.next_due = recurring.next_due + relativedelta(years=1)

    db.session.commit()

    flash(_('Expense created for %(name)s.') % {'name': recurring.name}, 'success')
    return redirect(url_for('recurring.index'))


@bp.route('/<int:recurring_id>/toggle', methods=['POST'])
@login_required
def toggle_active(recurring_id):
    """Toggle active status of a recurring expense."""
    vehicles = current_user.get_all_vehicles()
    vehicle_ids = [v.id for v in vehicles]
    recurring = RecurringExpense.query.filter(
        RecurringExpense.id == recurring_id,
        RecurringExpense.vehicle_id.in_(vehicle_ids)
    ).first_or_404()

    recurring.is_active = not recurring.is_active
    db.session.commit()

    status = 'activated' if recurring.is_active else 'paused'
    flash(_('Recurring expense %(status)s.') % {'status': status}, 'success')
    return redirect(url_for('recurring.index'))
