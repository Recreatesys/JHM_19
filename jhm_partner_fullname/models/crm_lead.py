from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Standalone fields — always present regardless of whether a partner is linked.
    # When filled they drive contact_name; when a partner is linked they also
    # sync bidirectionally with the partner's first_name / last_name.
    partner_first_name = fields.Char('First Name')
    partner_last_name = fields.Char('Last Name')

    # ── Sync first/last → contact_name (and partner when linked) ──────────
    @api.onchange('partner_first_name', 'partner_last_name')
    def _onchange_fullname_parts(self):
        for rec in self:
            full = ' '.join(filter(None, [rec.partner_first_name, rec.partner_last_name]))
            if full:
                rec.contact_name = full
            # If a partner is linked, write back to the contact record
            if rec.partner_id:
                rec.partner_id.first_name = rec.partner_first_name
                rec.partner_id.last_name = rec.partner_last_name

    # ── When partner is selected, pre-fill first/last from the contact ─────
    @api.onchange('partner_id')
    def _onchange_partner_fullname(self):
        for rec in self:
            if rec.partner_id:
                rec.partner_first_name = rec.partner_id.first_name
                rec.partner_last_name = rec.partner_id.last_name
                full = ' '.join(filter(None, [rec.partner_first_name, rec.partner_last_name]))
                if full:
                    rec.contact_name = full

    # ── Persist on create / write ──────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _sync_contact_name(vals)
        return super().create(vals_list)

    def write(self, vals):
        _sync_contact_name(vals)
        return super().write(vals)


def _sync_contact_name(vals):
    fn = vals.get('partner_first_name')
    ln = vals.get('partner_last_name')
    if fn is not None or ln is not None:
        # We need current values from the record for write(), but for create()
        # we only have what's in vals — use empty string as fallback.
        full = ' '.join(filter(None, [fn or '', ln or '']))
        if full and 'contact_name' not in vals:
            vals['contact_name'] = full
