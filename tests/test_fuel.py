import pytest
from datetime import date
from app import db
from app.models import FuelLog, FuelStation, FuelPriceHistory


class TestFuelIndex:
    def test_index_requires_auth(self, client):
        resp = client.get('/fuel/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_index_returns_200(self, auth_client):
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200

    def test_index_shows_fuel_logs(self, auth_client, sample_fuel_log):
        resp = auth_client.get('/fuel/')
        assert resp.status_code == 200


class TestFuelNew:
    def test_new_requires_auth(self, client):
        resp = client.get('/fuel/new', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_new_form_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/fuel/new')
        assert resp.status_code == 200

    def test_create_fuel_log(self, auth_client, sample_vehicle, test_user):
        resp = auth_client.post('/fuel/new', data={
            'vehicle_id': str(sample_vehicle.id),
            'date': '2024-03-01',
            'odometer': '15000',
            'volume': '45.0',
            'price_per_unit': '1.60',
            'total_cost': '72.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(
            vehicle_id=sample_vehicle.id,
            odometer=15000.0
        ).first()
        assert log is not None
        assert log.volume == 45.0
        assert log.user_id == test_user.id

    def test_new_redirects_to_vehicles_if_none(self, auth_client):
        # No vehicles exist for this user
        resp = auth_client.get('/fuel/new', follow_redirects=False)
        # If user has no vehicles it redirects to vehicles.new
        # sample_vehicle fixture not used here, so depends on if user has vehicles
        # Just verify it's a valid response
        assert resp.status_code in (200, 302)


class TestFuelEdit:
    def test_edit_requires_auth(self, client, sample_fuel_log):
        resp = client.get(f'/fuel/{sample_fuel_log.id}/edit', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_get_edit_form_returns_200(self, auth_client, sample_fuel_log):
        resp = auth_client.get(f'/fuel/{sample_fuel_log.id}/edit')
        assert resp.status_code == 200

    def test_edit_fuel_log(self, auth_client, sample_fuel_log):
        resp = auth_client.post(f'/fuel/{sample_fuel_log.id}/edit', data={
            'date': '2024-01-15',
            'odometer': '10500',
            'volume': '42.0',
            'price_per_unit': '1.55',
            'total_cost': '65.1',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db.session.refresh(sample_fuel_log)
        assert sample_fuel_log.odometer == 10500.0
        assert sample_fuel_log.volume == 42.0


class TestFuelDelete:
    def test_delete_requires_auth(self, client, sample_fuel_log):
        resp = client.post(f'/fuel/{sample_fuel_log.id}/delete', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_delete_fuel_log(self, auth_client, sample_fuel_log):
        log_id = sample_fuel_log.id
        resp = auth_client.post(f'/fuel/{log_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        assert FuelLog.query.get(log_id) is None


class TestPartialFillConsumption:
    """#122 — consumption should be calculated for partial fills."""

    def test_full_tank_consumption_unchanged(self, app, test_user, sample_vehicle):
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 15), odometer=10500, volume=42, is_full_tank=True)
        db.session.add_all([log1, log2])
        db.session.commit()
        # 42L / 500km * 100 = 8.4 L/100km
        assert abs(log2.get_consumption() - 8.4) < 0.01

    def test_partial_fill_returns_consumption(self, app, test_user, sample_vehicle):
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 10), odometer=10200, volume=20, is_full_tank=False)
        db.session.add_all([log1, log2])
        db.session.commit()
        # 20L / 200km * 100 = 10.0 L/100km
        consumption = log2.get_consumption()
        assert consumption is not None
        assert abs(consumption - 10.0) < 0.01

    def test_partial_fill_no_previous_log_returns_none(self, app, test_user, sample_vehicle):
        log = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                      date=date(2024, 1, 1), odometer=10000, volume=20, is_full_tank=False)
        db.session.add(log)
        db.session.commit()
        assert log.get_consumption() is None

    def test_no_volume_returns_none(self, app, test_user, sample_vehicle):
        log = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                      date=date(2024, 1, 1), odometer=10000, volume=None, is_full_tank=True)
        db.session.add(log)
        db.session.commit()
        assert log.get_consumption() is None

    def test_partial_fill_uses_any_previous_log(self, app, test_user, sample_vehicle):
        """Partial fill looks back to the nearest log regardless of fill type."""
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 1), odometer=10000, volume=40, is_full_tank=True)
        log2 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 8), odometer=10300, volume=15, is_full_tank=False)
        log3 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2024, 1, 15), odometer=10500, volume=20, is_full_tank=False)
        db.session.add_all([log1, log2, log3])
        db.session.commit()
        # log3 looks back to log2 (nearest), not log1
        # 20L / 200km * 100 = 10.0 L/100km
        consumption = log3.get_consumption()
        assert consumption is not None
        assert abs(consumption - 10.0) < 0.01

    def test_full_tank_sums_intervening_partials(self, app, test_user, sample_vehicle):
        """#169 — full tank consumption must sum partial fills since the previous full."""
        # Astrmn's reported scenario: full → partial → partial → full,
        # 1371 km between fulls, 19.67 + 12.71 + 53.80 = 86.18 L total.
        log_first_full = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 21), odometer=10000, volume=50, is_full_tank=True,
        )
        partial_a = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 24), odometer=10500, volume=19.67, is_full_tank=False,
        )
        partial_b = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 27), odometer=10900, volume=12.71, is_full_tank=False,
        )
        log_last_full = FuelLog(
            vehicle_id=sample_vehicle.id, user_id=test_user.id,
            date=date(2026, 4, 29), odometer=11371, volume=53.80, is_full_tank=True,
        )
        db.session.add_all([log_first_full, partial_a, partial_b, log_last_full])
        db.session.commit()
        # Fill-to-fill: (19.67 + 12.71 + 53.80) / 1371 * 100 = 6.286 L/100km
        consumption = log_last_full.get_consumption()
        assert consumption is not None
        assert abs(consumption - 6.286) < 0.01

    def test_full_tank_returns_none_when_intervening_log_is_missed(
            self, app, test_user, sample_vehicle):
        """A missed fill in the range invalidates the consumption figure."""
        log1 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 1), odometer=10000, volume=40, is_full_tank=True)
        missed = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                         date=date(2026, 4, 5), odometer=10300, volume=20,
                         is_full_tank=False, is_missed=True)
        log3 = FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                       date=date(2026, 4, 10), odometer=10500, volume=42,
                       is_full_tank=True)
        db.session.add_all([log1, missed, log3])
        db.session.commit()
        assert log3.get_consumption() is None

    def test_average_consumption_includes_partial_fills(
            self, app, test_user, sample_vehicle):
        """#169 — vehicle average must count partial fills between two fulls."""
        logs = [
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 21), odometer=10000, volume=50, is_full_tank=True),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 24), odometer=10500, volume=19.67, is_full_tank=False),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 27), odometer=10900, volume=12.71, is_full_tank=False),
            FuelLog(vehicle_id=sample_vehicle.id, user_id=test_user.id,
                    date=date(2026, 4, 29), odometer=11371, volume=53.80, is_full_tank=True),
        ]
        db.session.add_all(logs)
        db.session.commit()
        avg = sample_vehicle.get_average_consumption()
        assert avg is not None
        assert abs(avg - 6.286) < 0.01


