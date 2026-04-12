# -*- coding: utf-8 -*-

import logging
import requests

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CrmFacebookPage(models.Model):
    _name = 'crm.facebook.page'
    _description = 'Facebook Page'
    _rec_name = 'fb_account'
    #
    # name = fields.Char(required=True)
    # access_token = fields.Char(required=True, string='Page Access Token')

    fb_account = fields.Many2one(
        'facebook.pragtech.social.account', string='Page Name')
    access_token = fields.Char(string="Page Access Token", related='fb_account.fb_access_token', store=True,
                               readonly=False, tracking=True)
    name = fields.Char(string="Page ID", related='fb_account.fb_account_id', required=True)

    form_ids = fields.One2many('crm.facebook.form', 'page_id', string='Lead Forms')

    def lead_form_processing(self, p):
        if not p.get('data'):
            return

        for form in p['data']:
            if self.form_ids.filtered(
                    lambda f: f.fb_form_id == form['id']):
                continue
            self.env['crm.facebook.form'].create({
                'name': form['name'],
                'fb_form_id': form['id'],
                'page_id': self.id}).fetch_fb_form_fields()

        if p.get('paging') and p['paging'].get('next'):
            self.lead_form_processing(requests.get(p['paging']['next']).json())
        return

    def fetch_facebook_forms(self):
        r = requests.get("https://graph.facebook.com/v10.0/" + self.name + "/leadgen_forms",
                         params={'access_token': self.access_token}).json()
        self.lead_form_processing(r)


class CrmFbForm(models.Model):
    _name = 'crm.facebook.form'
    _description = 'Facebook Form Page'

    name = fields.Char(required=True)
    allow_to_sync = fields.Boolean()
    fb_form_id = fields.Char(required=True, string='Form ID')
    access_token = fields.Char(required=True, related='page_id.access_token', string='Page Access Token')
    page_id = fields.Many2one('crm.facebook.page', readonly=True, ondelete='cascade', string='Facebook Page')
    mappings = fields.One2many('crm.facebook.form.field', 'form_id')
    team_id = fields.Many2one('crm.team', domain=['|', ('use_leads', '=', True), ('use_opportunities', '=', True)],
                              string="Sales Team")
    campaign_id = fields.Many2one('utm.campaign')
    source_id = fields.Many2one('utm.source')
    medium_id = fields.Many2one('utm.medium')
    state = fields.Selection([
        ('draft', 'Draft'), ('confirm', 'Confirm')
    ], string='State', required=True, default='draft')
    fb_lead_create_as_opportunity = fields.Boolean(
        string="Create as Opportunity",
        help="If enabled, all leads fetched from this form will be created as opportunities directly."
    )

    def fetch_fb_form_fields(self):
        self.mappings.unlink()
        r = requests.get("https://graph.facebook.com/v10.0/" + self.fb_form_id,
                         params={'access_token': self.access_token, 'fields': 'questions'}).json()
        if r.get('questions'):
            for questions in r.get('questions'):

                self.env['crm.facebook.form.field'].create({
                    'form_id': self.id,
                    'name': questions['label'],
                    'fb_field': questions['key']
                })

    def validate_fb_form(self):
        if self.state and self.state == 'draft':
            self.state = 'confirm'
            self.allow_to_sync = True


class CrmFbFormField(models.Model):
    _name = 'crm.facebook.form.field'
    _description = 'Facebook form fields'

    form_id = fields.Many2one('crm.facebook.form', required=True, ondelete='cascade', string='Form')
    name = fields.Text()
    For_map_odoo_field = fields.Many2one('ir.model.fields', domain=[('model', '=', 'crm.lead'), ('store', '=', True),
                                                                    ('ttype', 'in', ('char', 'date', 'datetime', 'float', 'html',
                                                                                     'integer',
                                                                                     'monetary',
                                                                                     'many2one',
                                                                                     'selection',
                                                                                     'phone',
                                                                                     'text'))],
                                         required=False)
    fb_field = fields.Text(required=True)

    _sql_constraints = [
        ('field_unique', 'unique(form_id, For_map_odoo_field, fb_field)', 'Mapping must be unique per form')
    ]


class FbUtmMedium(models.Model):
    _inherit = 'utm.medium'

    fb_ad_id = fields.Char()

    _sql_constraints = [
        ('facebook_ad_unique', 'unique(fb_ad_id)',
         'This Facebook Ad already exists!')
    ]


class FbUtmAdset(models.Model):
    _name = 'fb.utm.adset'
    _description = ' Fb Utm Adset'

    name = fields.Char()
    fb_adset_id = fields.Char()

    _sql_constraints = [
        ('facebook_adset_unique', 'unique(fb_adset_id)',
         'This Facebook AdSet already exists!')
    ]


