/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS, loadCSS } from "@web/core/assets";

const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";

/**
 * Standalone map screen showing every branch and every (real, GPS-
 * enabled) customer as points. No Enterprise "Map View" needed - this
 * is plain Leaflet + OpenStreetMap tiles, loaded on demand so it never
 * slows down the rest of the app.
 *
 * Designed to be extended later with a delegate's route polyline: see
 * the commented-out example in renderMap() below - once
 * field.visit.route exposes an ordered list of (lat, lng) points for
 * a given day, drawing the path is a single L.polyline(...) call
 * using the exact same map instance.
 */
export class FieldVisitMap extends Component {
    static template = "field_visit.MapAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.mapRef = useRef("mapContainer");
        this.state = useState({ loading: true, routes: [], selectedRouteId: null });
        this.map = null;
        this.routeLayer = null; // holds the polyline + numbered stop markers
        this.delegateLayer = null; // "where is the delegate right now" markers
        this.refreshInterval = null;

        onWillStart(async () => {
            await loadCSS(LEAFLET_CSS);
            await loadJS(LEAFLET_JS);
            this.branches = await this.orm.searchRead(
                "field.branch",
                [["latitude", "!=", 0], ["longitude", "!=", 0]],
                ["name", "code", "latitude", "longitude"]
            );
            this.customers = await this.orm.searchRead(
                "res.partner",
                [
                    ["user_ids", "=", false],
                    ["field_visit_latitude", "!=", 0],
                    ["field_visit_longitude", "!=", 0],
                ],
                ["name", "field_visit_latitude", "field_visit_longitude"]
            );
            // Recent routes, most recent first - shown in the dropdown
            // as "Delegate - Date (N stops)" so a supervisor can pick
            // a specific delegate's day and see their path drawn on
            // the map. The stop count is included so it's obvious in
            // advance whether a route has multiple points (a
            // single-stop route will only show one line segment,
            // since the outbound and return trip overlap exactly).
            const routes = await this.orm.searchRead(
                "field.visit.route", [],
                ["name", "route_date", "delegate_id", "visit_ids"],
                { order: "route_date desc", limit: 100 }
            );
            routes.forEach((r) => { r.stop_count = r.visit_ids.length; });
            this.state.routes = routes;
            this.state.loading = false;
        });

        onMounted(() => {
            this.renderMap();
            this.refreshActiveDelegates();
            // Not real-time GPS streaming - just re-checks the latest
            // recorded checkpoint every 30s so the map feels live
            // without needing any background tracking infrastructure.
            this.refreshInterval = setInterval(
                () => this.refreshActiveDelegates(), 30000);
        });

