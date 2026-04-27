import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# API key for ManyChat authentication — stored in system parameters
# Set via Settings → Technical → System Parameters:
#   Key:   jhm.manychat_api_key
#   Value: <your secret key>
API_KEY_PARAM = 'jhm.manychat_api_key'


class ManyChatLeadController(http.Controller):

    @http.route('/api/manychat/lead', type='json', auth='none', methods=['POST'], csrf=False)
    def create_lead(self, **kwargs):
        """Create a CRM opportunity from ManyChat webhook.

        Expected JSON body:
        {
            "api_key": "<secret>",
            "name": "Contact Name",
            "phone": "+852 1234 5678"
        }

        Returns:
        {
            "status": "ok",
            "lead_id": 12345,
            "salesperson": "Cheryl"
        }
        """
        data = request.jsonrequest
        _logger.info('ManyChat API: received %s', data)

        # ── Auth ──────────────────────────────────────────────────────
        api_key = data.get('api_key', '')
        expected_key = request.env['ir.config_parameter'].sudo().get_param(API_KEY_PARAM, '')
        if not expected_key or api_key != expected_key:
            _logger.warning('ManyChat API: invalid api_key')
            return {'status': 'error', 'message': 'Invalid API key'}

        # ── Validate ──────────────────────────────────────────────────
        name = (data.get('name') or '').strip()
        phone = (data.get('phone') or '').strip()

        if not phone:
            return {'status': 'error', 'message': 'Phone is required'}
        if not name:
            name = phone  # fallback name

        # ── Find JHM HK company and HK Sales team ────────────────────
        env = request.env
        jhm_hk = env['res.company'].sudo().search(
            [('name', 'ilike', 'John Hu Migration')], limit=1)
        hk_sales = env['crm.team'].sudo().search(
            [('name', 'ilike', 'HK Sales')], limit=1)

        if not jhm_hk:
            _logger.error('ManyChat API: JHM HK company not found')
            return {'status': 'error', 'message': 'Company not found'}

        # ── Check for duplicate (same phone in same company) ──────────
        existing = env['crm.lead'].sudo().search([
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
        # type='opportunity' triggers auto-assignment from jhm_lead_distribution
        lead = env['crm.lead'].sudo().with_context(
            default_company_id=jhm_hk.id,
        ).create({
            'name': name,
            'phone': phone,
            'type': 'opportunity',
            'company_id': jhm_hk.id,
            'team_id': hk_sales.id if hk_sales else False,
            'partner_jhm_lead_source_id': _get_or_create_source(env, 'ManyChat'),
        })

        _logger.info('ManyChat API: created lead %d (%s) → salesperson %s',
                      lead.id, name, lead.user_id.name or 'unassigned')

        return {
            'status': 'ok',
            'lead_id': lead.id,
            'salesperson': lead.user_id.name or '',
        }


def _get_or_create_source(env, name):
    """Find or create a lead source by name."""
    rec = env['jhm.lead.source'].sudo().search([('name', '=ilike', name)], limit=1)
    if not rec:
        rec = env['jhm.lead.source'].sudo().create({'name': name})
    return rec.id
