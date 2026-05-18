/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ProjectTaskControlPanel } from "@project/views/project_task_control_panel/project_task_control_panel";

patch(ProjectTaskControlPanel.prototype, {
    setup() {
        super.setup(...arguments);
        // Always force showSubtasks = true (top menu always visible)
        this.state.showSubtasks = true;
        localStorage.setItem(this.showSubtasksKey, "true");
    },
});