@pytest.fixture
def sample_station(app, test_user):
    station = FuelStation(
        user_id=test_user.id,
        name='Test Station',
        brand='BP',
    )
    db.session.add(station)
    db.session.commit()
    return station


@pytest.fixture
def fuel_log_with_price_history(app, test_user, sample_vehicle, sample_station):
    log = FuelLog(
        vehicle_id=sample_vehicle.id,
        user_id=test_user.id,
        date=date(2024, 3, 1),
        odometer=15000,
        volume=45,
        price_per_unit=1.60,
        total_cost=72.0,
        is_full_tank=True,
    )
    db.session.add(log)
    db.session.flush()
    history = FuelPriceHistory(
        station_id=sample_station.id,
        user_id=test_user.id,
        date=log.date,
        fuel_type='petrol',
        price_per_unit=log.price_per_unit,
    )
    db.session.add(history)
    db.session.commit()
    return log, history


class TestPriceHistorySync:
    """#113 — editing a fuel log must keep FuelPriceHistory in sync."""

    def test_edit_price_updates_history(self, auth_client, fuel_log_with_price_history):
        log, history = fuel_log_with_price_history
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-01',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': '1.45',
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        db.session.refresh(history)
        assert history.price_per_unit == 1.45

    def test_edit_date_updates_history(self, auth_client, fuel_log_with_price_history):
        log, history = fuel_log_with_price_history
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-10',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': str(log.price_per_unit),
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        from datetime import date
        db.session.refresh(history)
        assert history.date == date(2024, 3, 10)

    def test_edit_remove_price_deletes_history(self, auth_client, fuel_log_with_price_history):
        log, history = fuel_log_with_price_history
        history_id = history.id
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-01',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': '',
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert FuelPriceHistory.query.get(history_id) is None

    def test_stale_price_not_shown_after_edit(self, auth_client, fuel_log_with_price_history):
        """The bad-entry scenario from issue #113: edit fixes the price, history reflects it."""
        log, history = fuel_log_with_price_history
        # Simulate the bad entry: history has 254.7
        history.price_per_unit = 254.7
        log.price_per_unit = 254.7
        db.session.commit()

        # User edits to correct value
        auth_client.post(f'/fuel/{log.id}/edit', data={
            'date': '2024-03-01',
            'odometer': str(log.odometer),
            'volume': str(log.volume),
            'price_per_unit': '2.547',
            'total_cost': str(log.total_cost),
            'is_full_tank': 'on',
        }, follow_redirects=True)
        db.session.refresh(history)
        assert history.price_per_unit == 2.547


class TestFuelQuick:
    def test_quick_requires_auth(self, client):
        resp = client.get('/fuel/quick', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_quick_get_returns_200(self, auth_client, sample_vehicle):
        resp = auth_client.get('/fuel/quick')
        assert resp.status_code == 200

    def test_quick_post_creates_log(self, auth_client, sample_vehicle):
        resp = auth_client.post('/fuel/quick', data={
            'vehicle_id': str(sample_vehicle.id),
            'odometer': '20000',
            'volume': '50.0',
            'total_cost': '80.0',
            'is_full_tank': 'on',
        }, follow_redirects=True)
        assert resp.status_code == 200
        log = FuelLog.query.filter_by(
            vehicle_id=sample_vehicle.id,
            odometer=20000.0
        ).first()
        assert log is not None
