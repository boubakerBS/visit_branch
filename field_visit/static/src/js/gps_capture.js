/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Field widget meant to be put on the "latitude" field of the GPS
 * check-in wizard. On mount, it asks the browser for the user's real
 * GPS position and writes latitude/longitude/gps_ok directly onto the
 * record - the person never types coordinates manually, which is the
 * whole point (manual entry could be faked).
 */
export class FieldVisitGpsCapture extends Component {
    static template = "field_visit.GpsCapture";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ status: "capturing", lat: null, lng: null }); // capturing | ok | error
        this.errorMessage = "";
        onWillStart(() => this.captureLocation());
    }

    captureLocation() {
        if (!navigator.geolocation) {
            this.state.status = "error";
            this.errorMessage = "This browser does not support location access.";
            this._writeResult(false);
            return;
        }
        return new Promise((resolve) => {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    this.state.status = "ok";
                    this.state.lat = position.coords.latitude;
                    this.state.lng = position.coords.longitude;
                    this._writeResult(true,
                        position.coords.latitude,
                        position.coords.longitude);
                    resolve();
                },
                (error) => {
                    this.state.status = "error";
                    this.errorMessage =
                        "Location access was denied or is unavailable. "
                        + "It is required to proceed.";
                    this._writeResult(false);
                    resolve();
                },
                { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
            );
        });
    }

    _writeResult(ok, latitude, longitude) {
        this.props.record.update({
            latitude: ok ? latitude : 0,
            longitude: ok ? longitude : 0,
            gps_ok: ok,
        });
    }

    retry() {
        this.state.status = "capturing";
        this.captureLocation();
    }
}

registry.category("fields").add("field_visit_gps_capture", {
    component: FieldVisitGpsCapture,
});