# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FieldSaleOrder(models.Model):
    _name = 'field.sale.order'
    _description = 'Field Sale Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'order_date desc'

    name = fields.Char(required=True, copy=False, default=lambda self: 'New')
    visit_id = fields.Many2one(
        'field.visit', required=True, ondelete='cascade',
        help="The visit this order was created during. Only visits "
             "that are currently 'In Progress' can create an order.")
    customer_id = fields.Many2one(
        related='visit_id.customer_id', store=True, readonly=True)
    delegate_id = fields.Many2one(
        related='visit_id.delegate_id', store=True, readonly=True)
    branch_id = fields.Many2one(
        related='visit_id.branch_id', store=True, readonly=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    order_date = fields.Date(required=True, default=fields.Date.context_today)

    fulfillment_source = fields.Selection([
        ('car_stock', "From Delegate's Car Stock"),
        ('email_supervisor', "Emailed to Supervisor"),
    ], required=True,
        help="Chosen by the delegate. Either way, the order is "
             "considered complete as soon as it is submitted - no "
             "approval step.")

    line_ids = fields.One2many('field.sale.order.line', 'order_id')
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True)
    amount_total = fields.Monetary(
        compute='_compute_amount_total', store=True,
        currency_field='currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'field.sale.order') or 'New'
        orders = super().create(vals_list)
        for order in orders:
            if order.fulfillment_source == 'email_supervisor':
                order._send_supervisor_email()
        return orders

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped('subtotal'))

    def _send_supervisor_email(self):
        self.ensure_one()
        supervisors = self.branch_id.supervisor_ids
        if not supervisors:
            return
        lines_text = '\n'.join(
            f"- {line.product_id.name}: {line.quantity} x {line.price_unit}"
            for line in self.line_ids)
        body = (
            f"New field sale order {self.name} from "
            f"{self.delegate_id.user_id.name} for {self.customer_id.name}.\n\n"
            f"{lines_text}\n\nTotal: {self.amount_total}"
        )
        self.message_notify(
            partner_ids=supervisors.partner_id.ids,
            subject=f"New Sale Order: {self.name}",
            body=body,
        )
