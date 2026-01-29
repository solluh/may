from flask import Blueprint, render_template, redirect, url_for, send_from_directory, current_app
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from app.models import Vehicle, FuelLog, Expense

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@bp.route('/offline')
def offline():
    """Offline page for PWA"""
    return render_template('offline.html')


@bp.route('/sw.js')
def service_worker():
    """Serve service worker from root URL for proper scope"""
    return send_from_directory(
        current_app.static_folder, 'sw.js',
        mimetype='application/javascript'
    )


@bp.route('/dashboard')
@login_required
def dashboard():
    vehicles = current_user.get_all_vehicles()

    # Calculate statistics
    total_fuel_cost = 0
    total_expense_cost = 0
    total_distance = 0
    recent_logs = []
    recent_expenses = []

    vehicle_ids = [v.id for v in vehicles]

    if vehicle_ids:
        # Total costs
        fuel_result = db.session.query(func.sum(FuelLog.total_cost)).filter(
            FuelLog.vehicle_id.in_(vehicle_ids)
        ).scalar()
        total_fuel_cost = fuel_result or 0

        expense_result = db.session.query(func.sum(Expense.cost)).filter(
            Expense.vehicle_id.in_(vehicle_ids)
        ).scalar()
        total_expense_cost = expense_result or 0

        # Total distance
        for vehicle in vehicles:
            total_distance += vehicle.get_total_distance()

        # Recent activity
        recent_logs = FuelLog.query.filter(
            FuelLog.vehicle_id.in_(vehicle_ids)
        ).order_by(FuelLog.date.desc()).limit(5).all()

        recent_expenses = Expense.query.filter(
            Expense.vehicle_id.in_(vehicle_ids)
        ).order_by(Expense.date.desc()).limit(5).all()

    # Monthly spending for chart (last 6 months)
    monthly_data = get_monthly_spending(vehicle_ids)

    return render_template('dashboard.html',
                           vehicles=vehicles,
                           total_fuel_cost=total_fuel_cost,
                           total_expense_cost=total_expense_cost,
                           total_distance=total_distance,
                           recent_logs=recent_logs,
                           recent_expenses=recent_expenses,
                           monthly_data=monthly_data)


def get_monthly_spending(vehicle_ids):
    """Get monthly fuel and expense spending for the last 6 months"""
    months = []
    fuel_costs = []
    expense_costs = []

    for i in range(5, -1, -1):
        date = datetime.now() - timedelta(days=i * 30)
        month_start = date.replace(day=1)
        if date.month == 12:
            month_end = date.replace(year=date.year + 1, month=1, day=1)
        else:
            month_end = date.replace(month=date.month + 1, day=1)

        months.append(month_start.strftime('%b'))

        if vehicle_ids:
            fuel = db.session.query(func.sum(FuelLog.total_cost)).filter(
                FuelLog.vehicle_id.in_(vehicle_ids),
                FuelLog.date >= month_start,
                FuelLog.date < month_end
            ).scalar() or 0

            expense = db.session.query(func.sum(Expense.cost)).filter(
                Expense.vehicle_id.in_(vehicle_ids),
                Expense.date >= month_start,
                Expense.date < month_end
            ).scalar() or 0
        else:
            fuel = 0
            expense = 0

        fuel_costs.append(round(fuel, 2))
        expense_costs.append(round(expense, 2))

    return {
        'labels': months,
        'fuel': fuel_costs,
        'expenses': expense_costs
    }
