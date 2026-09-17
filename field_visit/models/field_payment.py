# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class FieldPayment(models.Model):
    _name = 'field.payment'
    _description = 'Field Payment Voucher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'payment_date desc, id desc'

    # Single sequence shared across the whole program (not per branch,
    # not per delegate) - explicitly requested so printed receipts are
    # never ambiguous between delegates.
    name = fields.Char(
        required=True, copy=False, default=lambda self: 'New',
        string="Receipt No.")

    visit_id = fields.Many2one(
        'field.visit', required=True, ondelete='cascade',
        help="The visit this payment was collected during. Only "
             "visits that are currently 'In Progress' can create a "
             "payment voucher.")
    customer_id = fields.Many2one(
        related='visit_id.customer_id', store=True, readonly=True)
    delegate_id = fields.Many2one(
        related='visit_id.delegate_id', store=True, readonly=True)
    branch_id = fields.Many2one(
        related='visit_id.branch_id', store=True, readonly=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)

    payment_date = fields.Date(required=True, default=fields.Date.context_today)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('check', 'Check'),
        ('transfer', 'Bank Transfer'),
    ], default='cash', required=True)

    state = fields.Selection([
        ('in_custody', "In Delegate's Custody"),
        ('handed_over', 'Handed Over to Supervisor'),
        ('sent_to_dynamics', 'Sent to Dynamics'),
    ], default='in_custody', required=True, tracking=True)

    handed_over_datetime = fields.Datetime(readonly=True)
    handed_over_by_id = fields.Many2one(
        'res.users', readonly=True, string="Received By")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'field.payment') or 'New'
        payments = super().create(vals_list)
        payments._check_custody_threshold()
        return payments

    def action_hand_over(self):
        """Supervisor confirms they physically received the cash/check
        from the delegate. Usable individually or on a multi-selection
        (bulk 'Receive All')."""
        for payment in self:
            if payment.state != 'in_custody':
                raise UserError(
                    f"{payment.name} is not in custody (already "
                    f"handed over or sent).")
        self.write({
            'state': 'handed_over',
            'handed_over_datetime': fields.Datetime.now(),
            'handed_over_by_id': self.env.user.id,
        })

    def _check_custody_threshold(self):
        """Warn the supervisor by email once a delegate's total
        uncollected custody exceeds the branch's configured maximum."""
        for payment in self:
            delegate = payment.delegate_id
            branch = payment.branch_id
            if not branch.max_custody_amount:
                continue
            total_custody = sum(self.env['field.payment'].search([
                ('delegate_id', '=', delegate.id),
                ('state', '=', 'in_custody'),
            ]).mapped('amount'))
            if total_custody >= branch.max_custody_amount:
                supervisors = branch.supervisor_ids
                if supervisors:
                    payment.message_notify(
                        partner_ids=supervisors.partner_id.ids,
                        subject=f"Custody limit reached: {delegate.user_id.name}",
                        body=(
                            f"{delegate.user_id.name} is now holding "
                            f"{total_custody} {payment.currency_id.name} "
                            f"in uncollected payments, at or above the "
                            f"branch limit of {branch.max_custody_amount}. "
                            f"Please arrange to collect it."
                        ),
                    )
