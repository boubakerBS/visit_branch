# -*- coding: utf-8 -*-
from odoo import fields, models


class FieldPaymentReceive(models.TransientModel):
    _name = 'field.payment.receive'
    _description = 'Receive Custody From Delegate'

    payment_ids = fields.Many2many(
        'field.payment',
        default=lambda self: self.env.context.get('active_ids'))
    delegate_id = fields.Many2one(
        related='payment_ids.delegate_id', readonly=True)
    total_amount = fields.Float(compute='_compute_total_amount')

    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.payment_ids.mapped('amount'))

    def action_confirm(self):
        self.ensure_one()
        self.payment_ids.action_hand_over()
        return True
