# -*- coding: utf-8 -*-
import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError
from .field_visit_selection_data import WEEKDAYS, WEEKDAY_KEYS

_PY_WEEKDAY_TO_KEY = {5: 'sat', 6: 'sun', 0: 'mon',
                       1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}

# States in which the delegate is actively "doing something" - a
# delegate can only ever have ONE visit in one of these states across
# their entire day. This is what makes "In Progress on two customers
# at once" impossible.
_ACTIVE_STATES = ('traveling', 'in_progress')


class FieldVisit(models.Model):
    _name = 'field.visit'
    _description = 'Field Visit (materialized, dated)'
    _order = 'visit_date, sequence'

    # Execution flow (each step is one explicit button press by the
    # delegate, matching the mockup exactly):
    #   planned -> traveling   ("Start Trip" - left previous location)
    #   traveling -> in_progress  ("Start Visit" - arrived & started)
    #   in_progress -> done    ("Complete Visit")
    #   planned/traveling -> not_done  (via wizard, with a reason)
    # Sale orders and payment vouchers are NOT part of this model yet -
    # they will be added as a separate module addition (Sales &
    # Collections), matching the agreed phased approach.

    name = fields.Char(compute='_compute_name', store=True)
    plan_id = fields.Many2one(
        'field.visit.plan', required=True, ondelete='cascade')
    plan_line_id = fields.Many2one(
        'field.visit.plan.line', ondelete='set null',
        help="Template line this visit was generated from. Empty for "
             "visits added manually outside the recurring pattern.")
    route_id = fields.Many2one(
        'field.visit.route', ondelete='set null', index=True,
        string="Daily Route")

    customer_id = fields.Many2one(
        'res.partner', required=True, ondelete='restrict',
        domain=[('user_ids', '=', False)])
    delegate_id = fields.Many2one(
        related='plan_id.delegate_id', store=True, readonly=True)
    branch_id = fields.Many2one(
        related='plan_id.branch_id', store=True, readonly=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    visit_date = fields.Date(required=True, index=True)
    sequence = fields.Integer(default=10)

    state = fields.Selection([
        ('planned', 'Planned'),
        ('traveling', 'Traveling'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('not_done', 'Not Done'),
        ('cancelled', 'Cancelled'),
    ], default='planned', required=True, tracking=True)

    # ---------------- Journey timestamps ----------------
    datetime_trip_start = fields.Datetime(
        readonly=True, string="Left Previous Stop At")
    datetime_arrival = fields.Datetime(
        readonly=True, string="Arrived / Visit Started At")
    datetime_end = fields.Datetime(readonly=True, string="Visit Ended At")

    duration_minutes = fields.Integer(
        compute='_compute_duration_minutes', store=True,
        string="Visit Duration (minutes)",
        help="Time spent WITH the customer (arrival to end) - does not "
             "include travel time.")
    travel_minutes = fields.Integer(
        compute='_compute_duration_minutes', store=True,
        string="Travel Time (minutes)",
        help="Time spent traveling to this stop (trip start to arrival).")
    distance_from_previous_km = fields.Float(
        readonly=True,
        help="Distance from the previous stop (or the branch, for the "
             "first stop of the day). Computed when the trip to this "
             "customer starts, using the configured distance provider.")
    customer_latitude = fields.Float(
        related='customer_id.field_visit_latitude', readonly=True)
    customer_longitude = fields.Float(
        related='customer_id.field_visit_longitude', readonly=True)

    notes = fields.Text(string="Visit Notes")

    sale_order_ids = fields.One2many('field.sale.order', 'visit_id')
    sale_order_count = fields.Integer(compute='_compute_sale_order_count')
    payment_ids = fields.One2many('field.payment', 'visit_id')
    payment_count = fields.Integer(compute='_compute_payment_count')
    payment_total = fields.Monetary(
        compute='_compute_payment_count',
        currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')

    def _compute_sale_order_count(self):
        for visit in self:
            visit.sale_order_count = len(visit.sale_order_ids)

    def _compute_payment_count(self):
        for visit in self:
            visit.payment_count = len(visit.payment_ids)
            visit.payment_total = sum(visit.payment_ids.mapped('amount'))

    def action_create_sale_order(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(
                "A sale order can only be created while the visit is "
                "in progress.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Sale Order',
            'res_model': 'field.sale.order',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_id': self.id},
        }

    def action_create_payment(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(
                "A payment voucher can only be created while the "
                "visit is in progress.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Payment Voucher',
            'res_model': 'field.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_id': self.id},
        }

    # ---------------- GPS verification (per stage) ----------------
    trip_start_latitude = fields.Float(readonly=True, digits=(10, 7))
    trip_start_longitude = fields.Float(readonly=True, digits=(10, 7))

    arrival_latitude = fields.Float(readonly=True, digits=(10, 7))
    arrival_longitude = fields.Float(readonly=True, digits=(10, 7))
    arrival_distance_from_customer_km = fields.Float(readonly=True)
    arrival_location_verified = fields.Boolean(readonly=True)

    end_latitude = fields.Float(readonly=True, digits=(10, 7))
    end_longitude = fields.Float(readonly=True, digits=(10, 7))
    end_distance_from_customer_km = fields.Float(readonly=True)
    end_location_verified = fields.Boolean(readonly=True)

    location_exception_reason = fields.Text(
        string="Location Exception Reason",
        help="Filled in when the delegate was outside the allowed "
             "proximity range at arrival and/or completion, explaining "
             "why. Reviewable by the supervisor.")

    not_done_reason = fields.Selection([
        ('customer_absent', 'Customer Absent'),
        ('location_closed', 'Location Closed'),
        ('emergency', 'Emergency'),
        ('other', 'Other'),
    ])
    not_done_note = fields.Text(string="Details")

    is_today = fields.Boolean(compute='_compute_is_today', search='_search_is_today')

    # Read/write "day of week" projection of visit_date, kept in sync
    # both ways. Its only purpose is to let a Kanban view group visits
    # by weekday and support drag-and-drop between day columns: Odoo's
    # standard Kanban drag calls write() on the grouped field, which
    # runs the inverse below and recomputes the real visit_date - no
    # custom JavaScript needed, this is plain ORM compute/inverse.
    visit_weekday = fields.Selection(
        WEEKDAYS, compute='_compute_visit_weekday',
        inverse='_inverse_visit_weekday', store=True, string="Day")

    _sql_constraints = [
        ('plan_line_date_uniq',
         'unique(plan_line_id, visit_date)',
         "A visit for this customer on this date already exists for "
         "this template line."),
    ]

    @api.depends('customer_id', 'visit_date')
    def _compute_name(self):
        for visit in self:
            if visit.customer_id and visit.visit_date:
                visit.name = f"{visit.customer_id.name} - {visit.visit_date}"
            else:
                visit.name = "New Visit"

    @api.depends('datetime_trip_start', 'datetime_arrival', 'datetime_end')
    def _compute_duration_minutes(self):
        for visit in self:
            if visit.datetime_trip_start and visit.datetime_arrival:
                delta = visit.datetime_arrival - visit.datetime_trip_start
                visit.travel_minutes = round(delta.total_seconds() / 60)
            else:
                visit.travel_minutes = 0
            if visit.datetime_arrival and visit.datetime_end:
                delta = visit.datetime_end - visit.datetime_arrival
                visit.duration_minutes = round(delta.total_seconds() / 60)
            else:
                visit.duration_minutes = 0

    @api.depends('visit_date')
    def _compute_is_today(self):
        today = fields.Date.context_today(self)
        for visit in self:
            visit.is_today = visit.visit_date == today

    def _search_is_today(self, operator, value):
        today = fields.Date.context_today(self)
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [('visit_date', '=', today)]
        return [('visit_date', '!=', today)]

    @api.depends('visit_date')
    def _compute_visit_weekday(self):
        for visit in self:
            if visit.visit_date:
                visit.visit_weekday = _PY_WEEKDAY_TO_KEY[visit.visit_date.weekday()]
            else:
                visit.visit_weekday = False

    def _inverse_visit_weekday(self):
        for visit in self:
            if not visit.visit_date or not visit.visit_weekday:
                continue
            old_index = WEEKDAY_KEYS.index(
                _PY_WEEKDAY_TO_KEY[visit.visit_date.weekday()])
            new_index = WEEKDAY_KEYS.index(visit.visit_weekday)
            visit.visit_date += datetime.timedelta(days=new_index - old_index)

    # ------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------
    def _check_actionable_today(self):
        """Execution actions only ever apply to TODAY's visit - this is
        the rule that keeps tomorrow's visits visible (so a delegate
        can prepare) but not actionable."""
        for visit in self:
            if not visit.is_today:
                raise UserError(
                    "This visit is not scheduled for today. Only "
                    "today's visits can be acted on.")

    def _check_single_active(self):
        """THE critical rule: a delegate can only ever be doing ONE
        thing (traveling to a customer, or visiting one) at any given
        moment - never two at once, regardless of which customers are
        involved. Enforced here, not just hidden by the UI."""
        for visit in self:
            other_active = self.search([
                ('id', '!=', visit.id),
                ('delegate_id', '=', visit.delegate_id.id),
                ('state', 'in', _ACTIVE_STATES),
            ], limit=1)
            if other_active:
                raise UserError(
                    "%(delegate)s is already busy with another visit "
                    "(%(other)s, status: %(status)s). Finish or cancel "
                    "it before starting a new one." % {
                        'delegate': visit.delegate_id.user_id.name,
                        'other': other_active.name,
                        'status': dict(
                            other_active._fields['state'].selection
                        )[other_active.state],
                    })

    def action_start_trip(self):
        """'Start Trip' - the delegate has left the previous stop (or
        the branch, for the first visit of the day) heading to this
        customer. Opens the GPS check-in wizard first - the actual
        state transition happens in _do_start_trip, called by the
        wizard's Confirm button once a real GPS fix is captured."""
        self.ensure_one()
        self._check_actionable_today()
        self._check_single_active()
        if self.state != 'planned':
            raise UserError("Only a planned visit can be started.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirm Location',
            'res_model': 'field.visit.gps.checkin',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_id': self.id, 'default_stage': 'trip_start'},
        }

    def action_start_visit(self):
        self.ensure_one()
        self._check_actionable_today()
        if self.state != 'traveling':
            raise UserError("Start the trip to this customer first.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirm Location',
            'res_model': 'field.visit.gps.checkin',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_id': self.id, 'default_stage': 'arrival'},
        }

    def action_complete_visit(self):
        self.ensure_one()
        self._check_actionable_today()
        if self.state != 'in_progress':
            raise UserError(
                "Only a visit that is in progress can be completed.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Confirm Location',
            'res_model': 'field.visit.gps.checkin',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_id': self.id, 'default_stage': 'complete'},
        }

    # ------------------------------------------------------------
    # Called exclusively by field.visit.gps.checkin.action_confirm()
    # once a real GPS fix has been captured (or the delegate provided
    # an exception reason for being out of range).
    # ------------------------------------------------------------
    def _do_start_trip(self, latitude, longitude, exception_reason):
        self.ensure_one()
        distance_model = self.env['field.visit.distance']
        origin = self._get_previous_point()
        distance_km = distance_model.get_distance_km(
            origin[0], origin[1],
            self.customer_id.field_visit_latitude,
            self.customer_id.field_visit_longitude,
        )
        vals = {
            'state': 'traveling',
            'datetime_trip_start': fields.Datetime.now(),
            'trip_start_latitude': latitude,
            'trip_start_longitude': longitude,
            'distance_from_previous_km': distance_km,
        }
        if exception_reason:
            vals['location_exception_reason'] = exception_reason
        self.write(vals)
        if self.route_id and self.route_id.state == 'not_started':
            self.route_id.write({
                'state': 'in_progress',
                'datetime_departure': fields.Datetime.now(),
            })
        self._update_delegate_current_location(
            latitude, longitude, f"En route to {self.customer_id.name}")

    def _do_confirm_arrival(self, latitude, longitude, distance_km,
                             is_within_range, exception_reason):
        self.ensure_one()
        vals = {
            'state': 'in_progress',
            'datetime_arrival': fields.Datetime.now(),
            'arrival_latitude': latitude,
            'arrival_longitude': longitude,
            'arrival_distance_from_customer_km': distance_km,
            'arrival_location_verified': is_within_range,
        }
        if exception_reason:
            vals['location_exception_reason'] = (
                (self.location_exception_reason or '')
                + f"\n[Arrival] {exception_reason}")
        self.write(vals)
        self._update_delegate_current_location(
            latitude, longitude, f"At {self.customer_id.name}")

    def _do_complete_visit(self, latitude, longitude, distance_km,
                            is_within_range, exception_reason):
        self.ensure_one()
        vals = {
            'state': 'done',
            'datetime_end': fields.Datetime.now(),
            'end_latitude': latitude,
            'end_longitude': longitude,
            'end_distance_from_customer_km': distance_km,
            'end_location_verified': is_within_range,
        }
        if exception_reason:
            vals['location_exception_reason'] = (
                (self.location_exception_reason or '')
                + f"\n[Completion] {exception_reason}")
        self.write(vals)
        self._update_delegate_current_location(
            latitude, longitude, f"Finished at {self.customer_id.name}")

    def _update_delegate_current_location(self, latitude, longitude, status):
        """Keep the delegate's current position simple and always up
        to date - the map reads these two fields directly, exactly
        like it reads a customer's coordinates. No dependency on visit
        state, security rule joins, or query timing."""
        self.ensure_one()
        self.delegate_id.sudo().write({
            'current_latitude': latitude,
            'current_longitude': longitude,
            'current_status': status,
            'current_location_updated_at': fields.Datetime.now(),
        })

    def action_open_not_done_wizard(self):
        self.ensure_one()
        self._check_actionable_today()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Mark Visit as Not Done',
            'res_model': 'field.visit.not.done',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_visit_id': self.id},
        }

    def _get_previous_point(self):
        """(lat, lng) of the previous stop today for this visit's
        route, or the branch's coordinates if this is the first stop
        (or no route is set)."""
        self.ensure_one()
        if self.route_id:
            previous = self.route_id.visit_ids.filtered(
                lambda v: v.sequence < self.sequence and v.state == 'done'
            ).sorted('sequence', reverse=True)[:1]
            if previous:
                return (previous.customer_id.field_visit_latitude,
                        previous.customer_id.field_visit_longitude)
        return (self.branch_id.latitude, self.branch_id.longitude)