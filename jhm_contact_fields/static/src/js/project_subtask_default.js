/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ProjectTaskControlPanel } from "@project/views/project_task_control_panel/project_task_control_panel";

patch(ProjectTaskControlPanel.prototype, {
    setup() {
        super.setup(...arguments);
        // Default showSubtasks to true (show top menu always)
        if (localStorage.getItem(this.showSubtasksKey) === null) {
            this.state.showSubtasks = true;
            localStorage.setItem(this.showSubtasksKey, "true");
        }
    },
});
