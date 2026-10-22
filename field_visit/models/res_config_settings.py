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
             "starting a visit. The delegate cannot start the visit "
             "outside this range.")

    field_visit_sms_enabled = fields.Boolean(
        string="SMS to Customer on Payment",
        config_parameter='field_visit.sms_enabled',
        help="Send an SMS to the customer as soon as a payment voucher "
             "is issued. Uses Odoo's SMS service (requires SMS credits "
             "or a configured SMS provider).")
    field_visit_sms_template = fields.Text(
        string="SMS Message",
        config_parameter='field_visit.sms_template',
        help="Optional custom text. Available placeholders: {amount}, "
             "{date}, {receipt}, {customer}, {company}. Leave empty to "
             "use the standard message in the customer's language.")

    field_visit_tracking_enabled = fields.Boolean(
        string="Live Delegate Tracking",
        default=True,
        config_parameter='field_visit.tracking_enabled',
        help="While a delegate is traveling or visiting, their phone "
             "reports its position so the supervisor can follow them "
             "on the map. Nothing is tracked outside active visits.")
    field_visit_tracking_interval_seconds = fields.Integer(
        string="Update Every (seconds)",
        default=30,
        config_parameter='field_visit.tracking_interval_seconds')
