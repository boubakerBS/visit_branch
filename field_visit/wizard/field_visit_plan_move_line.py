# -*- coding: utf-8 -*-
import datetime

from odoo import fields, models

from ..models.field_visit_selection_data import WEEKDAYS, WEEKDAY_KEYS


class FieldVisitPlanMoveLine(models.TransientModel):
    _name = 'field.visit.plan.move.line'
    _description = 'Move Customer To Another Day'

    visit_id = fields.Many2one(
        'field.visit', required=True,
        default=lambda self: self.env.context.get('active_id'))
    customer_id = fields.Many2one(related='visit_id.customer_id', readonly=True)
    current_visit_date = fields.Date(related='visit_id.visit_date', readonly=True)

    new_day = fields.Selection(WEEKDAYS, required=True)
    apply_to_remaining = fields.Boolean(
        string="Apply to all future occurrences of this customer",
        help="Off (default): only this single dated visit moves - the "
             "recurring pattern is untouched.\n"
             "On: the recurring template line is updated AND every "
             "not-yet-happened future visit generated from it is "
             "shifted to the new weekday as well.")

    def action_move(self):
        self.ensure_one()
        visit = self.visit_id
        old_key = self._day_key_of(visit.visit_date)
        new_index = WEEKDAY_KEYS.index(self.new_day)
        old_index = WEEKDAY_KEYS.index(old_key)
        day_shift = new_index - old_index

        visit.visit_date = visit.visit_date + datetime.timedelta(days=day_shift)

        if self.apply_to_remaining and visit.plan_line_id:
            line = visit.plan_line_id
            line.visit_day = self.new_day

            future_visits = self.env['field.visit'].search([
                ('plan_line_id', '=', line.id),
                ('state', '=', 'planned'),
                ('id', '!=', visit.id),
            ])
            for future_visit in future_visits:
                future_visit.visit_date = future_visit.visit_date + \
                    datetime.timedelta(days=day_shift)

        return True

    @staticmethod
    def _day_key_of(date_value):
        _PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                               1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}
        return _PY_WEEKDAY_TO_KEY[date_value.weekday()]
