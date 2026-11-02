# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Non-cash vouchers are no longer "in custody": existing ones move
    to "Verify Amount" (pending) or "Verified" (already confirmed)."""
    cr.execute("""
        UPDATE field_payment SET state = 'to_verify'
         WHERE state = 'in_custody' AND payment_method <> 'cash'
    """)
    cr.execute("""
        UPDATE field_payment SET state = 'verified'
         WHERE state = 'handed_over' AND payment_method <> 'cash'
    """)
