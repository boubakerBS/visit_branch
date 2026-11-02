# -*- coding: utf-8 -*-
import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.field_visit_selection_data import WEEKDAYS

_PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                       1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}


class FieldVisitPlanAddCustomers(models.TransientModel):
    """Adds new customers to a plan that already exists, without
    touching anything that was already generated: only NEW template
    lines and NEW visits are created, existing visits (planned, done,
    in progress...) and their order are never modified."""
    _name = 'field.visit.plan.add.customers'
    _description = 'Add Customers To Visit Plan'

    plan_id = fields.Many2one(
        'field.visit.plan', required=True,
        default=lambda self: self.env.context.get('active_id'))
    delegate_id = fields.Many2one(
        related='plan_id.delegate_id', readonly=True)

    include_existing = fields.Boolean(
        string="Include customers already in the plan",
        help="Off: only customers that have no visit days in this plan "
             "yet are offered. On: all of the delegate's customers are "
             "offered, e.g. to add one more visit day to a customer.")
    available_customer_ids = fields.Many2many(
        'res.partner', compute='_compute_available_customers')
    customer_ids = fields.Many2many(
        'res.partner', 'field_visit_plan_add_customers_rel',
        'wizard_id', 'partner_id', string="Customers")

    day_sat = fields.Boolean(string="Saturday")
    day_sun = fields.Boolean(string="Sunday")
    day_mon = fields.Boolean(string="Monday")
    day_tue = fields.Boolean(string="Tuesday")
    day_wed = fields.Boolean(string="Wednesday")
    day_thu = fields.Boolean(string="Thursday")
    day_fri = fields.Boolean(string="Friday")

    date_from = fields.Date(
        required=True, string="From", default=fields.Date.context_today)
    date_to = fields.Date(
        required=True, string="To",
        default=lambda self: self._default_date_to())

    @api.model
    def _default_date_to(self):
        plan = self.env['field.visit.plan'].browse(
            self.env.context.get('active_id'))
        today = fields.Date.context_today(self)
        until = plan.schedule_generated_until if plan else False
        if until and until >= today:
            return until
        return today + datetime.timedelta(days=27)

    @api.depends('plan_id', 'include_existing')
    def _compute_available_customers(self):
        for wiz in self:
            customers = wiz.plan_id.delegate_id.customer_assignment_ids \
                .mapped('customer_id')
            if not wiz.include_existing:
                customers -= wiz.plan_id.line_ids.mapped('customer_id')
            wiz.available_customer_ids = customers

    # ------------------------------------------------------------
    def _suggest_days(self, delegate, load, count):
        """The `count` least busy working days (ties: week order)."""
        working = delegate._working_day_keys()
        ordered = sorted(working, key=lambda d: (load.get(d, 0), working.index(d)))
        return ordered[:count]

    def action_add(self):
        self.ensure_one()
        plan = self.plan_id
        delegate = plan.delegate_id
        if plan.state not in ('trial', 'approved'):
            raise UserError(_(
                "Customers can only be added to a plan in Trial or "
                "Approved state."))
        if not self.customer_ids:
            raise UserError(_("Select at least one customer."))
        assigned = delegate.customer_assignment_ids.mapped('customer_id')
        foreign = self.customer_ids - assigned
        if foreign:
            raise UserError(_(
                "These customers are not assigned to this delegate: %s",
                ', '.join(foreign.mapped('name'))))
        today = fields.Date.context_today(self)
        if self.date_from < today:
            raise UserError(_("The start date cannot be in the past."))
        date_to = min(self.date_to, plan.date_end)
        if date_to < self.date_from:
            raise UserError(_(
                "The period must start before it ends (and before the "
                "plan's end date %s).", plan.date_end))

        chosen_days = [key for key, _label in WEEKDAYS if self['day_' + key]]
        Line = self.env['field.visit.plan.line'].with_context(active_test=False)
        Visit = self.env['field.visit']
        Route = self.env['field.visit.route']
        distance_model = self.env['field.visit.distance']
        branch = delegate.branch_id

        all_lines = Line.search([('plan_id', '=', plan.id)])
        active_lines = all_lines.filtered('active')
        load = {}
        next_seq = {}
        last_point = {}
        for line in active_lines.sorted(lambda l: (l.visit_day, l.sequence)):
            load[line.visit_day] = load.get(line.visit_day, 0) + 1
            next_seq[line.visit_day] = max(
                next_seq.get(line.visit_day, 0), line.sequence)
            last_point[line.visit_day] = (
                line.customer_id.field_visit_latitude,
                line.customer_id.field_visit_longitude)

        # Visits that must not be duplicated: same customer, same day.
        # Own-plan visits of ANY state (the unique constraint cares),
        # other plans' visits of the same delegate unless cancelled.
        busy = set()
        for v in Visit.search([
                ('delegate_id', '=', delegate.id),
                ('customer_id', 'in', self.customer_ids.ids),
                ('visit_date', '>=', self.date_from),
                ('visit_date', '<=', date_to)]):
            if v.plan_id == plan or v.state != 'cancelled':
                busy.add((v.customer_id.id, v.visit_date))

        routes = {}
        route_seq = {}

        def route_for(day):
            if day not in routes:
                route = Route.search([
                    ('plan_id', '=', plan.id), ('route_date', '=', day),
                ], limit=1) or Route.create(
                    {'plan_id': plan.id, 'route_date': day})
                routes[day] = route
                route_seq[day] = max(route.visit_ids.mapped('sequence'),
                                     default=0)
            return routes[day]

        visit_vals = []
        skipped_duplicates = 0
        for customer in self.customer_ids:
            days = chosen_days or self._suggest_days(
                delegate, load, max(1, delegate.weekly_visit_frequency))
            if not days:
                raise UserError(_(
                    "This delegate has no working days configured."))
            for day_key in days:
                line = all_lines.filtered(
                    lambda l: l.customer_id == customer
                    and l.visit_day == day_key)[:1]
                if line and line.active:
                    pass  # already part of the template: keep as it is
                else:
                    origin = last_point.get(day_key) or (
                        branch.latitude, branch.longitude)
                    distance = distance_model.get_distance_km(
                        origin[0], origin[1],
                        customer.field_visit_latitude,
                        customer.field_visit_longitude)
                    next_seq[day_key] = next_seq.get(day_key, 0) + 10
                    vals = {
                        'sequence': next_seq[day_key],
                        'estimated_distance_km': distance,
                        'active': True,
                    }
                    if line:
                        line.write(vals)
                    else:
                        line = Line.create(dict(
                            vals, plan_id=plan.id,
                            customer_id=customer.id, visit_day=day_key))
                        all_lines |= line
                    last_point[day_key] = (
                        customer.field_visit_latitude,
                        customer.field_visit_longitude)
                    load[day_key] = load.get(day_key, 0) + 1

                current = self.date_from
                while current <= date_to:
                    if _PY_WEEKDAY_TO_KEY[current.weekday()] == day_key:
                        if (customer.id, current) in busy:
                            skipped_duplicates += 1
                        else:
                            route = route_for(current)
                            route_seq[current] += 10
                            visit_vals.append({
                                'plan_id': plan.id,
                                'plan_line_id': line.id,
                                'route_id': route.id,
                                'customer_id': customer.id,
                                'visit_date': current,
                                'sequence': route_seq[current],
                                'distance_from_previous_km':
                                    line.estimated_distance_km,
                            })
                            busy.add((customer.id, current))
                    current += datetime.timedelta(days=1)

        visits = Visit.create(visit_vals) if visit_vals else Visit
        if visits and date_to > (plan.schedule_generated_until
                                 or plan.date_start):
            plan.schedule_generated_until = date_to

        message = _(
            "%(visits)d visits created for %(customers)d customer(s).",
            visits=len(visits), customers=len(self.customer_ids))
        if skipped_duplicates:
            message += " " + _(
                "%d already existed and were skipped.", skipped_duplicates)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Customers added to the plan"),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _("Visits"),
                    'res_model': 'field.visit',
                    'views': [[False, 'list'], [False, 'form']],
                    'view_mode': 'list,form',
                    'target': 'current',
                    'domain': [('plan_id', '=', plan.id)],
                },
            },
        }
