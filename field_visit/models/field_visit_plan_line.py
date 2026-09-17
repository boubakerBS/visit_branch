# -*- coding: utf-8 -*-
from odoo import fields, models
from .field_visit_selection_data import WEEKDAYS


class FieldVisitPlanLine(models.Model):
    _name = 'field.visit.plan.line'
    _description = 'Field Visit Plan Line (recurring weekly template)'
    _order = 'visit_day, sequence'

    plan_id = fields.Many2one(
        'field.visit.plan', required=True, ondelete='cascade')
    customer_id = fields.Many2one(
        'res.partner', required=True, ondelete='cascade',
        domain=[('user_ids', '=', False)])
    visit_day = fields.Selection(
        WEEKDAYS, required=True,
        help="Which day of the week this customer is visited on. "
             "Dragging the card to another column in the Kanban view "
             "updates this field directly (standard Odoo behaviour).")
    sequence = fields.Integer(default=10)
    estimated_distance_km = fields.Float(
        help="Approximate distance from the previous stop of the same "
             "day (or from the branch for the first stop).")
    active = fields.Boolean(default=True)