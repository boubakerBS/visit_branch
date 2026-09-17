# -*- coding: utf-8 -*-
{
    'name': "Field Visit Management",
    'summary': "Plan, schedule and manage field sales & technical visits",
    'description': """
Field Visit Management
=======================
Manage branches, delegates, customer assignments and recurring weekly
visit routes. Designed to grow incrementally: this version covers route
planning only. Sales orders, collections and technical inspections will
be added to this same module in later iterations.

Key concepts
------------
* A Branch has GPS coordinates and default working days.
* A Delegate Config defines one uniform weekly visit frequency and
  working days for a delegate (all of a delegate's customers share the
  same frequency).
* A Visit Plan holds a recurring weekly template (Visit Plan Lines).
* Actual dated Visits are materialized from the template in small
  batches (trial week, then explicit extensions) - never silently in
  bulk for a whole year.
""",
    'version': '19.0.1.0.0',
    'category': 'Sales/Field Service',
    'author': "Meydan Field",
    'website': "https://example.com",
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'contacts',
        'web',
        'product',
    ],
    'data': [
        'security/field_visit_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'wizard/views/field_visit_plan_generate_views.xml',
        'wizard/views/field_visit_plan_extend_views.xml',
        'wizard/views/field_visit_plan_move_line_views.xml',
        'wizard/views/field_visit_not_done_views.xml',
        'wizard/views/field_visit_gps_checkin_views.xml',
        'wizard/views/field_payment_receive_views.xml',
        'report/field_payment_report.xml',
        'report/field_sale_order_report.xml',
        'views/field_delegate_config_views.xml',
        'views/field_branch_views.xml',
        'views/res_partner_views.xml',
        'views/res_users_views.xml',
        'views/field_customer_assignment_views.xml',
        'views/field_visit_plan_views.xml',
        'views/field_visit_plan_line_views.xml',
        'views/field_visit_route_views.xml',
        'views/field_sale_order_views.xml',
        'views/field_payment_views.xml',
        'views/field_visit_views.xml',
        'views/res_config_settings_views.xml',
        'views/field_customer_supervisor_views.xml',
        'views/field_visit_map_action.xml',
        'views/field_visit_dashboard_action.xml',
        'views/field_visit_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'field_visit/static/src/js/gps_capture.js',
            'field_visit/static/src/xml/gps_capture.xml',
            'field_visit/static/src/js/branch_map_action.js',
            'field_visit/static/src/xml/branch_map_action.xml',
            'field_visit/static/src/js/dashboard_action.js',
            'field_visit/static/src/xml/dashboard_action.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}