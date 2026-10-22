# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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
        ('mada', 'Mada Card Device'),
    ], default='cash', required=True)
    notes = fields.Text(string="Notes")

    state = fields.Selection([
        ('in_custody', "In Delegate's Custody"),
        ('handed_over', 'Handed Over to Supervisor'),
        ('sent_to_dynamics', 'Sent to Dynamics'),
    ], default='in_custody', required=True, tracking=True)

    # ---------------- SMS to the customer ----------------
    sms_state = fields.Selection([
        ('not_sent', 'Not Sent'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('no_phone', 'No Phone Number'),
    ], default='not_sent', readonly=True, copy=False,
        string="Customer SMS")
    sms_error = fields.Char(readonly=True, copy=False)
    sms_datetime = fields.Datetime(readonly=True, copy=False)

    handed_over_datetime = fields.Datetime(readonly=True)
    handed_over_by_id = fields.Many2one(
        'res.users', readonly=True, string="Received By")

    @api.constrains('amount')
    def _check_amount_positive(self):
        for payment in self:
            if payment.amount <= 0:
                raise ValidationError(_(
                    "The receipt amount must be greater than zero. A "
                    "payment voucher cannot be issued for a zero (or "
                    "negative) amount."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'field.payment') or 'New'
        payments = super().create(vals_list)
        payments._check_custody_threshold()
        # Confirmation SMS to the customer. Must never block or break
        # the collection itself, whatever happens with the gateway.
        payments._send_receipt_sms()
        return payments

    # ------------------------------------------------------------
    # SMS confirmation to the customer
    # ------------------------------------------------------------
    def _sms_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'field_visit.sms_enabled') == 'True'

    def _get_customer_phone(self):
        self.ensure_one()
        partner = self.customer_id
        mobile = partner._fields.get('mobile') and partner.mobile
        return mobile or partner.phone or False

    def _get_sms_body(self):
        self.ensure_one()
        partner = self.customer_id.with_context(lang=self.customer_id.lang)
        payment = self.with_context(lang=partner.lang)
        template = self.env['ir.config_parameter'].sudo().get_param(
            'field_visit.sms_template')
        values = {
            'amount': f"{payment.amount:,.2f} {payment.currency_id.name or ''}".strip(),
            'receipt': payment.name,
            'date': fields.Date.to_string(payment.payment_date),
            'customer': partner.name or '',
            'company': payment.company_id.name or '',
        }
        if template:
            try:
                return template.format(**values)
            except (KeyError, IndexError, ValueError):
                pass  # malformed custom template: fall back to default
        # env._ translates into the CUSTOMER's language (payment env).
        return payment.env._(
            "Dear customer, we received %(amount)s on %(date)s "
            "(receipt no. %(receipt)s) - %(company)s. Thank you.",
            **values)

    def _send_receipt_sms(self):
        """Sends the 'amount received' SMS. Records the outcome on the
        voucher; never raises."""
        if not self._sms_enabled():
            return
        for payment in self:
            number = payment._get_customer_phone()
            if not number:
                payment.sudo().write({'sms_state': 'no_phone'})
                continue
            try:
                with self.env.cr.savepoint():
                    sms = self.env['sms.sms'].sudo().create({
                        'number': number,
                        'body': payment._get_sms_body(),
                        'partner_id': payment.customer_id.id,
                    })
                    sms.send(unlink_failed=False, unlink_sent=False,
                             raise_exception=False)
                    failed = sms.state == 'error'
                    error = sms.failure_type if failed else False
                payment.sudo().write({
                    'sms_state': 'failed' if failed else 'sent',
                    'sms_error': error or False,
                    'sms_datetime': fields.Datetime.now(),
                })
            except Exception as exc:  # noqa: BLE001 - gateway must not break collection
                payment.sudo().write({
                    'sms_state': 'failed',
                    'sms_error': str(exc)[:200],
                })

    def action_resend_sms(self):
        for payment in self:
            if not payment._sms_enabled():
                raise UserError(_(
                    "Customer SMS is turned off. Enable it in Settings "
                    "> Field Visit > SMS Notifications."))
        self._send_receipt_sms()
        return True

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
