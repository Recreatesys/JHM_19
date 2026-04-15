from datetime import datetime, time as dtime

from odoo import api, fields, models

_CASE_STATUS = [
    ('not_required', 'Not Required'),
    ('not_started',  'Not Started'),
    ('waiting',      'Waiting'),
    ('in_progress',  'In Progress'),
    ('lodged',       'Lodged'),
    ('appealed',     'Appealed'),
    ('re_applied',   'Re-applied'),
    ('completed',    'Completed'),
    ('rejected',     'Rejected'),
    ('invited',      'Invited'),
    ('re_sit',       'Re-sit'),
    ('failed',       'Failed'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Rename core fields
    email = fields.Char(string='Main Applicant Email')
    phone = fields.Char(string='Main Applicant Phone')

    # ── Profile ──────────────────────────────────────────────────────────
    occupation = fields.Char('Occupation')
    gender = fields.Selection([
        ('M', 'M'), ('F', 'F'), ('Male', 'Male'), ('Female', 'Female'), ('TBD', 'TBD'),
    ], string='Gender')
    client_nationality_id = fields.Many2one('jhm.nationality', string="Client's Nationality")
    jhm_line_id = fields.Char('Line ID')
    wechat = fields.Char('WeChat')
    b2b_engagement = fields.Boolean('B2B Engagement')
    background_id = fields.Many2one('jhm.background', string='Background')
    immigration_country = fields.Char('Immigration Country')
    communication_channel_id = fields.Many2one('jhm.communication.channel', string='Communication Channel')

    # ── Case ─────────────────────────────────────────────────────────────
    visa_program_id = fields.Many2one('jhm.visa.program', string='Visa Program')
    previous_visa_program_id = fields.Many2one('jhm.visa.program', string='Previous Visa Program')
    jhm_lead_source_id = fields.Many2one('jhm.lead.source', string='Lead Source')
    source_details = fields.Char('Source Details')
    commission = fields.Char('Commission')
    migration_budget = fields.Char('Migration Budget')
    facing_problems = fields.Char('Facing Problems')
    consultation_fee_paid = fields.Char('Consultation Fee Paid')

    # ── Dates ─────────────────────────────────────────────────────────────
    sf_creation_date = fields.Date('SF Creation Date')
    appointment_date = fields.Date('Appointment Date')
    appointment_date_2 = fields.Date('2nd Appointment Date')
    appointment_notes = fields.Char('Appointment Notes')
    last_call_date = fields.Date('Last Call Date')
    sf_followup_date = fields.Date('SF Followup Date')

    # ── Spouse ────────────────────────────────────────────────────────────
    type = fields.Selection(selection_add=[('spouse', 'Spouse')], ondelete={'spouse': 'set default'})
    spouse_name = fields.Char('Spouse Name')
    spouse_phone = fields.Char('Spouse Mobile')
    spouse_email = fields.Char('Spouse Email')
    spouse_partner_id = fields.Many2one('res.partner', string='Spouse Contact', ondelete='set null')
    spouse_of_id = fields.Many2one('res.partner', string='Spouse of', ondelete='set null', readonly=True)
    spouse_highest_qualification = fields.Char("Spouse's Highest Qualification")
    family_sponsorship = fields.Boolean('Family Sponsorship')
    spouse_studied_in_immigration_country = fields.Boolean("Spouse's Studied in Immigration Country")
    no_of_children = fields.Integer('No. of Children')
    child_1 = fields.Char('Applicant Child 1')
    child_2 = fields.Char('Applicant Child 2')
    child_3 = fields.Char('Applicant Child 3')
    child_4 = fields.Char('Applicant Child 4')
    child_5 = fields.Char('Applicant Child 5')

    # ── Academic ──────────────────────────────────────────────────────────
    academic_survey_date = fields.Date('Survey Date')
    academic_problems = fields.Selection([
        ('secondary_school', 'Secondary School'),
        ('adhd', 'AD/HD'),
        ('bachelor', 'Bachelor'),
        ('master', 'Master'),
        ('doctor', 'Doctor'),
    ], string='Problems')
    academic_studied_in_immigration_country = fields.Boolean('Studied in Immigration Country')
    academic_highest_qualification = fields.Selection([
        ('secondary_school', 'Secondary School'),
        ('adhd', 'AD/HD'),
        ('bachelor', 'Bachelor'),
        ('master', 'Master'),
        ('doctor', 'Doctor'),
    ], string='Highest Qualification')

    # ── Client Survey ─────────────────────────────────────────────────────
    survey_date = fields.Date('Survey Date')
    survey_problems = fields.Selection(
        [('5', '5'), ('4', '4'), ('3', '3'), ('2', '2'), ('1', '1')], string='Problems')
    survey_satisfaction = fields.Selection(
        [('5', '5'), ('4', '4'), ('3', '3'), ('2', '2'), ('1', '1')], string='Satisfaction')
    survey_professional = fields.Selection(
        [('5', '5'), ('4', '4'), ('3', '3'), ('2', '2'), ('1', '1')], string='Professional')
    survey_responsive = fields.Selection(
        [('5', '5'), ('4', '4'), ('3', '3'), ('2', '2'), ('1', '1')], string='Responsive')
    survey_recommend = fields.Selection(
        [('5', '5'), ('4', '4'), ('3', '3'), ('2', '2'), ('1', '1')], string='Recommend')

    def _compute_type_address_label(self):
        for partner in self:
            if partner.type == 'spouse':
                partner.type_address_label = 'Spouse'
            else:
                super(ResPartner, partner)._compute_type_address_label()

    # ── Long text ─────────────────────────────────────────────────────────
    chat_log = fields.Text('Chat Log')
    jhm_description = fields.Text('Description')

    # ── Case tracking ─────────────────────────────────────────────────────
    birthday = fields.Date('Birthday')
    nomination = fields.Selection(_CASE_STATUS, string='Nomination')
    nomination_due_date = fields.Date('Nomination Due Date')
    aus_skill_status = fields.Char('Aus Skill Status')
    assessment_due_date = fields.Date('Assessment Due Date')
    assessment = fields.Selection(_CASE_STATUS, string='Assessment')
    spouse_occupation = fields.Char("Spouse's Occupation")
    admin = fields.Text('Admin')
    eoi = fields.Selection(_CASE_STATUS, string='EOI')
    eoi_date = fields.Date('EOI Date')
    los_date = fields.Date('LOS Date')
    lodgment_date = fields.Date('Lodgment Date')
    ielts = fields.Selection(_CASE_STATUS, string='IELTS')
    ielts_due_date = fields.Date('IELTS Due Date')
    health = fields.Selection(_CASE_STATUS, string='Health')
    health_due_date = fields.Date('Health Due Date')
    police = fields.Selection(_CASE_STATUS, string='Police')
    police_due_date = fields.Date('Police Due Date')

    # ── Batch action: create document folders for selected contacts ───────
    def action_batch_create_document_folders(self):
        """Called from list-view Action menu. Creates a client FOLDER (type='folder')
        inside the CRM folder for every selected contact."""
        Document = self.env['documents.document'].sudo()
        Access = self.env['documents.access'].sudo()
        crm_folder = Document.search(
            [('type', '=', 'folder'), ('name', '=', 'CRM'), ('folder_id', '=', False)], limit=1
        )
        if not crm_folder:
            crm_folder = Document.create({'type': 'folder', 'name': 'CRM'})
        created = 0
        for rec in self:
            if rec.is_company:
                continue
            existing = Document.search([
                ('type', '=', 'folder'),
                ('res_model', '=', 'res.partner'),
                ('res_id', '=', rec.id),
            ], limit=1)
            if existing:
                continue
            visa = rec.visa_program_id.name if rec.visa_program_id else ''
            folder_name = ('%s-%s — Client File' % (visa, rec.name)) if visa else ('%s — Client File' % rec.name)
            folder = Document.create({
                'type': 'folder',
                'name': folder_name,
                'folder_id': crm_folder.id,
                'res_model': 'res.partner',
                'res_id': rec.id,
            })
            access_partners = rec | rec.message_follower_ids.mapped('partner_id')
            forbidden = self.env['res.users'].browse([1]).mapped('partner_id')
            existing_pids = Access.search([('document_id', '=', folder.id)]).mapped('partner_id').ids
            for partner in access_partners - forbidden:
                if partner.id in existing_pids:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Access.create({'document_id': folder.id, 'partner_id': partner.id, 'role': 'edit'})
                except Exception:
                    pass
            created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Folders Created',
                'message': '%d client folder(s) created in Documents.' % created,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _sync_spouse_contact(self):
        """Create or update the spouse contact linked to this partner."""
        for rec in self:
            if not rec.spouse_name and not rec.spouse_phone and not rec.spouse_email:
                continue
            spouse_vals = {
                'name': rec.spouse_name or 'Spouse',
                'phone': rec.spouse_phone or False,
                'email': rec.spouse_email or False,
                'parent_id': rec.id,
                'type': 'spouse',
                'is_company': False,
                'spouse_of_id': rec.id,
            }
            if rec.spouse_partner_id:
                rec.spouse_partner_id.write(spouse_vals)
            else:
                spouse = self.env['res.partner'].create(spouse_vals)
                rec.write({'spouse_partner_id': spouse.id})

    # ── SF Creation Date → overwrite create_date ──────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.sf_creation_date:
                sf_dt = datetime.combine(record.sf_creation_date, dtime.min)
                self._cr.execute(
                    "UPDATE res_partner SET create_date = %s WHERE id = %s",
                    (sf_dt, record.id),
                )
                record.invalidate_recordset(['create_date'])
        return records

    def write(self, vals):
        result = super().write(vals)

        if vals.get('sf_creation_date'):
            sf_dt = datetime.combine(vals['sf_creation_date'], dtime.min)
            self._cr.execute(
                "UPDATE res_partner SET create_date = %s WHERE id IN %s",
                (sf_dt, tuple(self.ids)),
            )
            self.invalidate_recordset(['create_date'])

        # Sync partner JHM fields → linked CRM leads (skip if called from CRM sync)
        if not self.env.context.get('jhm_no_sync'):
            _PARTNER_TO_CRM = {
                'gender': 'partner_gender',
                'client_nationality_id': 'partner_client_nationality_id',
                'jhm_line_id': 'partner_jhm_line_id',
                'wechat': 'partner_wechat',
                'b2b_engagement': 'partner_b2b_engagement',
                'background_id': 'partner_background_id',
                'immigration_country': 'partner_immigration_country',
                'communication_channel_id': 'partner_communication_channel_id',
                'visa_program_id': 'partner_visa_program_id',
                'previous_visa_program_id': 'partner_previous_visa_program_id',
                'jhm_lead_source_id': 'partner_jhm_lead_source_id',
                'source_details': 'partner_source_details',
                'commission': 'partner_commission',
                'migration_budget': 'partner_migration_budget',
                'facing_problems': 'partner_facing_problems',
                'consultation_fee_paid': 'partner_consultation_fee_paid',
                'sf_creation_date': 'partner_sf_creation_date',
                'appointment_date': 'partner_appointment_date',
                'appointment_date_2': 'partner_appointment_date_2',
                'appointment_notes': 'partner_appointment_notes',
                'last_call_date': 'partner_last_call_date',
                'sf_followup_date': 'partner_sf_followup_date',
                'chat_log': 'partner_chat_log',
                'jhm_description': 'partner_jhm_description',
                'occupation': 'partner_occupation',
                'birthday': 'partner_birthday',
                'admin': 'partner_admin',
                'nomination': 'partner_nomination',
                'nomination_due_date': 'partner_nomination_due_date',
                'aus_skill_status': 'partner_aus_skill_status',
                'assessment_due_date': 'partner_assessment_due_date',
                'assessment': 'partner_assessment',
                'spouse_occupation': 'partner_spouse_occupation',
                'child_1': 'partner_child_1',
                'child_2': 'partner_child_2',
                'child_3': 'partner_child_3',
                'child_4': 'partner_child_4',
                'spouse_highest_qualification': 'partner_spouse_highest_qualification',
                'eoi': 'partner_eoi',
                'eoi_date': 'partner_eoi_date',
                'los_date': 'partner_los_date',
                'lodgment_date': 'partner_lodgment_date',
                'ielts': 'partner_ielts',
                'ielts_due_date': 'partner_ielts_due_date',
                'health': 'partner_health',
                'health_due_date': 'partner_health_due_date',
                'police': 'partner_police',
                'police_due_date': 'partner_police_due_date',
            }
            crm_vals = {
                _PARTNER_TO_CRM[pf]: v
                for pf, v in vals.items()
                if pf in _PARTNER_TO_CRM
            }
            if crm_vals:
                leads = self.env['crm.lead'].search([('partner_id', 'in', self.ids)])
                if leads:
                    leads.with_context(jhm_no_sync=True).write(crm_vals)
                    # Also sync date_deadline from sf_followup_date
                    if 'sf_followup_date' in vals:
                        leads.with_context(jhm_no_sync=True).write(
                            {'date_deadline': vals['sf_followup_date']}
                        )
            elif 'sf_followup_date' in vals:
                leads = self.env['crm.lead'].search([('partner_id', 'in', self.ids)])
                if leads:
                    leads.with_context(jhm_no_sync=True).write(
                        {'date_deadline': vals['sf_followup_date']}
                    )

        # Sync spouse contact when spouse fields change
        if {'spouse_name', 'spouse_phone', 'spouse_email'} & set(vals):
            self._sync_spouse_contact()

        return result
