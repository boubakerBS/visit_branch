# -*- coding: utf-8 -*-
from odoo import fields, models


class FieldBranch(models.Model):
    _name = 'field.branch'
    _description = 'Field Visit Branch'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(help="Short internal code, e.g. BR-RYD-E")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)

    # Address (kept minimal on purpose - no need to duplicate the full
    # res.partner address mixin for an internal branch record).
    street = fields.Char()
    city = fields.Char()
    country_id = fields.Many2one('res.country')

    # Coordinates - used as the start/end point when estimating route
    # distances. Can be entered manually or imported from an Excel file
    # by staff (import wizard is the standard Odoo list view import,
    # no custom code needed for that part).
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))

    # Defaults inherited by every field.delegate.config created under
    # this branch (each delegate can still override them individually).
    default_sat = fields.Boolean(string="Saturday", default=True)
    default_sun = fields.Boolean(string="Sunday", default=True)
    default_mon = fields.Boolean(string="Monday", default=True)
    default_tue = fields.Boolean(string="Tuesday", default=True)
    default_wed = fields.Boolean(string="Wednesday", default=True)
    default_thu = fields.Boolean(string="Thursday", default=True)
    default_fri = fields.Boolean(string="Friday", default=False)

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)
    max_custody_amount = fields.Monetary(
        currency_field='currency_id',
        help="Default maximum amount a delegate may hold in custody "
             "(collected but not yet handed over) before a warning "
             "email is sent to the supervisor. Can be overridden per "
             "delegate later when the collections module is added.")

    delegate_config_ids = fields.One2many(
        'field.delegate.config', 'branch_id', string="Delegates")
    delegate_count = fields.Integer(compute='_compute_delegate_count')

    # A branch can have one or more supervisors. This is the field
    # used by security record rules so a supervisor only ever sees
    # data (delegates, customers, plans, visits) of branches they are
    # actually assigned to - never the whole company.
    supervisor_ids = fields.Many2many(
        'res.users', 'field_branch_supervisor_rel', 'branch_id', 'user_id',
        string="Supervisors", domain=[('share', '=', False)])

    def _compute_delegate_count(self):
        for branch in self:
            branch.delegate_count = len(branch.delegate_config_ids)