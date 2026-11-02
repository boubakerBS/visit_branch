# -*- coding: utf-8 -*-
import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                       1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}


class FieldVisitPlanExtend(models.TransientModel):
    """Extends the schedule by repeating, FOR EACH CUSTOMER, the last
    week that was generated for that customer, exactly as it is now
    (including days/order changed by the supervisor).

    Every customer continues from its OWN last generated visit, so a
    customer added later (with a shorter schedule) simply catches up.
    Nothing that already exists is modified or deleted: only missing
    visits are added."""
    _name = 'field.visit.plan.extend'
    _description = 'Extend Visit Plan Schedule'

    plan_id = fields.Many2one(
        'field.visit.plan', required=True,
        default=lambda self: self.env.context.get('active_id'))
    schedule_generated_until = fields.Date(
        related='plan_id.schedule_generated_until', readonly=True)

    available_customer_ids = fields.Many2many(
        'res.partner', compute='_compute_available_customers')
    customer_ids = fields.Many2many(
        'res.partner', 'field_visit_plan_extend_rel',
        'wizard_id', 'partner_id', string="Customers",
        help="Leave empty to extend all the plan's customers.")

    extend_mode = fields.Selection([
        ('days', 'A number of days'),
        ('week', 'One more week'),
        ('until_date', 'Until a specific date'),
        ('until_plan_end', "Until the plan's end date"),
    ], default='week', required=True,
        help="Extending the schedule is always an explicit, one-time "
             "action - there is no silent background job that keeps "
             "generating visits indefinitely.")
    extend_days = fields.Integer(default=7)
    extend_until_date = fields.Date()

    @api.depends('plan_id')
    def _compute_available_customers(self):
        for wiz in self:
            visits = self.env['field.visit'].search([
                ('plan_id', '=', wiz.plan_id.id),
                ('state', '!=', 'cancelled')])
            wiz.available_customer_ids = visits.mapped('customer_id')

    def _compute_end(self):
        self.ensure_one()
        plan = self.plan_id
        baseline = plan.schedule_generated_until or plan.date_start
        if self.extend_mode == 'days':
            end = baseline + datetime.timedelta(days=max(self.extend_days, 1))
        elif self.extend_mode == 'week':
            end = baseline + datetime.timedelta(days=7)
        elif self.extend_mode == 'until_date':
            end = self.extend_until_date
        else:  # until_plan_end
            end = plan.date_end
        if not end:
            raise UserError(_("Invalid extension range."))
        return min(end, plan.date_end)

    def action_extend(self):
        self.ensure_one()
        plan = self.plan_id
        if plan.state != 'approved':
            raise UserError(_(
                "The plan's pattern must be Approved before it can be "
                "extended. Review the trial period and use "
                "'Approve Pattern' first."))

        Visit = self.env['field.visit']
        Line = self.env['field.visit.plan.line'].with_context(active_test=False)
        Route = self.env['field.visit.route']
        end = self._compute_end()

        # ---- Each customer's own last generated week ----
        domain = [('plan_id', '=', plan.id), ('state', '!=', 'cancelled')]
        if self.customer_ids:
            domain.append(('customer_id', 'in', self.customer_ids.ids))
        rows = Visit.search_read(
            domain, ['customer_id', 'visit_date', 'sequence',
                     'distance_from_previous_km'])
        by_customer = {}
        for row in rows:
            row['visit_date'] = fields.Date.to_date(row['visit_date'])
            by_customer.setdefault(row['customer_id'][0], []).append(row)
        horizons = {cid: max(r['visit_date'] for r in lst)
                    for cid, lst in by_customer.items()}

        no_pattern = self.customer_ids.filtered(
            lambda c: c.id not in by_customer)
        todo = {cid: h for cid, h in horizons.items() if h < end}
        if not todo and not no_pattern:
            raise UserError(_(
                "Nothing to extend: every selected customer already has "
                "visits up to %s.", end))

        # ---- Visits that already exist (never duplicated) ----
        busy = set()
        if todo:
            for v in Visit.search([
                    ('delegate_id', '=', plan.delegate_id.id),
                    ('customer_id', 'in', list(todo)),
                    ('visit_date', '>', min(todo.values())),
                    ('visit_date', '<=', end)]):
                if v.plan_id == plan or v.state != 'cancelled':
                    busy.add((v.customer_id.id, v.visit_date))

        all_lines = Line.search([
            ('plan_id', '=', plan.id), ('customer_id', 'in', list(todo))])
        routes = {}
        visit_vals = []
        extended_customers = set()
        for cid, horizon in todo.items():
            window_start = horizon - datetime.timedelta(days=6)
            source = sorted(
                [r for r in by_customer[cid] if r['visit_date'] >= window_start],
                key=lambda r: (r['visit_date'], r['sequence']))

            # Template lines of THIS customer follow its last week
            # (other customers' lines are never touched).
            lines = {}
            keep = Line
            for row in source:
                day_key = _PY_WEEKDAY_TO_KEY[row['visit_date'].weekday()]
                vals = {
                    'sequence': row['sequence'],
                    'estimated_distance_km': row['distance_from_previous_km'],
                    'active': True,
                }
                line = all_lines.filtered(
                    lambda l: l.customer_id.id == cid
                    and l.visit_day == day_key)[:1]
                if line:
                    line.write(vals)
                else:
                    line = Line.create(dict(
                        vals, plan_id=plan.id, customer_id=cid,
                        visit_day=day_key))
                    all_lines |= line
                lines[day_key] = line
                keep |= line
            (all_lines.filtered(lambda l: l.customer_id.id == cid) - keep) \
                .write({'active': False})

            # New visits, day by day, after this customer's own horizon.
            current = horizon + datetime.timedelta(days=1)
            while current <= end:
                line = lines.get(_PY_WEEKDAY_TO_KEY[current.weekday()])
                if line and (cid, current) not in busy:
                    if current not in routes:
                        routes[current] = Route.search([
                            ('plan_id', '=', plan.id),
                            ('route_date', '=', current)], limit=1) \
                            or Route.create({
                                'plan_id': plan.id, 'route_date': current})
                    visit_vals.append({
                        'plan_id': plan.id,
                        'plan_line_id': line.id,
                        'route_id': routes[current].id,
                        'customer_id': cid,
                        'visit_date': current,
                        'sequence': line.sequence,
                        'distance_from_previous_km': line.estimated_distance_km,
                    })
                    busy.add((cid, current))
                    extended_customers.add(cid)
                current += datetime.timedelta(days=1)

        visits = Visit.create(visit_vals) if visit_vals else Visit
        if visits and end > (plan.schedule_generated_until or plan.date_start):
            plan.schedule_generated_until = end

        message = _(
            "%(visits)d visits created for %(customers)d customer(s), "
            "up to %(end)s.",
            visits=len(visits), customers=len(extended_customers), end=end)
        if no_pattern:
            message += " " + _(
                "No visits to repeat for: %s.",
                ', '.join(no_pattern.mapped('name')))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Schedule extended"),
                'message': message,
                'type': 'warning' if no_pattern else 'success',
                'sticky': bool(no_pattern),
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
