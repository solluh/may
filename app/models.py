import secrets
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db

# Association table for vehicle sharing
vehicle_users = db.Table('vehicle_users',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('vehicle_id', db.Integer, db.ForeignKey('vehicles.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # User preferences
    language = db.Column(db.String(10), default='en')  # en, de, fr, es, etc.
    distance_unit = db.Column(db.String(10), default='km')  # km, mi
    volume_unit = db.Column(db.String(10), default='L')  # L, gal, us_gal
    consumption_unit = db.Column(db.String(10), default='L/100km')  # L/100km, mpg, mpg_us
    currency = db.Column(db.String(10), default='USD')

    # Notification preferences
    email_reminders = db.Column(db.Boolean, default=True)
    reminder_days_before = db.Column(db.Integer, default=7)  # Days before due date to notify
    notification_method = db.Column(db.String(20), default='email')  # email, webhook, ntfy, pushover, none
    webhook_url = db.Column(db.String(500))  # URL to POST notifications to
    ntfy_topic = db.Column(db.String(200))  # ntfy.sh topic or custom server URL
    pushover_user_key = db.Column(db.String(50))  # Pushover user key

    # API access
    api_key = db.Column(db.String(64), unique=True, index=True)
    api_key_created_at = db.Column(db.DateTime)

    # Relationships
    owned_vehicles = db.relationship('Vehicle', backref='owner', lazy='dynamic',
                                     foreign_keys='Vehicle.owner_id')
    shared_vehicles = db.relationship('Vehicle', secondary=vehicle_users,
                                      backref=db.backref('shared_users', lazy='dynamic'))
    fuel_logs = db.relationship('FuelLog', backref='user', lazy='dynamic')
    expenses = db.relationship('Expense', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_all_vehicles(self):
        """Get all vehicles user has access to (owned + shared)"""
        owned = list(self.owned_vehicles.all())
        shared = list(self.shared_vehicles)
        return list(set(owned + shared))

    def generate_api_key(self):
        """Generate a new API key for this user"""
        self.api_key = f"may_{secrets.token_hex(32)}"
        self.api_key_created_at = datetime.utcnow()
        return self.api_key

    def revoke_api_key(self):
        """Revoke the current API key"""
        self.api_key = None
        self.api_key_created_at = None

    @staticmethod
    def get_by_api_key(api_key):
        """Find user by API key"""
        if not api_key:
            return None
        return User.query.filter_by(api_key=api_key).first()


class Vehicle(db.Model):
    __tablename__ = 'vehicles'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Basic info
    name = db.Column(db.String(100), nullable=False)
    vehicle_type = db.Column(db.String(20), nullable=False)  # car, van, motorbike, scooter
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.Integer)

    # Identification
    registration = db.Column(db.String(20))
    vin = db.Column(db.String(50))

    # Fuel info
    fuel_type = db.Column(db.String(20), default='petrol')  # petrol, diesel, electric, hybrid, lpg
    tank_capacity = db.Column(db.Float)  # in liters

    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Image
    image_filename = db.Column(db.String(255))

    # Notes
    notes = db.Column(db.Text)

    # Relationships
    fuel_logs = db.relationship('FuelLog', backref='vehicle', lazy='dynamic',
                                cascade='all, delete-orphan')
    expenses = db.relationship('Expense', backref='vehicle', lazy='dynamic',
                               cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', backref='vehicle', lazy='dynamic',
                                  cascade='all, delete-orphan')
    specs = db.relationship('VehicleSpec', backref='vehicle', lazy='dynamic',
                            cascade='all, delete-orphan')

    def get_total_fuel_cost(self):
        return sum(log.total_cost for log in self.fuel_logs.all() if log.total_cost)

    def get_total_expense_cost(self):
        return sum(exp.cost for exp in self.expenses.all() if exp.cost)

    def get_total_cost(self):
        return self.get_total_fuel_cost() + self.get_total_expense_cost()

    def get_total_distance(self):
        logs = self.fuel_logs.order_by(FuelLog.odometer).all()
        if len(logs) < 2:
            return 0
        return logs[-1].odometer - logs[0].odometer

    def get_average_consumption(self):
        """Calculate average fuel consumption"""
        logs = self.fuel_logs.filter_by(is_full_tank=True).order_by(FuelLog.odometer).all()
        if len(logs) < 2:
            return None

        total_fuel = sum(log.volume for log in logs[1:] if log.volume)
        total_distance = logs[-1].odometer - logs[0].odometer

        if total_distance > 0:
            return (total_fuel / total_distance) * 100  # L/100km
        return None

    def get_last_odometer(self):
        last_log = self.fuel_logs.order_by(FuelLog.odometer.desc()).first()
        return last_log.odometer if last_log else 0

    def to_dict(self):
        """Serialize vehicle to dictionary for API"""
        return {
            'id': self.id,
            'name': self.name,
            'vehicle_type': self.vehicle_type,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'registration': self.registration,
            'vin': self.vin,
            'fuel_type': self.fuel_type,
            'tank_capacity': self.tank_capacity,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'stats': {
                'total_fuel_cost': round(self.get_total_fuel_cost(), 2),
                'total_expense_cost': round(self.get_total_expense_cost(), 2),
                'total_distance': round(self.get_total_distance(), 2),
                'average_consumption': round(self.get_average_consumption(), 2) if self.get_average_consumption() else None,
                'last_odometer': self.get_last_odometer()
            }
        }


class FuelLog(db.Model):
    __tablename__ = 'fuel_logs'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    odometer = db.Column(db.Float, nullable=False)  # stored in km
    volume = db.Column(db.Float)  # stored in liters
    price_per_unit = db.Column(db.Float)  # price per liter
    total_cost = db.Column(db.Float)

    is_full_tank = db.Column(db.Boolean, default=True)
    is_missed = db.Column(db.Boolean, default=False)  # missed fill-up flag

    station = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    attachments = db.relationship('Attachment', backref='fuel_log', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def get_consumption(self):
        """Calculate consumption for this fill-up"""
        if not self.is_full_tank or not self.volume:
            return None

        prev_log = FuelLog.query.filter(
            FuelLog.vehicle_id == self.vehicle_id,
            FuelLog.odometer < self.odometer,
            FuelLog.is_full_tank == True
        ).order_by(FuelLog.odometer.desc()).first()

        if prev_log:
            distance = self.odometer - prev_log.odometer
            if distance > 0:
                return (self.volume / distance) * 100  # L/100km
        return None

    def to_dict(self):
        """Serialize fuel log to dictionary for API"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'odometer': self.odometer,
            'volume': self.volume,
            'price_per_unit': self.price_per_unit,
            'total_cost': self.total_cost,
            'is_full_tank': self.is_full_tank,
            'is_missed': self.is_missed,
            'station': self.station,
            'notes': self.notes,
            'consumption': round(self.get_consumption(), 2) if self.get_consumption() else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Expense(db.Model):
    __tablename__ = 'expenses'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    category = db.Column(db.String(50), nullable=False)  # maintenance, insurance, repairs, tax, parking, tolls, other
    description = db.Column(db.String(200), nullable=False)
    cost = db.Column(db.Float, nullable=False)
    odometer = db.Column(db.Float)  # optional

    vendor = db.Column(db.String(100))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    attachments = db.relationship('Attachment', backref='expense', lazy='dynamic',
                                  cascade='all, delete-orphan')

    def to_dict(self):
        """Serialize expense to dictionary for API"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'date': self.date.isoformat() if self.date else None,
            'category': self.category,
            'description': self.description,
            'cost': self.cost,
            'odometer': self.odometer,
            'vendor': self.vendor,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Attachment(db.Model):
    __tablename__ = 'attachments'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)

    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'))
    fuel_log_id = db.Column(db.Integer, db.ForeignKey('fuel_logs.id'))
    expense_id = db.Column(db.Integer, db.ForeignKey('expenses.id'))

    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VehicleSpec(db.Model):
    """Custom specifications/attributes for vehicles"""
    __tablename__ = 'vehicle_specs'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)

    spec_type = db.Column(db.String(50), nullable=False)  # predefined or custom type
    label = db.Column(db.String(100), nullable=False)  # display label
    value = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Reminder(db.Model):
    """Reminders for vehicle-related dates and events"""
    __tablename__ = 'reminders'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    reminder_type = db.Column(db.String(50), nullable=False)  # service, mot, insurance, tax, custom
    due_date = db.Column(db.Date, nullable=False)

    # Relationships (defined here since this class is defined last)
    vehicle = db.relationship('Vehicle', backref=db.backref('reminders', lazy='dynamic', cascade='all, delete-orphan'))
    user_rel = db.relationship('User', backref=db.backref('reminders', lazy='dynamic'))

    # Recurrence settings
    recurrence = db.Column(db.String(20), default='none')  # none, monthly, yearly
    recurrence_interval = db.Column(db.Integer, default=1)  # e.g., every 1 year, every 6 months

    # Notification settings
    notify_days_before = db.Column(db.Integer, default=7)
    notification_sent = db.Column(db.Boolean, default=False)

    # Status
    is_completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime)

    # Tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_overdue(self):
        """Check if reminder is past due date"""
        from datetime import date
        return not self.is_completed and self.due_date < date.today()

    def is_upcoming(self, days=7):
        """Check if reminder is coming up within specified days"""
        from datetime import date, timedelta
        if self.is_completed:
            return False
        today = date.today()
        return today <= self.due_date <= today + timedelta(days=days)

    def days_until_due(self):
        """Calculate days until due date"""
        from datetime import date
        return (self.due_date - date.today()).days

    def to_dict(self):
        """Serialize reminder to dictionary"""
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'title': self.title,
            'description': self.description,
            'reminder_type': self.reminder_type,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'recurrence': self.recurrence,
            'is_completed': self.is_completed,
            'is_overdue': self.is_overdue(),
            'days_until_due': self.days_until_due(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class AppSettings(db.Model):
    """Application-wide settings for branding and customization"""
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        """Get a setting value by key"""
        setting = AppSettings.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        """Set a setting value"""
        setting = AppSettings.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = AppSettings(key=key, value=value)
            db.session.add(setting)
        db.session.commit()
        return setting

    @staticmethod
    def get_all_branding():
        """Get all branding settings as a dictionary"""
        defaults = {
            'app_name': 'May',
            'app_tagline': 'Vehicle Management',
            'primary_color': '#0284c7',
            'logo_filename': None,
            'favicon_filename': None,
        }
        settings = AppSettings.query.filter(AppSettings.key.in_(defaults.keys())).all()
        result = defaults.copy()
        for s in settings:
            result[s.key] = s.value
        return result


# Predefined vehicle specification types
VEHICLE_SPEC_TYPES = [
    ('tire_size_front', 'Front Tire Size'),
    ('tire_size_rear', 'Rear Tire Size'),
    ('wheel_size', 'Wheel Size'),
    ('oil_type', 'Engine Oil Type'),
    ('oil_capacity', 'Oil Capacity'),
    ('coolant_type', 'Coolant Type'),
    ('wiper_front', 'Front Wiper Size'),
    ('wiper_rear', 'Rear Wiper Size'),
    ('battery_type', 'Battery Type'),
    ('spark_plug', 'Spark Plug Type'),
    ('air_filter', 'Air Filter Part #'),
    ('cabin_filter', 'Cabin Filter Part #'),
    ('brake_pads_front', 'Front Brake Pads'),
    ('brake_pads_rear', 'Rear Brake Pads'),
    ('transmission_fluid', 'Transmission Fluid'),
    ('custom', 'Custom'),
]

# Expense categories
EXPENSE_CATEGORIES = [
    ('maintenance', 'Maintenance'),
    ('repairs', 'Repairs'),
    ('insurance', 'Insurance'),
    ('tax', 'Road Tax'),
    ('registration', 'Registration'),
    ('parking', 'Parking'),
    ('tolls', 'Tolls'),
    ('cleaning', 'Cleaning'),
    ('accessories', 'Accessories'),
    ('other', 'Other')
]

# Vehicle types
VEHICLE_TYPES = [
    ('car', 'Car'),
    ('van', 'Van'),
    ('motorbike', 'Motorbike'),
    ('scooter', 'Scooter'),
    ('truck', 'Truck'),
    ('suv', 'SUV'),
    ('other', 'Other')
]

# Fuel types
FUEL_TYPES = [
    ('petrol', 'Petrol/Gasoline'),
    ('diesel', 'Diesel'),
    ('electric', 'Electric'),
    ('hybrid', 'Hybrid'),
    ('plugin_hybrid', 'Plug-in Hybrid'),
    ('lpg', 'LPG'),
    ('cng', 'CNG'),
    ('hydrogen', 'Hydrogen'),
    ('e85', 'E85/Flex Fuel'),
    ('other', 'Other')
]

# Reminder types
REMINDER_TYPES = [
    ('mot', 'MOT/Inspection'),
    ('service', 'Service Due'),
    ('insurance', 'Insurance Renewal'),
    ('tax', 'Road Tax'),
    ('registration', 'Registration Renewal'),
    ('warranty', 'Warranty Expiry'),
    ('tire_change', 'Tire Change'),
    ('oil_change', 'Oil Change'),
    ('custom', 'Custom')
]

# Recurrence options
RECURRENCE_OPTIONS = [
    ('none', 'No Repeat'),
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly (3 months)'),
    ('biannual', 'Every 6 months'),
    ('yearly', 'Yearly'),
]
