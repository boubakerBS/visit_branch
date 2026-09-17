# -*- coding: utf-8 -*-
import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.field_visit_selection_data import WEEKDAY_KEYS

# Python's date.weekday(): Monday=0 ... Sunday=6.
# Map that to our own keys, which start the week on Saturday.
_PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                       1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}


class FieldVisitPlanGenerate(models.TransientModel):
    _name = 'field.visit.plan.generate'
    _description = 'Generate Trial Visit Plan'

    delegate_id = fields.Many2one(
        'field.delegate.config', required=True, string="Delegate")
    branch_id = fields.Many2one(
        related='delegate_id.branch_id', readonly=True)
    customer_count = fields.Integer(
        related='delegate_id.customer_count', readonly=True)
    weekly_visit_frequency = fields.Integer(
        related='delegate_id.weekly_visit_frequency', readonly=True)
    visits_per_day_estimate = fields.Float(
        related='delegate_id.visits_per_day_estimate', readonly=True)

    date_start = fields.Date(
        required=True, default=fields.Date.context_today,
        help="First day of the trial period.")
    trial_length = fields.Selection([
        ('week', 'One week (7 days)'),
        ('two_weeks', 'Two weeks (14 days)'),
    ], default='week', required=True,
        help="Only this short trial period is generated as real, dated "
             "visits. Nothing beyond it is created automatically - the "
             "supervisor reviews and adjusts this period, approves the "
             "pattern, then explicitly extends the schedule further "
             "(see the 'Extend Schedule' action on the plan).")

    # ------------------------------------------------------------
    # Which day each customer lands on: simple round-robin, spread
    # evenly so every customer gets exactly `frequency` visits/week.
    # This is about balancing WORKLOAD across days, not distance -
    # the geographic optimisation happens afterwards, WITHIN each day
    # (see _order_customers_by_distance below).
    # ------------------------------------------------------------
    @staticmethod
    def _distribute_to_days(customers, frequency, working_day_keys):
        n_days = len(working_day_keys)
        if not n_days or not frequency:
            return []
        step = max(1, n_days // frequency)
        assignments = []
        for idx, customer in enumerate(customers):
            for k in range(frequency):
                day_index = (idx + k * step) % n_days
                assignments.append((customer, working_day_keys[day_index]))
        return assignments

    def _order_customers_by_distance(self, customers, start_lat, start_lng):
        """Greedy Nearest-Neighbor: starting from (start_lat, start_lng)
        - normally the branch - repeatedly pick whichever remaining
        customer is closest to the CURRENT point (not the branch), then
        move to it and repeat. This is exactly what was asked for:
        stop 2's distance is measured from stop 1's actual location,
        not from the branch.

        The full distance matrix (branch + every customer) is fetched
        ONCE up front via get_distance_matrix_km - this matters when
        the OSRM/Google providers are configured, since each pairwise
        lookup would otherwise be a separate HTTP call (slow for
        larger customer lists). Haversine stays effectively free
        either way since it never leaves the server.
        """
        distance_model = self.env['field.visit.distance']
        points = [(start_lat, start_lng)] + [
            (c.field_visit_latitude, c.field_visit_longitude) for c in customers
        ]
        matrix = distance_model.get_distance_matrix_km(points)

        # index 0 = start point (branch); customers are 1..N in the
        # same order as `customers`, matching `points` above.
        remaining = list(range(1, len(points)))
        ordered = []
        cur_idx = 0
        while remaining:
            best_idx, best_dist = None, None
            for idx in remaining:
                dist = matrix[cur_idx][idx]
                if best_dist is None or dist < best_dist:
                    best_idx, best_dist = idx, dist
            ordered.append((customers[best_idx - 1], best_dist))
            remaining.remove(best_idx)
            cur_idx = best_idx
        return ordered

    def action_generate(self):
        self.ensure_one()
        delegate = self.delegate_id
        customers = delegate.customer_assignment_ids.mapped('customer_id')
        working_day_keys = delegate._working_day_keys()

        if not customers:
            raise UserError(
                "This delegate has no assigned customers yet. Assign "
                "customers before generating a plan.")
        if not working_day_keys:
            raise UserError(
                "This delegate has no working days configured.")
        missing_coords = customers.filtered(
            lambda c: not c.field_visit_latitude or not c.field_visit_longitude)
        if missing_coords:
            raise UserError(
                "These customers have no GPS coordinates yet, so a "
                "route cannot be ordered by distance: %s"
                % ', '.join(missing_coords.mapped('name')))

        trial_days = 14 if self.trial_length == 'two_weeks' else 7

        plan = self.env['field.visit.plan'].create({
            'delegate_id': delegate.id,
            'date_start': self.date_start,
            'date_end': self.date_start + datetime.timedelta(days=364),
            'state': 'trial',
        })

        # 1) Which day each customer belongs to (workload balancing).
        assignments = self._distribute_to_days(
            customers, delegate.weekly_visit_frequency, working_day_keys)
        customers_by_day = {}
        for customer, day_key in assignments:
            customers_by_day.setdefault(day_key, self.env['res.partner'])
            customers_by_day[day_key] |= customer

        # 2) WITHIN each day, order customers by nearest-neighbor from
        #    the branch, and store that order + estimated distance on
        #    the template line.
        branch = delegate.branch_id
        line_vals = []
        for day_key, day_customers in customers_by_day.items():
            ordered = self._order_customers_by_distance(
                day_customers, branch.latitude, branch.longitude)
            for seq, (customer, dist_km) in enumerate(ordered, start=1):
                line_vals.append({
                    'plan_id': plan.id,
                    'customer_id': customer.id,
                    'visit_day': day_key,
                    'sequence': seq * 10,
                    'estimated_distance_km': dist_km,
                })
        self.env['field.visit.plan.line'].create(line_vals)

        # 3) Materialize real, dated visits + one Route header per day.
        lines_by_day = {}
        for line in plan.line_ids:
            lines_by_day.setdefault(line.visit_day, self.env['field.visit.plan.line'])
            lines_by_day[line.visit_day] |= line

        for offset in range(trial_days):
            visit_date = self.date_start + datetime.timedelta(days=offset)
            day_key = _PY_WEEKDAY_TO_KEY[visit_date.weekday()]
            day_lines = lines_by_day.get(day_key)
            if not day_lines:
                continue

            route = self.env['field.visit.route'].create({
                'plan_id': plan.id,
                'route_date': visit_date,
            })
            visit_vals = [{
                'plan_id': plan.id,
                'plan_line_id': line.id,
                'route_id': route.id,
                'customer_id': line.customer_id.id,
                'visit_date': visit_date,
                'sequence': line.sequence,
                'distance_from_previous_km': line.estimated_distance_km,
            } for line in day_lines.sorted('sequence')]
            self.env['field.visit'].create(visit_vals)

        plan.schedule_generated_until = self.date_start + datetime.timedelta(
            days=trial_days - 1)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Visit Plan',
            'res_model': 'field.visit.plan',
            'view_mode': 'form',
            'res_id': plan.id,
        }