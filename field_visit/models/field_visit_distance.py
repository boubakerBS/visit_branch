# -*- coding: utf-8 -*-
import logging
import math

from odoo import models

_logger = logging.getLogger(__name__)


class FieldVisitDistance(models.AbstractModel):
    """Pluggable distance calculation. The provider is chosen in
    Settings (ir.config_parameter) - default is a free straight-line
    (Haversine) estimate that needs no external service at all. If a
    Google Maps API key is entered later in Settings, distances switch
    automatically to real driving distance/duration - no code change,
    no model change, nothing else to touch.
    """
    _name = 'field.visit.distance'
    _description = 'Field Visit Distance Provider'

    def get_distance_km(self, lat1, lng1, lat2, lng2):
        """Returns distance in km (float) between two coordinates.
        Falls back to the straight-line estimate if the configured
        provider fails for any reason (missing key, network error,
        quota...) so route generation never breaks because of it."""
        if not (lat1 and lng1 and lat2 and lng2):
            return 0.0

        provider = self.env['ir.config_parameter'].sudo().get_param(
            'field_visit.distance_provider', 'haversine')

        if provider == 'google':
            distance = self._get_distance_google(lat1, lng1, lat2, lng2)
            if distance is not None:
                return distance
            _logger.warning(
                "Google distance lookup failed, falling back to "
                "straight-line estimate.")
        elif provider == 'osrm':
            distance = self._get_distance_matrix_osrm([(lat1, lng1), (lat2, lng2)])
            if distance is not None:
                return distance[0][1]
            _logger.warning(
                "OSRM distance lookup failed, falling back to "
                "straight-line estimate.")

        return self._get_distance_haversine(lat1, lng1, lat2, lng2)

    def get_distance_matrix_km(self, points):
        """Returns a full NxN distance matrix (km, list of lists) for
        the given list of (lat, lng) points, in the same order. Used
        by route ordering (nearest-neighbor) so we fetch the whole
        matrix in ONE call instead of many repeated pairwise calls -
        this matters most for OSRM/Google where each pairwise call is
        a real HTTP request. Falls back to Haversine per-pair (fast,
        local, no network) on any failure."""
        provider = self.env['ir.config_parameter'].sudo().get_param(
            'field_visit.distance_provider', 'haversine')

        if provider == 'osrm':
            matrix = self._get_distance_matrix_osrm(points)
            if matrix is not None:
                return matrix
            _logger.warning(
                "OSRM matrix lookup failed, falling back to "
                "straight-line estimates.")

        # Haversine fallback (also used directly when provider is
        # 'haversine', and for 'google' since its API bills per
        # element and a full matrix here could be costly - Google is
        # instead used for the single pairwise GPS-verification calls
        # via get_distance_km above).
        return [
            [self._get_distance_haversine(p1[0], p1[1], p2[0], p2[1])
             for p2 in points]
            for p1 in points
        ]

    @staticmethod
    def _get_distance_haversine(lat1, lng1, lat2, lng2):
        """Free, offline, always-available straight-line distance. Real
        driving distance is usually 20-40% longer than this - it is
        only meant as a good-enough estimate for ordering stops, not
        as an exact figure."""
        R = 6371.0  # Earth radius in km
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lng2 - lng1)
        a = (math.sin(d_phi / 2) ** 2
             + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(R * c, 2)

    def _get_distance_matrix_osrm(self, points):
        """Real road-distance matrix via OSRM's free public Table
        Service - one HTTP call regardless of how many points, no API
        key needed. Returns None on any failure (caller falls back to
        Haversine automatically)."""
        try:
            import requests
            # OSRM expects "lng,lat" pairs, the opposite of our (lat, lng).
            coords = ';'.join(f'{lng},{lat}' for lat, lng in points)
            resp = requests.get(
                f'https://router.project-osrm.org/table/v1/driving/{coords}',
                params={'annotations': 'distance'},
                timeout=10,
            )
            data = resp.json()
            if data.get('code') != 'Ok':
                return None
            # OSRM returns meters - convert to km.
            return [
                [round(d / 1000.0, 2) if d is not None else 0.0 for d in row]
                for row in data['distances']
            ]
        except Exception:
            _logger.exception("OSRM Table API call failed")
            return None

    def _get_distance_google(self, lat1, lng1, lat2, lng2):
        """Real driving distance via the Google Maps Distance Matrix
        API. Only called when both a provider='google' setting AND an
        API key are configured. Returns None on any failure so the
        caller falls back to the free estimate automatically."""
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'field_visit.google_maps_api_key')
        if not api_key:
            return None
        try:
            import requests
            resp = requests.get(
                'https://maps.googleapis.com/maps/api/distancematrix/json',
                params={
                    'origins': f'{lat1},{lng1}',
                    'destinations': f'{lat2},{lng2}',
                    'key': api_key,
                },
                timeout=5,
            )
            data = resp.json()
            element = data['rows'][0]['elements'][0]
            if element.get('status') != 'OK':
                return None
            return round(element['distance']['value'] / 1000.0, 2)
        except Exception:
            _logger.exception("Google Distance Matrix API call failed")
            return None