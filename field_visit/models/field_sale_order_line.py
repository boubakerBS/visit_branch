# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FieldSaleOrderLine(models.Model):
    _name = 'field.sale.order.line'
    _description = 'Field Sale Order Line'

    order_id = fields.Many2one(
        'field.sale.order', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    quantity = fields.Float(default=1.0, required=True)
    price_unit = fields.Float(required=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    subtotal = fields.Monetary(
        compute='_compute_subtotal', store=True, currency_field='currency_id')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.lst_price

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit
