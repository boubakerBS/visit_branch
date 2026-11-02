# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FieldDelegateAssignCustomers(models.TransientModel):
    """Assign many customers to a delegate in one go (instead of one
    row at a time). Never removes or changes existing assignments."""
    _name = 'field.delegate.assign.customers'
    _description = 'Add Customers To Delegate'

    delegate_id = fields.Many2one(
        'field.delegate.config', required=True, string="Delegate",
        default=lambda self: self.env.context.get('default_delegate_id')
        or self.env.context.get('active_id'))
    assigned_customer_ids = fields.Many2many(
        'res.partner', compute='_compute_assigned_customers')
    customer_ids = fields.Many2many(
        'res.partner', 'field_delegate_assign_customers_rel',
        'wizard_id', 'partner_id', string="Customers")
    skip_assigned_elsewhere = fields.Boolean(
        string="Skip customers assigned to another delegate", default=True,
        help="On (default): customers that already belong to another "
             "delegate are not added and are listed in the result. Off: "
             "they are added to this delegate as well.")

    @api.depends('delegate_id')
    def _compute_assigned_customers(self):
        Assignment = self.env['field.customer.assignment'].with_context(
            active_test=False)
        for wiz in self:
            wiz.assigned_customer_ids = Assignment.search([
                ('delegate_id', '=', wiz.delegate_id.id),
                ('active', '=', True)]).mapped('customer_id')

    def action_assign(self):
        self.ensure_one()
        delegate = self.delegate_id
        if not self.customer_ids:
            raise UserError(_("Select at least one customer."))

        Assignment = self.env['field.customer.assignment'].with_context(
            active_test=False)
        mine = {a.customer_id.id: a for a in Assignment.search([
            ('delegate_id', '=', delegate.id),
            ('customer_id', 'in', self.customer_ids.ids)])}
        elsewhere = set(Assignment.search([
            ('delegate_id', '!=', delegate.id),
            ('active', '=', True),
            ('customer_id', 'in', self.customer_ids.ids)]
        ).mapped('customer_id').ids)

        to_create, added, skipped_elsewhere = [], 0, []
        for customer in self.customer_ids:
            existing = mine.get(customer.id)
            if existing and existing.active:
                continue  # already assigned: nothing to do
            if self.skip_assigned_elsewhere and customer.id in elsewhere:
                skipped_elsewhere.append(customer.name)
                continue
            if existing:
                existing.write({'active': True})  # re-activate, no duplicate
            else:
                to_create.append({
                    'customer_id': customer.id, 'delegate_id': delegate.id})
            added += 1
        if to_create:
            Assignment.create(to_create)

        message = _("%d customer(s) added to the delegate.", added)
        if skipped_elsewhere:
            message += " " + _(
                "Skipped (already assigned to another delegate): %s.",
                ', '.join(skipped_elsewhere))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Customers added"),
                'message': message,
                'type': 'warning' if skipped_elsewhere else 'success',
                'sticky': bool(skipped_elsewhere),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
