# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FieldDelegateConfig(models.Model):
    _name = 'field.delegate.config'
    _description = 'Field Delegate Configuration'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade',
        domain=[('share', '=', False)])
    branch_id = fields.Many2one(
        'field.branch', required=True, ondelete='cascade')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    # A SINGLE weekly frequency applies to every customer assigned to
    # this delegate - the business explicitly rejected a per-customer
    # frequency (that was an earlier design mistake, corrected).
    weekly_visit_frequency = fields.Integer(
        default=1, string="Weekly Visit Frequency",
        help="How many times per week EACH customer assigned to this "
             "delegate is visited. Applies uniformly to all of the "
             "delegate's customers.")

    # Working days - defaulted from the branch, editable per delegate
    # (a delegate may need two days off instead of one, for example).
    work_sat = fields.Boolean(string="Saturday")
    work_sun = fields.Boolean(string="Sunday")
    work_mon = fields.Boolean(string="Monday")
    work_tue = fields.Boolean(string="Tuesday")
    work_wed = fields.Boolean(string="Wednesday")
    work_thu = fields.Boolean(string="Thursday")
    work_fri = fields.Boolean(string="Friday")

    customer_assignment_ids = fields.One2many(
        'field.customer.assignment', 'delegate_id', string="Customers")
    customer_count = fields.Integer(compute='_compute_customer_count')

    # ---------------- Current location ----------------
    # Simple, always-current fields - just like a customer's
    # coordinates. Updated in-place by field.visit / field.visit.route
    # every time the delegate confirms a GPS check-in (start trip,
    # arrival, complete visit, return to branch). The map only ever
    # needs to read these two numbers, exactly like it reads a
    # customer's field_visit_latitude/longitude - no dependency on
    # visit state, timing, or any live join.
    current_latitude = fields.Float(digits=(10, 7), readonly=True)
    current_longitude = fields.Float(digits=(10, 7), readonly=True)
    current_accuracy_m = fields.Float(readonly=True, string="GPS Accuracy (m)")
    current_status = fields.Char(readonly=True)
    current_location_updated_at = fields.Datetime(readonly=True)

    visits_per_day_estimate = fields.Float(
        compute='_compute_visits_per_day_estimate',
        help="(customers x weekly frequency) / working days, rounded "
             "up. Shown to the supervisor as a sanity check before "
             "generating the schedule.")

    _sql_constraints = [
        ('user_branch_uniq', 'unique(user_id, branch_id)',
         "This user already has a configuration for this branch."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'branch_id' in vals:
                branch = self.env['field.branch'].browse(vals['branch_id'])
                for day in ('sat', 'sun', 'mon', 'tue', 'wed', 'thu', 'fri'):
                    vals.setdefault(f'work_{day}', branch[f'default_{day}'])
        return super().create(vals_list)

    def _working_day_keys(self):
        """Return the ordered list of working day keys (e.g. ['sat',
        'sun', ...]) for this delegate, following the WEEKDAYS order."""
        self.ensure_one()
        from .field_visit_selection_data import WEEKDAYS
        return [key for key, _label in WEEKDAYS if self[f'work_{key}']]

    def _compute_customer_count(self):
        for config in self:
            config.customer_count = len(config.customer_assignment_ids)

    @api.depends('customer_assignment_ids', 'weekly_visit_frequency',
                 'work_sat', 'work_sun', 'work_mon', 'work_tue',
                 'work_wed', 'work_thu', 'work_fri')
    def _compute_visits_per_day_estimate(self):
        import math
        for config in self:
            working_days = len(config._working_day_keys())
            if not working_days:
                config.visits_per_day_estimate = 0
                continue
            total_slots = config.customer_count * config.weekly_visit_frequency
            config.visits_per_day_estimate = math.ceil(total_slots / working_days)

    @api.constrains('weekly_visit_frequency')
    def _check_frequency(self):
        for config in self:
            if config.weekly_visit_frequency < 1:
                raise ValidationError(
                    "Weekly visit frequency must be at least 1.")

    # ------------------------------------------------------------
    # Live location (heartbeat from the delegate's browser)
    # ------------------------------------------------------------
    @api.model
    def get_tracking_info(self):
        """Tells the web client whether (and how often) to report the
        current GPS position. Tracking is only active while the
        delegate is actually working: traveling to a customer or
        visiting one - never outside of that."""
        user = self.env.user
        if not self.sudo().search_count([('user_id', '=', user.id)]):
            return {'is_delegate': False}
        params = self.env['ir.config_parameter'].sudo()
        enabled = params.get_param('field_visit.tracking_enabled', 'True') == 'True'
        try:
            interval = max(10, int(params.get_param(
                'field_visit.tracking_interval_seconds', 30)))
        except ValueError:
            interval = 30
        active = bool(enabled and self.env['field.visit'].sudo().search_count([
            ('delegate_id.user_id', '=', user.id),
            ('visit_date', '=', fields.Date.context_today(self)),
            ('state', 'in', ('traveling', 'in_progress')),
        ]))
        return {
            'is_delegate': True,
            'enabled': enabled,
            'interval': interval,
            'active': active,
        }

    @api.model
    def update_my_location(self, latitude, longitude, accuracy=0.0):
        """Stores the calling delegate's latest GPS position. Only the
        caller's own configuration is ever touched."""
        try:
            latitude = float(latitude)
            longitude = float(longitude)
            accuracy = float(accuracy or 0.0)
        except (TypeError, ValueError):
            return False
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return False
        if not (latitude or longitude):
            return False
        configs = self.sudo().search([('user_id', '=', self.env.user.id)])
        if not configs:
            return False
        now = fields.Datetime.now()
        for config in configs:
            last = config.current_location_updated_at
            if last and (now - last).total_seconds() < 5:
                continue  # ignore floods
            config.write({
                'current_latitude': latitude,
                'current_longitude': longitude,
                'current_accuracy_m': accuracy,
                'current_location_updated_at': now,
            })
        return True
