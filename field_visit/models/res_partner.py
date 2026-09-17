# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    field_visit_latitude = fields.Float(
        string="Latitude", digits=(10, 7))
    field_visit_longitude = fields.Float(
        string="Longitude", digits=(10, 7))
