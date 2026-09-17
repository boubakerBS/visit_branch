/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";

const CHARTJS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js";

/**
 * Landing dashboard for the Field Visit app. All numbers are read
 * live via the ORM (read_group / search_count) - nothing is stored or
 * precomputed, so it is always accurate as of the moment it's opened.
 */
export class FieldVisitDashboard extends Component {
    static template = "field_visit.Dashboard";
    static props = ["*"];

    /**
     * Thin wrapper around the ORM's group-by call. Odoo's JS ORM
     * service method for this is `webReadGroup` (not `readGroup`,
     * which does not exist on the client-side ORM service) and its
     * result can come back either as a plain array of groups or as
     * `{ groups: [...], length: N }` depending on version - this
     * normalizes both shapes to a plain array so the rest of the
     * dashboard code never has to care.
     */
    /**
     * Thin wrapper around the ORM's group-by call. Confirmed against
     * the actual Odoo "Read_group: A New Hope" refactor: the modern
     * signature is (model, domain, groupby, aggregates) - groupby now
     * comes BEFORE aggregates (the old convention was the reverse:
     * fields/aggregates first, then groupby). Every call site below
     * passes arguments in that order.
     */
    async readGroup(model, domain, groupby, aggregates) {
        const result = await this.orm.webReadGroup(model, domain, groupby, aggregates);
        return Array.isArray(result) ? result : (result.groups || []);
    }

    setup() {
        this.labels = {
            title: _t("Field Visit Dashboard"),
            plannedToday: _t("Planned Today"),
            inProgress: _t("In Progress"),
            doneToday: _t("Done Today"),
            notDoneToday: _t("Not Done Today"),
            weekCompletionRate: _t("This Week's Completion Rate"),
            doneOfTotal: _t("done of"),
            total: _t("total"),
            activeDelegatesNow: _t("Active Delegates Right Now"),
            salesToday: _t("Sales Today"),
            custodyPending: _t("Custody Pending Hand-over"),
            custodyLimitReached: _t("Custody Limit Reached"),
            allowed: _t("allowed"),
            visitsThisWeek: _t("Visits This Week"),
            visits: _t("Visits"),
        };
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.chartRef = useRef("weekChart");
        this.state = useState({
            loading: true,
            todayPlanned: 0,
            todayDone: 0,
            todayNotDone: 0,
            todayInProgress: 0,
            weekTotal: 0,
            weekDone: 0,
            weekCompletionPct: 0,
            activeDelegates: 0,
            salesTodayCount: 0,
            salesTodayAmount: 0,
            custodyPending: 0,
            custodyAlerts: [],
            weekLabels: [],
            weekCounts: [],
        });

        onWillStart(() => this.loadData());
        onMounted(() => this.renderChart());
    }

    async loadData() {
        const today = new Date().toISOString().slice(0, 10);
        const weekStart = new Date();
        weekStart.setDate(weekStart.getDate() - 6);
        const weekStartStr = weekStart.toISOString().slice(0, 10);

        // ---- Today's visits by state ----
        const todayGroups = await this.readGroup(
            "field.visit",
            [["visit_date", "=", today]],
            ["state"], []
        );
        const todayByState = {};
        todayGroups.forEach((g) => { todayByState[g.state] = g.__count; });
        this.state.todayPlanned = todayByState.planned || 0;
        this.state.todayInProgress =
            (todayByState.traveling || 0) + (todayByState.in_progress || 0);
        this.state.todayDone = todayByState.done || 0;
        this.state.todayNotDone = todayByState.not_done || 0;

        // ---- This week's completion rate ----
        const weekGroups = await this.readGroup(
            "field.visit",
            [["visit_date", ">=", weekStartStr], ["visit_date", "<=", today]],
            ["state"], []
        );
        let weekTotal = 0, weekDone = 0;
        weekGroups.forEach((g) => {
            weekTotal += g.__count;
            if (g.state === "done") weekDone += g.__count;
        });
        this.state.weekTotal = weekTotal;
        this.state.weekDone = weekDone;
        this.state.weekCompletionPct = weekTotal
            ? Math.round((weekDone / weekTotal) * 100) : 0;

        // ---- Visits per day this week (for the chart) ----
        const dayGroups = await this.readGroup(
            "field.visit",
            [["visit_date", ">=", weekStartStr], ["visit_date", "<=", today]],
            ["visit_date:day"], []
        );
        this.state.weekLabels = dayGroups.map((g) => g["visit_date:day"]);
        this.state.weekCounts = dayGroups.map((g) => g.__count);

        // ---- Active delegates right now ----
        this.state.activeDelegates = await this.orm.searchCount(
            "field.visit", [["state", "in", ["traveling", "in_progress"]]]
        );

        // ---- Sales today ----
        // Plain fetch + sum in JS instead of read_group: web_read_group
        // requires a non-empty groupby (it rejects "just give me one
        // total"), so for a simple total this is both simpler and
        // guaranteed to work regardless of read_group's constraints.
        const salesToday = await this.orm.searchRead(
            "field.sale.order", [["order_date", "=", today]], ["amount_total"]
        );
        this.state.salesTodayCount = salesToday.length;
        this.state.salesTodayAmount = salesToday.reduce(
            (sum, o) => sum + o.amount_total, 0);

        // ---- Custody still pending hand-over ----
        const inCustodyPayments = await this.orm.searchRead(
            "field.payment", [["state", "=", "in_custody"]], ["amount"]
        );
        this.state.custodyPending = inCustodyPayments.reduce(
            (sum, p) => sum + p.amount, 0);

        // ---- Delegates over their branch's custody threshold ----
        const inCustody = await this.readGroup(
            "field.payment",
            [["state", "=", "in_custody"]],
            ["delegate_id"], ["amount:sum"]
        );
        const alerts = [];
        for (const row of inCustody) {
            if (!row.delegate_id) continue;
            const [delegateId, delegateName] = row.delegate_id;
            const config = await this.orm.read(
                "field.delegate.config", [delegateId], ["branch_id"]
            );
            if (!config[0] || !config[0].branch_id) continue;
            const branch = await this.orm.read(
                "field.branch", [config[0].branch_id[0]], ["max_custody_amount"]
            );
            const threshold = branch[0] ? branch[0].max_custody_amount : 0;
            if (threshold && row.amount >= threshold) {
                alerts.push({ name: delegateName, amount: row.amount, threshold });
            }
        }
        this.state.custodyAlerts = alerts;

        this.state.loading = false;
    }

    renderChart() {
        loadJS(CHARTJS_URL).then(() => {
            if (!this.chartRef.el) return;
            new window.Chart(this.chartRef.el, {
                type: "bar",
                data: {
                    labels: this.state.weekLabels,
                    datasets: [{
                        label: this.labels.visits,
                        data: this.state.weekCounts,
                        backgroundColor: "#714B67",
                    }],
                },
                options: {
                    plugins: { legend: { display: false } },
                    scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
                },
            });
        });
    }

    openVisitsToday() {
        this.actionService.doAction("field_visit.action_field_visit", {
            additionalContext: { search_default_today: 1 },
        });
    }

    openSaleOrders() {
        this.actionService.doAction("field_visit.action_field_sale_order");
    }

    openCollections() {
        this.actionService.doAction("field_visit.action_field_payment");
    }
}

registry.category("actions").add("field_visit_dashboard", FieldVisitDashboard);