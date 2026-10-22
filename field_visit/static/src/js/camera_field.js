/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { Component, useRef, useState } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const MAX_SIDE = 1600; // px - keeps photos light for mobile data
const JPEG_QUALITY = 0.8;

/**
 * Image field widget with a "Take Photo" button.
 *
 * On a phone/tablet the hidden <input type="file" capture="environment">
 * opens the rear camera directly; on a computer it falls back to the
 * normal file picker. The picked photo is down-scaled in the browser
 * before being stored on the record.
 */
export class FieldVisitCamera extends Component {
    static template = "field_visit.Camera";
    static props = { ...standardFieldProps };

    setup() {
        this.fileInput = useRef("fileInput");
        this.state = useState({ preview: null, busy: false, error: "" });
    }

    openCamera() {
        this.fileInput.el.click();
    }

    async onFileChange(ev) {
        const file = ev.target.files && ev.target.files[0];
        ev.target.value = ""; // allow re-taking the same photo
        if (!file) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            const dataUrl = await this._resize(file);
            this.state.preview = dataUrl;
            // The record stores only the base64 payload (no prefix).
            await this.props.record.update({
                [this.props.name]: dataUrl.split(",")[1],
            });
        } catch (e) {
            console.error(e);
            this.state.error = _t("Could not read the photo. Please try again.");
        } finally {
            this.state.busy = false;
        }
    }

    _resize(file) {
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
                const canvas = document.createElement("canvas");
                canvas.width = Math.round(img.width * scale);
                canvas.height = Math.round(img.height * scale);
                canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
                URL.revokeObjectURL(url);
                resolve(canvas.toDataURL("image/jpeg", JPEG_QUALITY));
            };
            img.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error("image load failed"));
            };
            img.src = url;
        });
    }
}

registry.category("fields").add("field_visit_camera", {
    component: FieldVisitCamera,
    supportedTypes: ["binary", "image"],
});
