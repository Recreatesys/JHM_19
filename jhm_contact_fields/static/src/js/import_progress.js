/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class JhmImportProgress extends Component {
    static template = "jhm_contact_fields.ImportProgress";
    static props = ["action", "actionId?", "*"];

    setup() {
        this.orm           = useService("orm");
        this.actionService = useService("action");

        const p = this.props.action.params || {};
        this.state = useState({
            wizardId:     p.wizard_id,
            // per-file progress
            totalBatches: p.total_batches || 1,
            totalRows:    p.total_rows    || 0,
            currentBatch: 0,
            // counts
            imported:     0,
            skipped:      0,
            grandImported: 0,
            grandSkipped:  0,
            // file tracking
            totalFiles:   p.total_files  || 1,
            fileIndex:    p.file_index   || 0,
            fileName:     p.file_name    || "",
            status:       "running",   // running | done | error
            log:          "",
            error:        "",
        });

        this._running = true;

        onMounted(()     => this._processLoop());
        onWillUnmount(() => { this._running = false; });
    }

    async _processLoop() {
        while (this._running) {
            let result;
            try {
                result = await this.orm.call(
                    "jhm.crm.import.wizard",
                    "action_process_next_batch",
                    [[this.state.wizardId]]
                );
            } catch (e) {
                this.state.status = "error";
                this.state.error  = e.message || String(e);
                this._running     = false;
                break;
            }

            if (!this._running) break;

            // Update per-file progress
            this.state.currentBatch  = result.current_batch;
            this.state.totalBatches  = result.total_batches;
            this.state.imported      = result.imported;
            this.state.skipped       = result.skipped;
            this.state.grandImported = result.grand_imported ?? this.state.grandImported;
            this.state.grandSkipped  = result.grand_skipped  ?? this.state.grandSkipped;

            // Update file info (may change when advancing to next file)
            if (result.file_index !== undefined) {
                this.state.fileIndex = result.file_index;
            }
            if (result.total_files !== undefined) {
                this.state.totalFiles = result.total_files;
            }
            if (result.file_name !== undefined) {
                this.state.fileName = result.file_name;
            }

            if (result.state === "done") {
                this.state.status = "done";
                this.state.log    = result.log || "";
                this._running     = false;
                break;
            }

            // Brief pause so the browser can repaint the progress bar
            await new Promise(r => setTimeout(r, 150));
        }
    }

    get progressPercent() {
        const { currentBatch, totalBatches } = this.state;
        if (!totalBatches) return 0;
        return Math.min(100, Math.round((currentBatch / totalBatches) * 100));
    }

    get progressLabel() {
        const { currentBatch, totalBatches } = this.state;
        return `Batch ${currentBatch} / ${totalBatches}`;
    }

    get fileLabel() {
        const { fileIndex, totalFiles, fileName } = this.state;
        const idx = `File ${fileIndex + 1} / ${totalFiles}`;
        return fileName ? `${idx}: ${fileName}` : idx;
    }

    onClose() {
        this._running = false;
        this.actionService.doAction({ type: "ir.actions.act_window_close" });
    }
}

registry.category("actions").add("jhm_import_progress", JhmImportProgress);
