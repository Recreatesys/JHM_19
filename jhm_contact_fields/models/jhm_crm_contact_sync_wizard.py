# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# Maps crm.lead field → res.partner field
_CRM_TO_PARTNER = {
    'partner_gender':                   'gender',
    'partner_client_nationality_id':    'client_nationality_id',
    'partner_jhm_line_id':              'jhm_line_id',
    'partner_b2b_engagement':           'b2b_engagement',
    'partner_background_id':            'background_id',
    'partner_immigration_country':      'immigration_country',
    'partner_communication_channel_id': 'communication_channel_id',
    'partner_visa_program_id':          'visa_program_id',
    'partner_previous_visa_program_id': 'previous_visa_program_id',
    'partner_jhm_lead_source_id':       'jhm_lead_source_id',
    'partner_source_details':           'source_details',
    'partner_commission':               'commission',
    'partner_migration_budget':         'migration_budget',
    'partner_facing_problems':          'facing_problems',
    'partner_consultation_fee_paid':    'consultation_fee_paid',
    'partner_sf_creation_date':         'sf_creation_date',
    'partner_appointment_date':         'appointment_date',
    'partner_appointment_notes':        'appointment_notes',
    'partner_last_call_date':           'last_call_date',
    'partner_sf_followup_date':         'sf_followup_date',
    'partner_chat_log':                 'chat_log',
    'partner_jhm_description':          'jhm_description',
    'partner_spouse_name':              'spouse_name',
    'partner_spouse_phone':             'spouse_phone',
    'partner_spouse_email':             'spouse_email',
}


class JhmCrmContactSyncWizard(models.TransientModel):
    _name = 'jhm.crm.contact.sync.wizard'
    _description = 'Sync Opportunity Data to Contacts'

    lead_ids = fields.Many2many(
        'crm.lead', string='Opportunities',
        default=lambda self: self._default_lead_ids(),
    )
    to_create = fields.Integer('Contacts to Create', compute='_compute_counts')
    to_update = fields.Integer('Contacts to Update', compute='_compute_counts')

    state      = fields.Selection([('confirm', 'Confirm'), ('done', 'Done')], default='confirm')
    created    = fields.Integer('Created',  readonly=True)
    updated    = fields.Integer('Updated',  readonly=True)
    skipped    = fields.Integer('Skipped',  readonly=True)
    result_log = fields.Text('Log',         readonly=True)

    def _default_lead_ids(self):
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            return self.env['crm.lead'].browse(active_ids)
        return self.env['crm.lead']

    @api.depends('lead_ids')
    def _compute_counts(self):
        for wiz in self:
            wiz.to_create = len(wiz.lead_ids.filtered(lambda r: not r.partner_id))
            wiz.to_update = len(wiz.lead_ids.filtered(lambda r: r.partner_id))

    def action_sync(self):
        self.ensure_one()
        created = updated = skipped = 0
        log_lines = []
        ctx = dict(self.env.context, jhm_no_sync=True)
        env = self.env(context=ctx)

        for rec in self.lead_ids:
            try:
                # ── Derive name ────────────────────────────────────────────
                fn = rec.partner_first_name or ''
                ln = rec.partner_last_name or ''
                full_name = ' '.join(filter(None, [fn, ln]))
                if not full_name:
                    # Fall back to contact_name or the lead name
                    full_name = rec.contact_name or rec.name or ''
                if not full_name:
                    skipped += 1
                    log_lines.append(f'Lead {rec.id}: no name — skipped')
                    continue

                # ── Build partner vals from JHM fields ────────────────────
                partner_vals = {}
                for crm_f, partner_f in _CRM_TO_PARTNER.items():
                    val = rec[crm_f]
                    if val:
                        partner_vals[partner_f] = val.id if hasattr(val, 'id') else val

                if not rec.partner_id:
                    # ── CREATE new contact ─────────────────────────────────
                    partner_vals.update({
                        'name':       full_name,
                        'first_name': fn or False,
                        'last_name':  ln or False,
                        'email':      rec.email_from or False,
                        'phone':      rec.phone or False,
                        'is_company': False,
                        'company_id': rec.company_id.id or False,
                    })
                    partner = env['res.partner'].create(partner_vals)
                    rec.with_context(jhm_no_sync=True).write({'partner_id': partner.id})
                    created += 1
                    _logger.info('JHM Contact Sync: created contact "%s" for lead %d', full_name, rec.id)

                else:
                    # ── UPDATE existing contact ────────────────────────────
                    # Sync name parts if not already set
                    if fn and not rec.partner_id.first_name:
                        partner_vals['first_name'] = fn
                    if ln and not rec.partner_id.last_name:
                        partner_vals['last_name'] = ln
                    if not rec.partner_id.email and rec.email_from:
                        partner_vals['email'] = rec.email_from
                    if not rec.partner_id.phone and rec.phone:
                        partner_vals['phone'] = rec.phone
                    if partner_vals:
                        rec.partner_id.with_context(jhm_no_sync=True).write(partner_vals)
                    updated += 1

            except Exception as e:
                skipped += 1
                msg = f'Lead {rec.id} ({rec.name}): {e}'
                log_lines.append(msg)
                _logger.warning('JHM Contact Sync error: %s', msg)

        log_text = f'Created: {created}  |  Updated: {updated}  |  Skipped: {skipped}'
        if log_lines:
            log_text += '\n\nErrors:\n' + '\n'.join(log_lines[:30])

        self.write({
            'state':      'done',
            'created':    created,
            'updated':    updated,
            'skipped':    skipped,
            'result_log': log_text,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'jhm.crm.contact.sync.wizard',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
        }
