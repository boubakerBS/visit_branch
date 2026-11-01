# -*- coding: utf-8 -*-
import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.field_visit_selection_data import WEEKDAY_KEYS

_PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                       1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}


class FieldVisitPlanMoveLine(models.TransientModel):
    """Reschedule a visit. Opened (a) from the Action menu of a visit
    and (b) automatically when a supervisor moves a recurring visit to
    another day (form or drag & drop), to ask whether the change is for
    this visit only or for the rest of the period."""
    _name = 'field.visit.plan.move.line'
    _description = 'Reschedule Visit'

    visit_id = fields.Many2one(
        'field.visit', required=True,
        default=lambda self: self.env.context.get('active_id'))
    customer_id = fields.Many2one(related='visit_id.customer_id', readonly=True)
    current_visit_date = fields.Date(related='visit_id.visit_date', readonly=True)

    new_date = fields.Date(string="New Date", required=True)
    scope = fields.Selection([
        ('this', 'This visit only'),
        ('rest', 'This visit and all following ones (rest of the period)'),
    ], string="Apply To", default='this', required=True)
    following_count = fields.Integer(
        compute='_compute_following_count', string="Following Visits")

    def _following_visits(self):
        self.ensure_one()
        visit = self.visit_id
        if not visit.plan_line_id:
            return self.env['field.visit']
        return self.env['field.visit'].search([
            ('plan_line_id', '=', visit.plan_line_id.id),
            ('state', '=', 'planned'),
            ('visit_date', '>', visit.visit_date),
            ('id', '!=', visit.id),
        ])

    @api.depends('visit_id')
    def _compute_following_count(self):
        for wiz in self:
            wiz.following_count = len(wiz._following_visits())

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'new_date' in fields_list and not res.get('new_date'):
            visit = self.env['field.visit'].browse(
                res.get('visit_id') or self.env.context.get('active_id'))
            if visit:
                res['new_date'] = visit.visit_date
        return res

    def action_move(self):
        self.ensure_one()
        visit = self.visit_id.with_context(field_visit_skip_scope_prompt=True)
        if self.new_date == visit.visit_date:
            return True
        if visit.state != 'planned':
            raise UserError(_("Only a planned visit can be rescheduled."))

        old_index = WEEKDAY_KEYS.index(
            _PY_WEEKDAY_TO_KEY[visit.visit_date.weekday()])
        new_key = _PY_WEEKDAY_TO_KEY[self.new_date.weekday()]
        day_shift = WEEKDAY_KEYS.index(new_key) - old_index

        if visit.plan_line_id and self.env['field.visit'].search_count([
                ('plan_line_id', '=', visit.plan_line_id.id),
                ('visit_date', '=', self.new_date),
                ('id', '!=', visit.id)]):
            raise UserError(_(
                "This customer already has a visit from the same weekly "
                "pattern on %s.", self.new_date))

        followers = (self._following_visits()
                     if self.scope == 'rest' else self.env['field.visit'])
        visit.write({'visit_date': self.new_date})
        for follower in followers:
            follower.with_context(field_visit_skip_scope_prompt=True).write({
                'visit_date': follower.visit_date + datetime.timedelta(
                    days=day_shift)})
        if followers and visit.plan_line_id:
            visit.plan_line_id.visit_day = new_key
        return True
