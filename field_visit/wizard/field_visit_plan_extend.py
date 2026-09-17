# -*- coding: utf-8 -*-
import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

_PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                       1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}


class FieldVisitPlanExtend(models.TransientModel):
    _name = 'field.visit.plan.extend'
    _description = 'Extend Visit Plan Schedule'

    plan_id = fields.Many2one(
        'field.visit.plan', required=True,
        default=lambda self: self.env.context.get('active_id'))
    schedule_generated_until = fields.Date(
        related='plan_id.schedule_generated_until', readonly=True)

    extend_mode = fields.Selection([
        ('days', 'A number of days'),
        ('week', 'One more week'),
        ('until_date', 'Until a specific date'),
        ('until_plan_end', "Until the plan's end date"),
    ], default='week', required=True,
        help="Extending the schedule is always an explicit, one-time "
             "action - there is no silent background job that keeps "
             "generating visits indefinitely.")
    extend_days = fields.Integer(default=7)
    extend_until_date = fields.Date()

    def _compute_range(self):
        self.ensure_one()
        plan = self.plan_id
        start = (plan.schedule_generated_until or plan.date_start) + \
            datetime.timedelta(days=1)

        if self.extend_mode == 'days':
            end = start + datetime.timedelta(days=max(self.extend_days, 1) - 1)
        elif self.extend_mode == 'week':
            end = start + datetime.timedelta(days=6)
        elif self.extend_mode == 'until_date':
            end = self.extend_until_date
        else:  # until_plan_end
            end = plan.date_end

        if not end or end < start:
            raise UserError("Invalid extension range.")
        if end > plan.date_end:
            end = plan.date_end
        return start, end

    def action_extend(self):
        self.ensure_one()
        plan = self.plan_id
        if plan.state != 'approved':
            raise UserError(
                "The plan's pattern must be Approved before it can be "
                "extended. Review the trial period and use "
                "'Approve Pattern' first.")

        start, end = self._compute_range()

        lines_by_day = {}
        for line in plan.line_ids:
            lines_by_day.setdefault(line.visit_day, self.env['field.visit.plan.line'])
            lines_by_day[line.visit_day] |= line

        existing = self.env['field.visit'].search([
            ('plan_id', '=', plan.id),
            ('visit_date', '>=', start),
            ('visit_date', '<=', end),
        ])
        existing_keys = {(v.plan_line_id.id, v.visit_date) for v in existing}

        current = start
        while current <= end:
            day_key = _PY_WEEKDAY_TO_KEY[current.weekday()]
            day_lines = lines_by_day.get(day_key)
            if not day_lines:
                current += datetime.timedelta(days=1)
                continue

            new_lines = day_lines.filtered(
                lambda line: (line.id, current) not in existing_keys)
            if not new_lines:
                current += datetime.timedelta(days=1)
                continue

            route = self.env['field.visit.route'].search([
                ('plan_id', '=', plan.id), ('route_date', '=', current),
            ], limit=1) or self.env['field.visit.route'].create({
                'plan_id': plan.id,
                'route_date': current,
            })

            visit_vals = [{
                'plan_id': plan.id,
                'plan_line_id': line.id,
                'route_id': route.id,
                'customer_id': line.customer_id.id,
                'visit_date': current,
                'sequence': line.sequence,
                'distance_from_previous_km': line.estimated_distance_km,
            } for line in new_lines.sorted('sequence')]
            self.env['field.visit'].create(visit_vals)
            current += datetime.timedelta(days=1)

        plan.schedule_generated_until = end

        return {
            'type': 'ir.actions.act_window',
            'name': 'Visits',
            'res_model': 'field.visit',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', plan.id)],
        }