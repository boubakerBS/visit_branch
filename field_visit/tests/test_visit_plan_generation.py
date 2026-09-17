# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestVisitPlanGeneration(TransactionCase):

    def setUp(self):
        super().setUp()
        self.branch = self.env['field.branch'].create({
            'name': 'Test Branch',
            'latitude': 24.7136,
            'longitude': 46.6753,
        })
        self.delegate_user = self.env['res.users'].create({
            'name': 'Test Delegate',
            'login': 'test_delegate_login',
        })
        self.delegate = self.env['field.delegate.config'].create({
            'user_id': self.delegate_user.id,
            'branch_id': self.branch.id,
            'weekly_visit_frequency': 2,
        })
        self.customers = self.env['res.partner'].create([
            {'name': f'Customer {i}'} for i in range(10)
        ])
        self.env['field.customer.assignment'].create([
            {'customer_id': c.id, 'delegate_id': self.delegate.id}
            for c in self.customers
        ])

    def test_distribution_covers_every_customer(self):
        working_days = self.delegate._working_day_keys()
        Wizard = self.env['field.visit.plan.generate']
        assignments = Wizard._distribute(
            self.customers, self.delegate.weekly_visit_frequency, working_days)
        self.assertEqual(len(assignments), 10 * 2)
        counts = {}
        for customer, _day in assignments:
            counts[customer.id] = counts.get(customer.id, 0) + 1
        for customer in self.customers:
            self.assertEqual(counts[customer.id], 2)

    def test_generate_trial_week_creates_dated_visits(self):
        wizard = self.env['field.visit.plan.generate'].create({
            'delegate_id': self.delegate.id,
            'date_start': '2026-08-15',  # a Saturday
            'trial_length': 'week',
        })
        wizard.action_generate()
        plan = self.env['field.visit.plan'].search([
            ('delegate_id', '=', self.delegate.id)])
        self.assertEqual(plan.state, 'trial')
        self.assertEqual(len(plan.line_ids), 20)
        self.assertTrue(len(plan.visit_ids) > 0)
        for visit in plan.visit_ids:
            self.assertTrue(
                visit.visit_date <= plan.schedule_generated_until)

    def test_extend_requires_approved_state(self):
        wizard = self.env['field.visit.plan.generate'].create({
            'delegate_id': self.delegate.id,
            'date_start': '2026-08-15',
            'trial_length': 'week',
        })
        wizard.action_generate()
        plan = self.env['field.visit.plan'].search([
            ('delegate_id', '=', self.delegate.id)])
        extend = self.env['field.visit.plan.extend'].create({
            'plan_id': plan.id,
            'extend_mode': 'week',
        })
        with self.assertRaises(Exception):
            extend.action_extend()

        plan.action_approve()
        self.assertEqual(plan.state, 'approved')
        extend.action_extend()
        self.assertTrue(plan.schedule_generated_until > plan.date_start)
