# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class FieldVisitGpsCheckin(models.TransientModel):
    _name = 'field.visit.gps.checkin'
    _description = 'GPS Location Check-in'

    visit_id = fields.Many2one(
        'field.visit',
        default=lambda self: self.env.context.get('default_visit_id'))
    customer_id = fields.Many2one(related='visit_id.customer_id', readonly=True)

    route_id = fields.Many2one(
        'field.visit.route',
        default=lambda self: self.env.context.get('default_route_id'))
    branch_id = fields.Many2one(related='route_id.branch_id', readonly=True)

    stage = fields.Selection([
        ('trip_start', 'Start Trip'),
        ('arrival', 'Arrived - Start Visit'),
        ('complete', 'Complete Visit'),
        ('return_to_branch', 'Return to Branch'),
    ], required=True,
        default=lambda self: self.env.context.get('default_stage'))
    stage_label = fields.Char(compute='_compute_stage_label')

    # Filled automatically by the field_visit_gps_capture JS widget -
    # never typed manually by the person, which is the whole point.
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    gps_ok = fields.Boolean(
        default=False,
        help="False until the browser has successfully returned a "
             "real GPS position. The Confirm button stays hidden "
             "until this is True.")

    distance_km = fields.Float(
        compute='_compute_distance', string="Distance from Target")
    proximity_threshold_km = fields.Float(
        compute='_compute_distance')
    is_within_range = fields.Boolean(compute='_compute_distance')

    exception_reason = fields.Text(
        string="Why are you not at the expected location?")

    @api.depends('stage')
    def _compute_stage_label(self):
        labels = dict(self._fields['stage'].selection)
        for rec in self:
            rec.stage_label = labels.get(rec.stage, '')

    @api.depends('latitude', 'longitude', 'gps_ok', 'visit_id', 'route_id')
    def _compute_distance(self):
        distance_model = self.env['field.visit.distance']
        threshold_m = int(self.env['ir.config_parameter'].sudo().get_param(
            'field_visit.proximity_threshold_meters', 500))
        for rec in self:
            rec.proximity_threshold_km = threshold_m / 1000.0
            if not rec.gps_ok:
                rec.distance_km = 0.0
                rec.is_within_range = True
                continue

            if rec.stage == 'return_to_branch':
                target_lat = rec.route_id.branch_id.latitude
                target_lng = rec.route_id.branch_id.longitude
            else:
                target_lat = rec.visit_id.customer_id.field_visit_latitude
                target_lng = rec.visit_id.customer_id.field_visit_longitude

            rec.distance_km = distance_model.get_distance_km(
                rec.latitude, rec.longitude, target_lat, target_lng)
            rec.is_within_range = rec.distance_km <= rec.proximity_threshold_km

    def action_confirm(self):
        self.ensure_one()
        if not self.gps_ok:
            raise UserError(
                "Location access is required to proceed. Please allow "
                "GPS access in your browser.")
        if not self.is_within_range and not self.exception_reason:
            raise UserError(
                "You appear to be %.2f km away from the expected "
                "location (allowed: %.2f km). Please explain why "
                "before continuing."
                % (self.distance_km, self.proximity_threshold_km))

        if self.stage == 'trip_start':
            self.visit_id._do_start_trip(
                self.latitude, self.longitude, self.exception_reason)
        elif self.stage == 'arrival':
            self.visit_id._do_confirm_arrival(
                self.latitude, self.longitude, self.distance_km,
                self.is_within_range, self.exception_reason)
        elif self.stage == 'complete':
            self.visit_id._do_complete_visit(
                self.latitude, self.longitude, self.distance_km,
                self.is_within_range, self.exception_reason)
        elif self.stage == 'return_to_branch':
            self.route_id._do_return_to_branch(
                self.latitude, self.longitude, self.distance_km,
                self.is_within_range, self.exception_reason)
        return True