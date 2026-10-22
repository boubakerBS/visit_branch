/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Live location heartbeat for delegates.
 *
 * While a delegate is traveling to / visiting a customer (decided by
 * the server), the browser reports its GPS position every N seconds
 * so the supervisor's map can show where the delegate is right now.
 *
 * Browser limitation: this works while the Odoo page stays open on the
 * phone. Browsers pause GPS when the page is closed or the phone is
 * locked - continuous background tracking needs a native/PWA app.
 */
export const fieldVisitLocationTracker = {
    dependencies: ["orm"],

    start(env, { orm }) {
        if (!navigator.geolocation) {
            return;
        }
        let stopped = false;

        const getPosition = () =>
            new Promise((resolve) => {
                navigator.geolocation.getCurrentPosition(
                    (pos) => resolve(pos.coords),
                    () => resolve(null),
                    { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 }
                );
            });

        const cycle = async () => {
            if (stopped) {
                return;
            }
            let delay = 60000;
            try {
                const info = await orm.silent.call(
                    "field.delegate.config", "get_tracking_info", []);
                if (!info.is_delegate) {
                    stopped = true; // not a delegate: never check again
                    return;
                }
                delay = (info.interval || 30) * 1000;
                if (info.enabled && info.active) {
                    const coords = await getPosition();
                    if (coords) {
                        await orm.silent.call(
                            "field.delegate.config", "update_my_location", [],
                            {
                                latitude: coords.latitude,
                                longitude: coords.longitude,
                                accuracy: coords.accuracy,
                            });
                    }
                }
            } catch (e) {
                // Offline or server busy: just try again next cycle.
            }
            setTimeout(cycle, delay);
        };

        // Small initial delay so it never competes with the page load.
        setTimeout(cycle, 5000);
    },
};

registry.category("services").add("field_visit_location_tracker", fieldVisitLocationTracker);
