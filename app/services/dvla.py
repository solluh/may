"""
DVLA Vehicle Enquiry Service Integration

Uses the official DVLA VES API to look up vehicle information including:
- MOT status and expiry date
- Road tax status and due date
- Vehicle details (make, model, colour, fuel type)

API Documentation: https://developer-portal.driver-vehicle-licensing.api.gov.uk/
"""

import requests
from datetime import datetime
from app.models import AppSettings


class DVLAService:
    """Service for interacting with the DVLA Vehicle Enquiry Service API"""

    BASE_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"

    @classmethod
    def get_api_key(cls):
        """Get the DVLA API key from app settings"""
        return AppSettings.get('dvla_api_key')

    @classmethod
    def is_configured(cls):
        """Check if DVLA integration is configured"""
        return bool(cls.get_api_key())

    @classmethod
    def lookup_vehicle(cls, registration):
        """
        Look up vehicle information from DVLA

        Args:
            registration: UK vehicle registration number (e.g., "AB12CDE")

        Returns:
            tuple: (success: bool, data: dict or error: str)

        On success, data contains:
            - registration: Registration mark
            - make: Vehicle make
            - model: Vehicle model (may be None)
            - colour: Vehicle colour
            - fuel_type: Fuel type (PETROL, DIESEL, ELECTRIC, etc.)
            - year_of_manufacture: Year of manufacture
            - engine_capacity: Engine capacity in CC (if applicable)
            - co2_emissions: CO2 emissions g/km (if applicable)
            - mot_status: MOT status (Valid, Not valid, No details held)
            - mot_expiry_date: MOT expiry date (datetime.date or None)
            - tax_status: Tax status (Taxed, Untaxed, SORN, etc.)
            - tax_due_date: Tax due date (datetime.date or None)
            - type_approval: Type approval category
            - wheelplan: Wheelplan description
            - revenue_weight: Revenue weight in kg (if applicable)
        """
        api_key = cls.get_api_key()
        if not api_key:
            return False, "DVLA API key not configured"

        # Clean the registration number (remove spaces, uppercase)
        registration = registration.upper().replace(" ", "").replace("-", "")

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "registrationNumber": registration
        }

        try:
            response = requests.post(
                cls.BASE_URL,
                json=payload,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return True, cls._parse_response(data)
            elif response.status_code == 404:
                return False, "Vehicle not found"
            elif response.status_code == 400:
                return False, "Invalid registration number format"
            elif response.status_code == 403:
                return False, "Invalid DVLA API key"
            else:
                return False, f"DVLA API error: {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "DVLA API request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"DVLA API connection error: {str(e)}"

    @classmethod
    def _parse_response(cls, data):
        """Parse the DVLA API response into a standardized format"""
        result = {
            'registration': data.get('registrationNumber'),
            'make': data.get('make'),
            'model': data.get('model'),  # May not always be available
            'colour': data.get('colour'),
            'fuel_type': data.get('fuelType'),
            'year_of_manufacture': data.get('yearOfManufacture'),
            'engine_capacity': data.get('engineCapacity'),
            'co2_emissions': data.get('co2Emissions'),
            'mot_status': data.get('motStatus'),
            'mot_expiry_date': None,
            'tax_status': data.get('taxStatus'),
            'tax_due_date': None,
            'type_approval': data.get('typeApproval'),
            'wheelplan': data.get('wheelplan'),
            'revenue_weight': data.get('revenueWeight'),
            'date_of_last_v5c_issued': None,
            'marked_for_export': data.get('markedForExport', False),
        }

        # Parse MOT expiry date
        if data.get('motExpiryDate'):
            try:
                result['mot_expiry_date'] = datetime.strptime(
                    data['motExpiryDate'], '%Y-%m-%d'
                ).date()
            except (ValueError, TypeError):
                pass

        # Parse tax due date
        if data.get('taxDueDate'):
            try:
                result['tax_due_date'] = datetime.strptime(
                    data['taxDueDate'], '%Y-%m-%d'
                ).date()
            except (ValueError, TypeError):
                pass

        # Parse date of last V5C issued
        if data.get('dateOfLastV5CIssued'):
            try:
                result['date_of_last_v5c_issued'] = datetime.strptime(
                    data['dateOfLastV5CIssued'], '%Y-%m-%d'
                ).date()
            except (ValueError, TypeError):
                pass

        return result

    @classmethod
    def map_fuel_type(cls, dvla_fuel_type):
        """Map DVLA fuel type to May fuel type"""
        mapping = {
            'PETROL': 'petrol',
            'DIESEL': 'diesel',
            'ELECTRIC': 'electric',
            'ELECTRICITY': 'electric',
            'HYBRID ELECTRIC': 'hybrid',
            'PETROL/ELECTRIC': 'hybrid',
            'DIESEL/ELECTRIC': 'hybrid',
            'GAS': 'lpg',
            'GAS/PETROL': 'lpg',
            'GAS BI-FUEL': 'lpg',
        }
        return mapping.get(dvla_fuel_type.upper() if dvla_fuel_type else '', 'petrol')

    @classmethod
    def test_api_key(cls, api_key):
        """
        Test if a DVLA API key is valid

        Uses a known test registration to verify the key works
        """
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }

        # Use a generic registration format to test
        payload = {
            "registrationNumber": "AA19AAA"
        }

        try:
            response = requests.post(
                cls.BASE_URL,
                json=payload,
                headers=headers,
                timeout=10
            )

            # 200 = valid key, found vehicle
            # 404 = valid key, vehicle not found (this is fine for testing)
            # 403 = invalid key
            if response.status_code in [200, 404]:
                return True, "API key is valid"
            elif response.status_code == 403:
                return False, "Invalid API key"
            else:
                return False, f"Unexpected response: {response.status_code}"

        except requests.exceptions.Timeout:
            return False, "Request timed out"
        except requests.exceptions.RequestException as e:
            return False, f"Connection error: {str(e)}"
