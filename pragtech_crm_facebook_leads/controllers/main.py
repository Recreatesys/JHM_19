# -*- coding: utf-8 -*-
import base64
import json

import requests
import werkzeug
from urllib.parse import urljoin as url_join, urlencode as url_encode

from odoo import http, _
from odoo.http import request
from odoo.addons.auth_oauth.controllers.main import fragment_to_query_string
from odoo.exceptions import UserError
from odoo.exceptions import AccessError, MissingError, ValidationError


class SocialFbController(http.Controller):

    @fragment_to_query_string
    @http.route(['/social_fb_leads/callback'], type='http', auth='user')
    def fb_account_token_callback(self, access_token=None, is_extended_token=False, **kw_social):
        if not request.env.user.has_group('odoo_lead_forms_ad_integration_hub_crm.group_social_manager'):
            raise UserError(_("Please provide access right"))
        if access_token:
            media = request.env.ref('pragtech_crm_facebook_leads.facebook_pragtech_social_media_facebook')

            try:
                self._create_fb_accounts(access_token, media, is_extended_token)
                return "You can Close this window now"

            except (AccessError, MissingError):
                pass

    def _create_fb_accounts(self, access_token, media, is_extended_token):
        extended_access_token = access_token if is_extended_token else self._get_fb_access_token(access_token, media)
        accounts_url = url_join(request.env['facebook.pragtech.social.media']._FB_ENDPOINT, "/me/accounts/")
        json_response = requests.get(accounts_url, params={
            'access_token': extended_access_token
        }).json()

        if 'data' not in json_response:
            raise ValidationError(_('Provide a valid access token or it may access token has expired.'))

        accounts_to_create = []
        existing_accounts = self._get_fb_old_accounts(media, json_response)
        for account in json_response.get('data'):
            pragtech_account_id = account['id']
            access_token = account.get('access_token')
            if existing_accounts.get(pragtech_account_id):
                existing_accounts.get(pragtech_account_id).write({
                    'fb_access_token': access_token,
                    'pragtech_is_media_disconnected': False
                })
            else:
                accounts_to_create.append({
                    'name': account.get('name'),
                    'social_media_id': media.id,
                    'fb_account_id': pragtech_account_id,
                    'fb_access_token': access_token,
                })

        if accounts_to_create:
            request.env['facebook.pragtech.social.account'].create(accounts_to_create)

    def _get_fb_access_token(self, access_token, media):
        fb_app_id = request.env['ir.config_parameter'].sudo().get_param('pragtech_crm_facebook_leads.fb_app_id')
        fb_client_secret = request.env['ir.config_parameter'].sudo().get_param(
            'pragtech_crm_facebook_leads.fb_client_secret')
        extended_token_url = url_join(request.env['facebook.pragtech.social.media']._FB_ENDPOINT, "/oauth/access_token")
        extended_token_request = requests.post(extended_token_url, params={
            'client_id': fb_app_id,
            'client_secret': fb_client_secret,
            'grant_type': 'fb_exchange_token',
            'fb_exchange_token': access_token
        })
        return extended_token_request.json().get('access_token')

    def _get_fb_old_accounts(self, media_id, json_response):
        facebook_accounts_ids = [account['id'] for account in json_response.get('data', [])]
        if facebook_accounts_ids:
            existing_accounts = request.env['facebook.pragtech.social.account'].search([
                ('social_media_id', '=', int(media_id)),
                ('fb_account_id', 'in', facebook_accounts_ids)
            ])
            return {
                existing_account.fb_account_id: existing_account
                for existing_account in existing_accounts
            }
        return {}
