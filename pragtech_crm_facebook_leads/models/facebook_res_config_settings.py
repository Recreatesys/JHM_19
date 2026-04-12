# coding: utf-8

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    facebook_own_account = fields.Boolean("Facebook Account",
                                          config_parameter='pragtech_crm_facebook_leads.facebook_own_account')
    fb_app_id = fields.Char("Facebook App ID",
                            compute='_compute_fb_app_id', inverse='_inverse_fb_app_id')
    fb_client_secret = fields.Char("Facebook App Secret",
                                   compute='_compute_fb_client_secret', inverse='_inverse_fb_client_secret')

    @api.onchange('facebook_own_account')
    def _onchange_facebook_own_account(self):
        if not self.facebook_own_account:
            self.fb_app_id = False
            self.fb_client_secret = False

    @api.depends('facebook_own_account')
    def _compute_fb_app_id(self):
        for record in self:
            
            if self.env.user.has_group('odoo_lead_forms_ad_integration_hub_crm.group_social_manager'):
                
                record.fb_app_id = self.env['ir.config_parameter'].sudo().get_param(
                    'pragtech_crm_facebook_leads.fb_app_id')
               
            else:
               
                record.fb_app_id = None

    



    def _inverse_fb_app_id(self):
        for record in self:
            if self.env.user.has_group('odoo_lead_forms_ad_integration_hub_crm.group_social_manager'):
                self.env['ir.config_parameter'].sudo().set_param('pragtech_crm_facebook_leads.fb_app_id',
                                                                 record.fb_app_id)

    @api.depends('facebook_own_account')
    def _compute_fb_client_secret(self):
        for record in self:
            if self.env.user.has_group('odoo_lead_forms_ad_integration_hub_crm.group_social_manager'):
                record.fb_client_secret = self.env['ir.config_parameter'].sudo().get_param(
                    'pragtech_crm_facebook_leads.fb_client_secret')
            else:
                record.fb_client_secret = None

    def _inverse_fb_client_secret(self):
        for record in self:
            if self.env.user.has_group('odoo_lead_forms_ad_integration_hub_crm.group_social_manager'):
                self.env['ir.config_parameter'].sudo().set_param('pragtech_crm_facebook_leads.fb_client_secret',
                                                                 record.fb_client_secret)
