/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { BaseImportModel } from "@base_import/import_model";

/**
 * Change the default batch import limit from 2000 → 1500.
 * We intercept the first call to importOptions (before any user interaction)
 * and apply the new default exactly once per instance.
 * The user can still override it manually via the "Batch limit" UI field.
 */
patch(BaseImportModel.prototype, {
    get importOptions() {
        if (!this._jhmLimitPatched) {
            this._jhmLimitPatched = true;
            if (this.importOptionsValues?.limit) {
                this.importOptionsValues.limit.value = 1500;
            }
        }
        return super.importOptions;
    },
});
