# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil.relativedelta import relativedelta

import json

import requests
from odoo import models, fields, api
from urllib.parse import urljoin as url_join
import logging

_logger = logging.getLogger(__name__)


class SocialAccountFb(models.Model):
    _name = 'facebook.pragtech.social.account'
    _description = 'Socail Account'
    _rec_name = 'name'

    social_media_id = fields.Many2one('facebook.pragtech.social.media', string="Social Media", required=True,
                                      readonly=True, ondelete='cascade')
    social_media_type = fields.Selection(related='social_media_id.media_type')
    name = fields.Char('Page Name', readonly=True)
    pragtech_is_media_disconnected = fields.Boolean('Link with external Social Media is broken')

    fb_account_id = fields.Char('Facebook Page ID', readonly=True)
    fb_access_token = fields.Char('Facebook Page Access Token', readonly=True)

    @api.model
    def _scheduler_facebook_refresh_token_from_access_token(self):
        fb_accounts = self.env['facebook.pragtech.social.account'].search([])
        for account in fb_accounts:
            if account.fb_access_token:
                account._get_fb_access_token(account.fb_access_token)
            else:
                _logger.warning('Please Authenticate for Facebook account %s' % account.fb_account_id)

    def _get_fb_access_token(self, access_token):
        fb_app_id = self.env['ir.config_parameter'].sudo().get_param('pragtech_crm_facebook_leads.fb_app_id')
        fb_client_secret = self.env['ir.config_parameter'].sudo().get_param(
            'pragtech_crm_facebook_leads.fb_client_secret')
        extended_token_url = url_join(self.env['facebook.pragtech.social.media']._FB_ENDPOINT, "/oauth/access_token")

        extended_token_request = requests.get(extended_token_url, params={
            'client_id': fb_app_id,
            'client_secret': fb_client_secret,
            'grant_type': 'fb_exchange_token',
            'fb_exchange_token': access_token
        })

        self.fb_access_token = extended_token_request.json().get('access_token')
