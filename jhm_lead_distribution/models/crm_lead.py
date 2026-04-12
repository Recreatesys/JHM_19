from odoo import api, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_eligible_salespeople(self):
        """Return internal users in the current company who are not skipped."""
        return self.env['res.users'].search([
            ('share', '=', False),
            ('skip_auto_assignment', '=', False),
            ('company_ids', 'in', self.env.company.id),
        ])

    def _find_existing_assignment(self, phone, email):
        """If a previous lead/opportunity with the same phone or email already
        has a salesperson assigned, return that user (sticky assignment)."""
        if not phone and not email:
            return self.env['res.users']

        domain = [('user_id', '!=', False), ('id', '!=', self.id if self else 0)]
        matches = self.env['crm.lead']
        if phone:
            matches |= self.search(domain + [('phone', '=', phone)])
        if email:
            matches |= self.search(domain + [('email_from', '=', email)])

        if matches:
            # Return the salesperson from the most recently written match
            latest = matches.sorted('write_date', reverse=True)[0]
            return latest.user_id
        return self.env['res.users']

    def _auto_assign_salesperson(self):
        """Assign a salesperson via round-robin, respecting sticky phone/email."""
        Tracker = self.env['jhm.assignment.tracker'].sudo()
        for rec in self:
            # Only assign if currently unassigned
            if rec.user_id:
                continue

            phone = rec.phone or (rec.partner_id.phone if rec.partner_id else '')
            email = rec.email_from or (rec.partner_id.email if rec.partner_id else '')

            # Sticky: reuse salesperson from prior lead with same phone/email
            existing_user = rec._find_existing_assignment(phone, email)
            if existing_user and not existing_user.skip_auto_assignment:
                rec.user_id = existing_user
                continue

            # Round-robin
            eligible = rec._get_eligible_salespeople()
            if not eligible:
                continue
            tracker = Tracker._get_for_company(rec.company_id.id or self.env.company.id)
            next_user = tracker.get_next_user(eligible)
            if next_user:
                rec.user_id = next_user

    # ── Trigger on conversion from lead → opportunity ─────────────────────

    def write(self, vals):
        # Capture which records are being converted to opportunity
        converting = self.env['crm.lead']
        if vals.get('type') == 'opportunity':
            converting = self.filtered(lambda r: r.type == 'lead')

        result = super().write(vals)

        if converting:
            converting._auto_assign_salesperson()

        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self.env.context.get('jhm_import'):
            return records
        # Auto-assign any records created directly as opportunities without a salesperson
        to_assign = records.filtered(lambda r: r.type == 'opportunity' and not r.user_id)
        if to_assign:
            to_assign._auto_assign_salesperson()
        return records
