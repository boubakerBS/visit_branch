# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class FieldVisitNotDone(models.TransientModel):
    _name = 'field.visit.not.done'
    _description = 'Mark Visit as Not Done'

    visit_id = fields.Many2one(
        'field.visit', required=True,
        default=lambda self: self.env.context.get('default_visit_id'))
    customer_id = fields.Many2one(related='visit_id.customer_id', readonly=True)

    reason = fields.Selection([
        ('customer_absent', 'Customer Absent'),
        ('location_closed', 'Location Closed'),
        ('emergency', 'Emergency'),
        ('other', 'Other'),
    ], required=True)
    note = fields.Text(string="Details")

    def action_confirm(self):
        self.ensure_one()
        visit = self.visit_id
        if visit.state not in ('planned', 'in_progress'):
            raise UserError(
                "Only a planned or in-progress visit can be marked as "
                "not done.")
        visit.write({
            'state': 'not_done',
            'not_done_reason': self.reason,
            'not_done_note': self.note,
        })
        return True
