import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

API_KEY_PARAM = 'jhm.manychat_api_key'


class ManyChatLeadController(http.Controller):

    @http.route('/api/manychat/lead', type='json', auth='none', methods=['POST'], csrf=False)
    def create_lead(self, api_key='', name='', phone='', **kwargs):
        """Create a CRM opportunity from ManyChat webhook.

        JSON-RPC body params:
            api_key (str): secret key
            name (str): contact name
            phone (str): phone number

        Returns dict with status, lead_id, salesperson.
        """
        _logger.info('ManyChat API: name=%s phone=%s', name, phone)

        # ── Auth ──────────────────────────────────────────────────────
        expected_key = request.env['ir.config_parameter'].sudo().get_param(API_KEY_PARAM, '')
        if not expected_key or api_key != expected_key:
            _logger.warning('ManyChat API: invalid api_key')
            return {'status': 'error', 'message': 'Invalid API key'}

        # ── Validate ──────────────────────────────────────────────────
        phone = (phone or '').strip()
        name = (name or '').strip()

        if not phone:
            return {'status': 'error', 'message': 'Phone is required'}
        if not name:
            name = phone

        # ── Find JHM HK company and HK Sales team ────────────────────
        env = request.env
        jhm_hk = env['res.company'].sudo().search(
            [('name', 'ilike', 'John Hu Migration Consulting Ltd')], limit=1)
        hk_sales = env['crm.team'].sudo().search(
            [('name', 'ilike', 'HK Sales')], limit=1)

        if not jhm_hk:
            return {'status': 'error', 'message': 'Company not found'}

        # ── Check duplicate ───────────────────────────────────────────
        existing = env['crm.lead'].sudo().with_context(active_test=False).search([
            ('phone', '=', phone),
            ('company_id', '=', jhm_hk.id),
        ], limit=1)

        if existing:
            _logger.info('ManyChat API: duplicate phone %s → lead %d', phone, existing.id)
            return {
                'status': 'duplicate',
                'lead_id': existing.id,
                'salesperson': existing.user_id.name or '',
                'message': 'Lead with this phone already exists',
            }

        # ── Create opportunity ────────────────────────────────────────
        source_id = _get_or_create_source(env, 'ManyChat')
        lead = env['crm.lead'].sudo().create({
            'name': name,
            'phone': phone,
            'type': 'opportunity',
            'company_id': jhm_hk.id,
            'team_id': hk_sales.id if hk_sales else False,
            'partner_jhm_lead_source_id': source_id,
        })

        _logger.info('ManyChat API: created lead %d (%s) → salesperson %s',
                      lead.id, name, lead.user_id.name or 'unassigned')

        return {
            'status': 'ok',
            'lead_id': lead.id,
            'salesperson': lead.user_id.name or '',
        }


def _get_or_create_source(env, name):
    rec = env['jhm.lead.source'].sudo().search([('name', '=ilike', name)], limit=1)
    if not rec:
        rec = env['jhm.lead.source'].sudo().create({'name': name})
    return rec.id
