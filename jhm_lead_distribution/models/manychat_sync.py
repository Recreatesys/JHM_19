import logging
import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MANYCHAT_API_URL = 'https://api.manychat.com/fb'
# Custom field IDs in ManyChat
MC_FIELD_NEW_LEAD = 12166027       # "new lead"
MC_FIELD_PHONE = 12166026          # "PHONE"
MC_FIELD_LEAD_SOURCE = 12166025    # "lead source"


class ManyChatSync(models.AbstractModel):
    _name = 'jhm.manychat.sync'
    _description = 'ManyChat → Odoo Lead Sync'

    @api.model
    def _get_api_token(self):
        return self.env['ir.config_parameter'].sudo().get_param('jhm.manychat_api_token', '')

    @api.model
    def _mc_get(self, endpoint, params=None):
        token = self._get_api_token()
        if not token:
            _logger.warning('ManyChat sync: no API token configured (jhm.manychat_api_token)')
            return None
        resp = requests.get(
            f'{MANYCHAT_API_URL}{endpoint}',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            _logger.error('ManyChat API error %d: %s', resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        if data.get('status') != 'success':
            _logger.error('ManyChat API error: %s', data.get('message'))
            return None
        return data.get('data')

    @api.model
    def _mc_post(self, endpoint, payload):
        token = self._get_api_token()
        if not token:
            return None
        resp = requests.post(
            f'{MANYCHAT_API_URL}{endpoint}',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            _logger.error('ManyChat POST error %d: %s', resp.status_code, resp.text[:200])
            return None
        return resp.json()

    @api.model
    def _mc_clear_new_lead_flag(self, subscriber_id):
        """Set 'new lead' custom field to empty so the subscriber isn't pulled again."""
        return self._mc_post('/subscriber/setCustomField', {
            'subscriber_id': subscriber_id,
            'field_id': MC_FIELD_NEW_LEAD,
            'field_value': '',
        })

    @api.model
    def _cron_sync_manychat_leads(self):
        """Pull new leads from ManyChat and create opportunities in Odoo."""
        _logger.info('ManyChat sync: starting')

        subscribers = self._mc_get('/subscriber/findByCustomField', {
            'field_id': MC_FIELD_NEW_LEAD,
            'field_value': 'yes',
        })
        if not subscribers:
            _logger.info('ManyChat sync: no new leads')
            return

        jhm_hk = self.env['res.company'].sudo().search(
            [('name', 'ilike', 'John Hu Migration Consulting Ltd')], limit=1)
        hk_sales = self.env['crm.team'].sudo().search(
            [('name', 'ilike', 'HK Sales')], limit=1)
        source_id = self._get_or_create_source('ManyChat')
        admin = self.env.ref('base.user_admin')

        CrmLead = self.env['crm.lead'].with_user(admin).with_context(
            mail_create_nosubscribe=True,
            tracking_disable=True,
            default_user_id=False,
        )

        created = 0
        skipped_dup = 0
        skipped_no_phone = 0

        for sub in subscribers:
            mc_id = sub.get('id')
            name = sub.get('name', '').strip()
            wa_phone = sub.get('whatsapp_phone', '').strip()

            # Also check PHONE custom field
            custom_fields = {f['name']: f.get('value') for f in sub.get('custom_fields', [])}
            phone_cf = (custom_fields.get('PHONE') or '').strip()

            # Use whatsapp_phone first, fallback to PHONE custom field
            phone = wa_phone or phone_cf
            if not phone:
                skipped_no_phone += 1
                self._mc_clear_new_lead_flag(mc_id)
                continue

            # Format phone with + if missing
            if not phone.startswith('+'):
                phone = '+' + phone

            if not name:
                name = phone

            # Check duplicate
            existing = self.env['crm.lead'].sudo().with_context(active_test=False).search([
                ('phone', '=', phone),
                ('company_id', '=', jhm_hk.id),
            ], limit=1)

            if existing:
                skipped_dup += 1
                self._mc_clear_new_lead_flag(mc_id)
                continue

            # Create opportunity
            lead = CrmLead.create({
                'name': name,
                'phone': phone,
                'type': 'opportunity',
                'user_id': False,
                'company_id': jhm_hk.id,
                'team_id': hk_sales.id if hk_sales else False,
                'partner_jhm_lead_source_id': source_id,
            })

            # Clear the flag in ManyChat
            self._mc_clear_new_lead_flag(mc_id)

            created += 1
            _logger.info('ManyChat sync: created lead %d (%s, %s) → %s',
                         lead.id, name, phone, lead.user_id.name or 'unassigned')

        self.env.cr.commit()
        _logger.info('ManyChat sync: done — created=%d, dup=%d, no_phone=%d',
                      created, skipped_dup, skipped_no_phone)

    @api.model
    def _get_or_create_source(self, name):
        rec = self.env['jhm.lead.source'].sudo().search([('name', '=ilike', name)], limit=1)
        if not rec:
            rec = self.env['jhm.lead.source'].sudo().create({'name': name})
        return rec.id
