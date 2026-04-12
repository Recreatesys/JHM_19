# -*- coding: utf-8 -*-

import requests

from odoo import _, models, fields
from odoo.exceptions import UserError
from urllib.parse import urljoin as url_join, urlencode as url_encode


class SocialMediaFb(models.Model):
    _name = 'facebook.pragtech.social.media'
    _description = 'Facebook Social Pages'
    _rec_name = 'media_name'

    _FB_ENDPOINT = 'https://graph.facebook.com'

    media_name = fields.Char('Name', readonly=True, required=True, translate=True)
    media_description = fields.Char('Description', readonly=True)
    media_image = fields.Binary('Image', readonly=True)
    # media_type = fields.Selection([], readonly=True, )
    media_account_ids = fields.One2many('facebook.pragtech.social.account', 'social_media_id',
                                        string="Facebook Accounts")
    media_link_accounts = fields.Boolean('link Your accounts ?', default=True, readonly=True, required=True, )

    # media_type = fields.Selection(selection_add=[('facebook', 'Facebook')])
    media_type = fields.Selection([
        ('facebook', 'Facebook')
    ], string='Media Type', required=True, default='facebook')

    def pragtech_action_add_account(self):
        self.ensure_one()

        fb_app_id = self.env['ir.config_parameter'].sudo().get_param('pragtech_crm_facebook_leads.fb_app_id')
        fb_client_secret = self.env['ir.config_parameter'].sudo().get_param(
            'pragtech_crm_facebook_leads.fb_client_secret')
        if fb_app_id and fb_client_secret:
            return self._add_fb_accounts_from_configuration(fb_app_id)
        else:
            raise UserError(_(" You are Missing App ID and App Secret."))

    def _add_fb_accounts_from_configuration(self, fb_app_id):
        get_base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        split_base_url = get_base_url.split(':')[0]
        if split_base_url == 'http':
            get_base_url = get_base_url.replace("http", "https")
        else:
            pass
        get_base_facebook_url = 'https://www.facebook.com/v10.0/dialog/oauth?%s'
        get_params = {
            'client_id': fb_app_id,
            'redirect_uri': url_join(get_base_url, "/social_fb_leads/callback"),
            'response_type': 'token',
            'scope': ','.join([
                'pages_manage_ads',
                'pages_manage_metadata',
                'pages_read_engagement',
                'pages_read_user_content',
                'pages_manage_engagement',
                'pages_manage_posts',
                'read_insights',
                'pages_show_list',
                'leads_retrieval',
                'business_management'
            ])
        }
        ttttt = get_base_facebook_url % url_encode(get_params)
        # print("\n\n\ntttttttttttttttttttttttttttttttttt",ttttt)
        return {
            'type': 'ir.actions.act_url',
            'url': get_base_facebook_url % url_encode(get_params),
            'target': 'new'
        }
