# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class FieldVisitRoute(models.Model):
    _name = 'field.visit.route'
    _description = "Delegate's Daily Route"
    _order = 'route_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    plan_id = fields.Many2one('field.visit.plan', ondelete='cascade')
    delegate_id = fields.Many2one(
        related='plan_id.delegate_id', store=True, readonly=True)
    branch_id = fields.Many2one(
        related='plan_id.branch_id', store=True, readonly=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    route_date = fields.Date(required=True, index=True)
    visit_ids = fields.One2many(
        'field.visit', 'route_id', string="Visits")

    state = fields.Selection([
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
    ], default='not_started', required=True)

    datetime_departure = fields.Datetime(
        readonly=True, string="Left Branch At")
    datetime_return = fields.Datetime(
        readonly=True, string="Returned to Branch At")

    return_latitude = fields.Float(readonly=True, digits=(10, 7))
    return_longitude = fields.Float(readonly=True, digits=(10, 7))
    return_distance_from_branch_km = fields.Float(readonly=True)
    return_location_verified = fields.Boolean(readonly=True)
    return_exception_reason = fields.Text()
    total_duration_minutes = fields.Integer(
        compute='_compute_totals', store=True, string="Total Duration (min)")
    total_distance_km = fields.Float(
        compute='_compute_totals', store=True, string="Total Distance (km)")

    is_today = fields.Boolean(compute='_compute_is_today', search='_search_is_today')

    _sql_constraints = [
        ('plan_date_uniq', 'unique(plan_id, route_date)',
         "A route for this delegate on this date already exists."),
    ]

    @api.depends('delegate_id', 'route_date')
    def _compute_name(self):
        for route in self:
            delegate_name = route.delegate_id.user_id.name if route.delegate_id else '?'
            route.name = f"{delegate_name} - {route.route_date}"

    @api.depends('visit_ids.distance_from_previous_km', 'visit_ids.duration_minutes',
                 'datetime_departure', 'datetime_return')
    def _compute_totals(self):
        for route in self:
            route.total_distance_km = sum(
                route.visit_ids.mapped('distance_from_previous_km'))
            if route.datetime_departure and route.datetime_return:
                delta = route.datetime_return - route.datetime_departure
                route.total_duration_minutes = round(delta.total_seconds() / 60)
            else:
                route.total_duration_minutes = 0

    @api.depends('route_date')
    def _compute_is_today(self):
        today = fields.Date.context_today(self)
        for route in self:
            route.is_today = route.route_date == today

    def _search_is_today(self, operator, value):
        today = fields.Date.context_today(self)
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [('route_date', '=', today)]
        return [('route_date', '!=', today)]

    def action_return_to_branch(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(
                "The route must be in progress (all visits handled) "
                "before returning to the branch.")
        unfinished = self.visit_ids.filtered(
            lambda v: v.state in ('planned', 'traveling', 'in_progress'))
        if unfinished:
            raise UserError(
                "There are still visits that are not completed or "
                "marked as not done: %s" % ', '.join(unfinished.mapped('name')))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirm Location',
            'res_model': 'field.visit.gps.checkin',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_route_id': self.id,
                        'default_stage': 'return_to_branch'},
        }

    def _do_return_to_branch(self, latitude, longitude, distance_km,
                              is_within_range, exception_reason):
        self.ensure_one()
        self.write({
            'state': 'done',
            'datetime_return': fields.Datetime.now(),
            'return_latitude': latitude,
            'return_longitude': longitude,
            'return_distance_from_branch_km': distance_km,
            'return_location_verified': is_within_range,
            'return_exception_reason': exception_reason or False,
        })
        self.delegate_id.sudo().write({
            'current_latitude': latitude,
            'current_longitude': longitude,
            'current_status': f"Returned to {self.branch_id.name}",
            'current_location_updated_at': fields.Datetime.now(),
        })