        onWillUnmount(() => {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
            }
        });
    }

    renderMap() {
        if (this.state.loading || !this.mapRef.el) {
            return;
        }
        const L = window.L;

        const allPoints = [
            ...this.branches.map((b) => [b.latitude, b.longitude]),
            ...this.customers.map((c) => [c.field_visit_latitude, c.field_visit_longitude]),
        ];
        const center = allPoints.length ? allPoints[0] : [24.7136, 46.6753];

        this.map = L.map(this.mapRef.el).setView(center, 11);
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: "&copy; OpenStreetMap contributors",
            maxZoom: 19,
        }).addTo(this.map);

        const branchIcon = L.divIcon({
            className: "",
            html: '<div style="background:#714B67;width:18px;height:18px;border-radius:4px;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);"></div>',
            iconSize: [18, 18],
            iconAnchor: [9, 9],
        });
        const customerIcon = L.divIcon({
            className: "",
            html: '<div style="background:#2F6FDB;width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);"></div>',
            iconSize: [12, 12],
            iconAnchor: [6, 6],
        });

        this.overviewLayer = L.layerGroup().addTo(this.map);
        this.delegateLayer = L.layerGroup().addTo(this.map);

        for (const b of this.branches) {
            L.marker([b.latitude, b.longitude], { icon: branchIcon })
                .addTo(this.overviewLayer)
                .bindPopup(`<b>${b.name}</b><br/>Branch${b.code ? " - " + b.code : ""}`);
        }
        for (const c of this.customers) {
            L.marker([c.field_visit_latitude, c.field_visit_longitude], { icon: customerIcon })
                .addTo(this.overviewLayer)
                .bindPopup(`<b>${c.name}</b><br/>Customer`);
        }

        if (allPoints.length > 1) {
            this.map.fitBounds(allPoints, { padding: [40, 40] });
        }
    }

    async onRouteChange(ev) {
        const routeId = ev.target.value ? parseInt(ev.target.value, 10) : null;
        this.state.selectedRouteId = routeId;
        this.clearRoute();
        if (routeId) {
            // Hide the general branch/customer overview while a
            // specific route is shown - otherwise the surrounding
            // blue dots make the orange path hard to follow.
            this.map.removeLayer(this.overviewLayer);
            await this.drawRoute(routeId);
        } else {
            this.overviewLayer.addTo(this.map);
        }
    }

    clearRoute() {
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
            this.routeLayer = null;
        }
    }

    async drawRoute(routeId) {
        const L = window.L;
        const route = await this.orm.read(
            "field.visit.route", [routeId], ["branch_id"]
        );
        const branch = await this.orm.read(
            "field.branch", [route[0].branch_id[0]], ["latitude", "longitude"]
        );
        const visits = await this.orm.searchRead(
            "field.visit",
            [["route_id", "=", routeId]],
            ["customer_id", "customer_latitude", "customer_longitude", "sequence", "state"],
            { order: "sequence" }
        );

        const branchPoint = [branch[0].latitude, branch[0].longitude];
        const stopPoints = visits
            .filter((v) => v.customer_latitude && v.customer_longitude)
            .map((v) => [v.customer_latitude, v.customer_longitude]);
        const waypoints = [branchPoint, ...stopPoints, branchPoint];

        this.routeLayer = L.layerGroup().addTo(this.map);

        // Real road-following path via OSRM's free public routing
        // server (no API key needed - same "free by default" pattern
        // used for distance estimation elsewhere in this module).
        // Falls back to a straight-line path if OSRM is unreachable
        // (e.g. no internet) so the feature never breaks entirely.
        const roadPath = await this._fetchRoadPath(waypoints);
        L.polyline(roadPath || waypoints, {
            color: "#E8871E", weight: 4, opacity: 0.85,
        }).addTo(this.routeLayer);

        visits.forEach((v, i) => {
            if (!v.customer_latitude || !v.customer_longitude) return;
            const numberIcon = L.divIcon({
                className: "",
                html: `<div style="background:#E8871E;color:#fff;width:22px;height:22px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;">${i + 1}</div>`,
                iconSize: [22, 22],
                iconAnchor: [11, 11],
            });
            L.marker([v.customer_latitude, v.customer_longitude], { icon: numberIcon })
                .addTo(this.routeLayer)
                .bindPopup(`<b>${i + 1}. ${v.customer_id[1]}</b><br/>${v.state}`);
        });

        this.map.fitBounds(waypoints, { padding: [40, 40] });
    }

    /**
     * Calls OSRM's free public demo routing server to get the actual
     * road-following geometry connecting the given waypoints, in
     * order. Returns an array of [lat, lng] pairs ready for
     * L.polyline, or null on any failure (caller falls back to
     * straight lines between the same points).
     *
     * Note: the public demo server is rate-limited and meant for
     * light/occasional use - fine for a supervisor checking a route
     * now and then. A self-hosted OSRM instance or a paid provider
     * (e.g. Google Directions) can replace the URL below later
     * without changing anything else here.
     */
    async _fetchRoadPath(waypoints) {
        try {
            // OSRM expects "lng,lat" pairs, the opposite of Leaflet.
            const coords = waypoints.map(([lat, lng]) => `${lng},${lat}`).join(";");
            const url = `https://router.project-osrm.org/route/v1/driving/${coords}?overview=full&geometries=geojson`;
            const response = await fetch(url);
            const data = await response.json();
            if (data.code !== "Ok" || !data.routes || !data.routes.length) {
                return null;
            }
            // GeoJSON coordinates are [lng, lat] - flip back for Leaflet.
            return data.routes[0].geometry.coordinates.map(([lng, lat]) => [lat, lng]);
        } catch (error) {
            console.warn("OSRM routing failed, falling back to straight lines.", error);
            return null;
        }
    }

    /**
     * "Where is the delegate right now" - a simple, always-current
     * marker, exactly the same pattern as a customer's coordinates:
     * one flat read of two stored fields (current_latitude /
     * current_longitude on field.delegate.config), no dependency on
     * visit state, timing, or join queries. Those two fields are kept
     * up to date by field.visit / field.visit.route every time the
     * delegate confirms a GPS check-in (start trip, arrival,
     * complete, return to branch) - see _update_delegate_current_location.
     */
    async refreshActiveDelegates() {
        if (!this.map) return;
        const L = window.L;

        const delegates = await this.orm.searchRead(
            "field.delegate.config",
            [
                ["current_latitude", "!=", 0],
                ["current_longitude", "!=", 0],
            ],
            ["user_id", "current_latitude", "current_longitude",
             "current_status", "current_location_updated_at"]
        );

        this.delegateLayer.clearLayers();

        const icon = L.divIcon({
            className: "",
            html: `<div style="background:#1c7430;width:16px;height:16px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 4px rgba(28,116,48,.35);"></div>`,
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });
        for (const d of delegates) {
            L.marker([d.current_latitude, d.current_longitude], { icon })
                .addTo(this.delegateLayer)
                .bindPopup(
                    `<b>${d.user_id[1]}</b><br/>${d.current_status || ""}<br/>` +
                    `<span class="text-muted">as of ${d.current_location_updated_at}</span>`
                );
        }
    }
}

registry.category("actions").add("field_visit_map", FieldVisitMap);