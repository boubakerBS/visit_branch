# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FieldVisitPhoto(models.Model):
    _name = 'field.visit.photo'
    _description = 'Field Visit Photo'
    _order = 'id desc'

    visit_id = fields.Many2one(
        'field.visit', required=True, ondelete='cascade', index=True)
    image = fields.Image(
        string="Photo", required=True, max_width=1600, max_height=1600)
    image_256 = fields.Image(
        related='image', max_width=256, max_height=256, store=True)
    caption = fields.Char()
    taken_at = fields.Datetime(
        default=fields.Datetime.now, readonly=True)
    taken_by_id = fields.Many2one(
        'res.users', default=lambda self: self.env.user, readonly=True,
        string="Taken By")

    customer_id = fields.Many2one(
        related='visit_id.customer_id', store=True, readonly=True)
    delegate_id = fields.Many2one(
        related='visit_id.delegate_id', store=True, readonly=True)
    branch_id = fields.Many2one(
        related='visit_id.branch_id', store=True, readonly=True)
    company_id = fields.Many2one(
        related='visit_id.company_id', store=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        visits = self.env['field.visit'].browse(
            [v['visit_id'] for v in vals_list if v.get('visit_id')])
        for visit in visits:
            if visit.state != 'in_progress':
                raise UserError(_(
                    "Photos can only be added while the visit is in "
                    "progress."))
        return super().create(vals_list)
