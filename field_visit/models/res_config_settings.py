# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    field_visit_distance_provider = fields.Selection([
        ('haversine', 'Straight-line estimate (free, no setup)'),
        ('osrm', 'OSRM real road distance (free, public server)'),
        ('google', 'Google Maps Distance Matrix (real driving distance, paid)'),
    ], string="Distance Provider", default='haversine',
        config_parameter='field_visit.distance_provider')

    field_visit_google_maps_api_key = fields.Char(
        string="Google Maps API Key",
        config_parameter='field_visit.google_maps_api_key',
        help="Only required if 'Google Maps Distance Matrix' is "
             "selected above. Leave empty to keep using the free "
             "straight-line estimate.")

    field_visit_proximity_threshold_meters = fields.Integer(
        string="Location Verification Range (meters)",
        default=500,
        config_parameter='field_visit.proximity_threshold_meters',
        help="How close (in meters) a delegate's captured GPS position "
             "must be to a customer's registered coordinates when "
             "starting or completing a visit. Outside this range, the "
             "delegate must provide a reason before proceeding.")