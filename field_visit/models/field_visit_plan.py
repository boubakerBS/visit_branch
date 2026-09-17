# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class FieldVisitPlan(models.Model):
    _name = 'field.visit.plan'
    _description = 'Field Visit Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'

    name = fields.Char(
        required=True, copy=False, default=lambda self: 'New',
        tracking=True)
    delegate_id = fields.Many2one(
        'field.delegate.config', required=True, ondelete='restrict',
        tracking=True, string="Delegate")
    branch_id = fields.Many2one(
        related='delegate_id.branch_id', store=True, readonly=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(
        required=True, tracking=True,
        help="Target end date for the overall plan. Actual visits are "
             "only materialized gradually up to 'Schedule Generated "
             "Until', not all at once for the whole period.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('trial', 'Trial'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True,
        help="Draft: not generated yet.\n"
             "Trial: an initial short period (e.g. one week) has been "
             "generated as real dated visits so the supervisor can "
             "adjust it freely.\n"
             "Approved: the supervisor confirmed the pattern from the "
             "trial period matches reality; the template lines now "
             "reflect it and further extensions are allowed.\n"
             "Cancelled: no further visits will be generated.")

    line_ids = fields.One2many(
        'field.visit.plan.line', 'plan_id', string="Weekly Template")
    line_count = fields.Integer(compute='_compute_line_count')

    visit_ids = fields.One2many('field.visit', 'plan_id', string="Visits")
    visit_count = fields.Integer(compute='_compute_visit_count')

    schedule_generated_until = fields.Date(
        readonly=True, tracking=True,
        help="Real field.visit records exist up to (and including) "
             "this date. Extending the schedule moves this date "
             "forward; nothing is generated automatically beyond it.")

    _sql_constraints = [
        ('name_uniq', 'unique(name, company_id)', "Plan reference must be unique."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'field.visit.plan') or 'New'
        return super().create(vals_list)

    def _compute_line_count(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)

    def _compute_visit_count(self):
        for plan in self:
            plan.visit_count = len(plan.visit_ids)

    # ------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------
    def action_approve(self):
        """Snapshot the current template lines as the confirmed
        pattern. Called explicitly by the supervisor after reviewing
        (and possibly editing) the trial period - never automatic."""
        for plan in self:
            if plan.state != 'trial':
                raise UserError(
                    "Only plans in 'Trial' state can be approved.")
            plan.state = 'approved'
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def action_view_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Visits',
            'res_model': 'field.visit',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }