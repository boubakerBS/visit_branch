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