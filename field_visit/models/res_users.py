# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Mirror image of field.branch.supervisor_ids - same relation
    # table, columns swapped. Editing from either side (the Branch
    # form's "Supervisors" field, or this "Field Visit Branches" field
    # on the user) updates the exact same underlying relation.
    field_visit_branch_ids = fields.Many2many(
        'field.branch', 'field_branch_supervisor_rel', 'user_id', 'branch_id',
        string="Field Visit Branches",
        help="Branches this user supervises. Determines which "
             "delegates, customer assignments, plans and visits they "
             "can see and manage.")
