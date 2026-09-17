# -*- coding: utf-8 -*-
"""
Shared selection list used everywhere a "day of the week" needs to be
referenced (branch default working days, delegate config, visit plan
lines, wizards...). Kept in a single place so the order and the keys
never drift apart between models.

Business rule (confirmed by the customer): the week runs Saturday to
Thursday, Friday is the default day off. This is only a *default* -
individual delegates can be configured with a different day off.
"""

WEEKDAYS = [
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
]

WEEKDAY_KEYS = [key for key, _label in WEEKDAYS]