class FbUtmCampaign(models.Model):
    _inherit = 'utm.campaign'

    fb_campaign_id = fields.Char()

    _sql_constraints = [
        ('facebook_campaign_unique', 'unique(fb_campaign_id)',
         'This Facebook Campaign already exists!')
    ]


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    description = fields.Html('Notes')
    fb_lead_id = fields.Char(readonly=True)
    fb_page_id = fields.Many2one(
        'crm.facebook.page', related='fb_form_id.page_id',
        store=True, readonly=True)
    fb_form_id = fields.Many2one('crm.facebook.form', readonly=True)
    fb_adset_id = fields.Many2one('fb.utm.adset', readonly=True)
    fb_ad_id = fields.Many2one(
        'utm.medium', related='medium_id', store=True, readonly=True,
        string='Facebook Ad')
    fb_campaign_id = fields.Many2one(
        'utm.campaign', related='campaign_id', store=True, readonly=True,
        string='Facebook Campaign')
    fb_date_create = fields.Datetime(readonly=True)
    fb_is_organic = fields.Boolean(readonly=True)

    _sql_constraints = [
        ('facebook_lead_unique', 'unique(fb_lead_id)',
         'This Facebook lead already exists!')
    ]

    def fetch_ad(self, lead):
        ad_obj = self.env['utm.medium']
        if not lead.get('ad_id'):
            return ad_obj
        if not ad_obj.search(
                [('fb_ad_id', '=', lead['ad_id'])]):
            return ad_obj.create({
                'fb_ad_id': lead['ad_id'], 'name': lead['ad_name'], }).id

        return ad_obj.search(
            [('fb_ad_id', '=', lead['ad_id'])], limit=1)[0].id

    def fetch_adset(self, lead):
        ad_obj = self.env['fb.utm.adset']
        if not lead.get('adset_id'):
            return ad_obj
        if not ad_obj.search(
                [('fb_adset_id', '=', lead['adset_id'])]):
            return ad_obj.create({
                'fb_adset_id': lead['adset_id'], 'name': lead['adset_name'], }).id

        return ad_obj.search(
            [('fb_adset_id', '=', lead['adset_id'])], limit=1)[0].id

    def fetch_campaign(self, lead):
        campaign_instance = self.env['utm.campaign']
        if not lead.get('campaign_id'):
            return campaign_instance
        if not campaign_instance.search(
                [('fb_campaign_id', '=', lead['campaign_id'])]):
            return campaign_instance.create({
                'fb_campaign_id': lead['campaign_id'],
                'name': lead['campaign_name'], }).id

        return campaign_instance.search(
            [('fb_campaign_id', '=', lead['campaign_id'])],
            limit=1)[0].id

    def generate_lead_creation(self, lead, form):
        vals, notes = self.fetch_fields_from_data(lead, form)
        source_id = self.env.ref('utm.utm_source_facebook')
        medium_id = self.env.ref('utm.utm_medium_facebook')

        vals.update({
            'fb_lead_id': lead['id'],
            'fb_is_organic': lead['is_organic'],
            'name': self.fetch_opportunity_name(vals, lead, form),
            'description': "\n".join(notes),
            'team_id': form.team_id and form.team_id.id,
            'campaign_id': form.campaign_id and form.campaign_id.id or self.fetch_campaign(lead),
            'source_id': source_id.id,
            'medium_id': medium_id.id,
            'user_id': form.team_id and form.team_id.user_id and form.team_id.user_id.id or False,
            'fb_adset_id': self.fetch_adset(lead),
            'fb_form_id': form.id,
            'fb_date_create': lead['created_time'].split('+')[0].replace('T', ' '),
            # 'type':'opportunity',
        })
         
        fb_lead_create_as_opportunity = form.fb_lead_create_as_opportunity or self.env['ir.config_parameter'].sudo().get_param('crm.fb_lead_create_as_opportunity', default=False)
        # Set the type based on the create_as_opportunity flag
        vals['type'] = 'opportunity' if fb_lead_create_as_opportunity else 'lead'

        return vals
        
    def lead_generation(self, lead, form):
        vals = self.generate_lead_creation(lead, form)
        return self.create(vals)

    def fetch_opportunity_name(self, vals, lead, form):
        if not vals.get('name'):
            vals['name'] = '%s - %s' % (form.name, lead['id'])
        return vals['name']

    def fetch_fields_from_data(self, lead, form):
        # print("\n\n\n=======fetch_fields_from_data==============", self, lead, form)
        vals, notes = {}, []
        form_mapping = form.mappings.filtered(lambda m: m.For_map_odoo_field).mapped('fb_field')
        # print("form_mapping=================",form.mappings.filtered(lambda m: m.fb_field))

        unmapped_fb_fields = []
        for name, value in lead.items():
            if name not in form_mapping:
                unmapped_fb_fields.append((name, value))
                # print("unmapped_fb_fields===============",name)
                continue
            For_map_odoo_field = form.mappings.filtered(lambda m: m.fb_field == name).For_map_odoo_field

            # print("For_map_odoo_field=============ggggggggggggggggggggggggggggggggggggggggggg", For_map_odoo_field.field_description)
            # if For_map_odoo_field.ttype == 'many2one':
            #     if For_map_odoo_field.relation in ['res.country.state', 'res.country']:
            #             record = self.env[For_map_odoo_field.relation].search(['|', ('name', '=', value), ('code', '=', value)], limit=1)
            #             if record:
            #                 vals[For_map_odoo_field.name] = record.id
            #             else :
            #                 False
            #     else:
            #         related_value = self.env[For_map_odoo_field.relation].search([('name', '=', value)])
            #         vals.update({For_map_odoo_field.name: related_value and related_value.id})
            if For_map_odoo_field.ttype == 'many2one':
                if For_map_odoo_field.relation in ['res.country.state', 'res.country']:
                    record = self.env[For_map_odoo_field.relation].search(['|', ('name', '=', value), ('code', '=', value)], limit=1)
                    if record:
                        vals[For_map_odoo_field.name] = record.id
                    else:
                        new_record = self.env[For_map_odoo_field.relation].create({'name': value})
                        vals[For_map_odoo_field.name] = new_record.id
                else:
                    related_value = self.env[For_map_odoo_field.relation].search([('name', '=', value)], limit=1)
                    if related_value:
                        vals[For_map_odoo_field.name] = related_value.id
                    else:
                        new_record = self.env[For_map_odoo_field.relation].create({'name': value})
                        vals[For_map_odoo_field.name] = new_record.id
            elif For_map_odoo_field.ttype in ('float', 'monetary'):
                vals.update({For_map_odoo_field.name: float(value)})
            elif For_map_odoo_field.ttype == 'integer':
                vals.update({For_map_odoo_field.name: int(value)})
            elif For_map_odoo_field.ttype in ('date', 'datetime'):
                vals.update({For_map_odoo_field.name: value.split('+')[0].replace('T', ' ')})
            # elif For_map_odoo_field.ttype == 'selection':
            #     vals.update({For_map_odoo_field.name: value})
            elif For_map_odoo_field.ttype == 'selection':
                current_value = getattr(lead, For_map_odoo_field.name, None)
                if current_value != value:
                    vals.update({For_map_odoo_field.name: value})
            elif For_map_odoo_field.ttype == 'boolean':
                vals.update({For_map_odoo_field.name: value == 'true' if value else False})
            else:
                vals.update({For_map_odoo_field.name: value})

        for name, value in unmapped_fb_fields:

            if name not in ['created_time', 'is_organic', 'id']:
                # print("name==============", name)
                notes.append('<b>%s</b>: %s <br><br>' % (str(name.capitalize().replace("_", " ")), value))

        return vals, notes


    def execute_lead_field_data(self, lead):
        field_data = lead.pop('field_data')
        lead_data = dict(lead)
        lead_data.update([(l['name'], l['values'][0])
                          for l in field_data
                          if l.get('name') and l.get('values')])
        return lead_data

    def lead_execution(self, r, form):
        if not r.get('data'):
            return
        for lead in r['data']:
            lead = self.execute_lead_field_data(lead)
            if not self.search(
                    [('fb_lead_id', '=', lead.get('id')), '|', ('active', '=', True), ('active', '=', False)]):
                self.lead_generation(lead, form)
        try:
            self.env.cr.commit()
        except Exception:
            self.env.cr.rollback()

        if r.get('paging') and r['paging'].get('next'):
            _logger.info('Fetching a new page in Form: %s' % form.name)
            self.lead_execution(requests.get(r['paging']['next']).json(), form)
        return

    @api.model
    def fetch_facebook_leads(self):
        fb_api = "https://graph.facebook.com/v10.0/"
        for form in self.env['crm.facebook.form'].search([('state', '=', 'confirm')]):
            _logger.info(' Get leads: %s' % form.name)
            r = requests.get(fb_api + form.fb_form_id + "/leads", params={'access_token': form.access_token,
                                                                          'fields': 'campaign_id, field_data, created_time, is_organic,ad_id, campaign_name, adset_name, ad_nameadset_id'}).json()
            self.lead_execution(r, form)
        _logger.info('Leads Created Successfully !')