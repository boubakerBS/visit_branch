# -*- coding: utf-8 -*-
from odoo import fields, models


class FieldCustomerAssignment(models.Model):
    _name = 'field.customer.assignment'
    _description = 'Field Customer Assignment'
    _rec_name = 'customer_id'

    customer_id = fields.Many2one(
        'res.partner', required=True, ondelete='cascade',
        domain=[('user_ids', '=', False)],
        help="Only real contacts are selectable - partners linked to "
             "an internal user account (delegates, supervisors...) "
             "are excluded.")
    delegate_id = fields.Many2one(
        'field.delegate.config', required=True, ondelete='cascade',
        string="Delegate")
    branch_id = fields.Many2one(
        related='delegate_id.branch_id', store=True, readonly=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    # Convenience related fields shown on the assignment Kanban card.
    delegate_user_id = fields.Many2one(
        related='delegate_id.user_id', string="Delegate User")
    weekly_visit_frequency = fields.Integer(
        related='delegate_id.weekly_visit_frequency', readonly=True)

    _sql_constraints = [
        ('customer_delegate_uniq', 'unique(customer_id, delegate_id)',
         "This customer is already assigned to this delegate."),
    ]