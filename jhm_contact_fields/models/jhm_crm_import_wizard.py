# -*- coding: utf-8 -*-
import base64
import json
import logging
import math
import re
from datetime import datetime
from html.parser import HTMLParser

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ── Column indices — JHM HK format ───────────────────────────────────────────
COL_LEAD_OWNER          = 0   # ignored
COL_LEAD_STATUS         = 1
COL_CREATE_DATE         = 2
COL_JHM_LEAD_OWNER      = 3
COL_FIRST_NAME          = 4
COL_LAST_NAME           = 5
COL_COMPANY_ACCOUNT     = 6   # ignored
COL_LEAD_SOURCE         = 7
COL_EMAIL               = 8   # fallback email
COL_GENDER              = 9
COL_MAIN_EMAIL          = 10
COL_MAIN_MOBILE         = 11
COL_TIME_TO_CLOSE       = 12
COL_PROBABILITY         = 13
COL_QUESTION_COMMENTS   = 14
COL_FACING_PROBLEMS     = 15
COL_DESCRIPTION         = 16
COL_COUNTRY             = 17
COL_COMMISSION          = 18
COL_INDUSTRY            = 19
COL_PREV_INDUSTRY       = 20
COL_SPOUSE_PHONE        = 21   # Spouse Mobile
COL_SPOUSE_EMAIL        = 22   # Spouse Email
COL_OCC_VISA_STATE      = 23   # Occupation / Visa / State → immigration_country
COL_APPOINTMENT_DATE    = 24
COL_APPOINTMENT_NOTES   = 25
COL_LAST_CALL_DATE      = 26
COL_FOLLOWUP_DATE       = 27
COL_CHAT_LOG            = 28
COL_PAID                = 29

# ── Column indices — JHM Taiwan format ───────────────────────────────────────
# Col 0: Lead ID (skip)
TW_COL_CREATE_DATE             = 1   # Lead Created Date → create_date
TW_COL_WEBINAR_NAME            = 2   # Webinar Name → source_details
TW_COL_NAME                    = 3   # Name → opportunity name
TW_COL_EMAIL                   = 4
TW_COL_MOBILE                  = 5
TW_COL_LINE_ID                 = 6
TW_COL_PREFERRED_CONTACT_TIME  = 7   # Preferred Contact Time → appointment_notes
TW_COL_BUDGET                  = 8
TW_COL_SALESPERSON             = 9
TW_COL_STAGE                   = 10
TW_COL_LAST_CONTACT_DATE       = 11
TW_COL_NEXT_ACTION             = 12
TW_COL_NEXT_ACTION_DATE        = 13
TW_COL_CONSIDERING_OTHERS      = 14
TW_COL_NOTES                   = 15
TW_COL_CALL_CONNECTED          = 16
TW_COL_ADDED_ON_LINE           = 17
TW_COL_EMAIL_SENT              = 18
TW_COL_GROUP_CREATED           = 19
TW_COL_FOLLOWUP_1              = 20
TW_COL_FOLLOWUP_2              = 21
TW_COL_FOLLOWUP_3              = 22
TW_COL_FOLLOWUP_4              = 23
TW_COL_CONVERTED_TO            = 26
TW_COL_CONVERTED_DATE          = 27

_TRUTHY = {'yes', 'y', 'true', '1', 'v', '✓', '✔', 'ok', 'done'}

# ── Case-status normalisation ─────────────────────────────────────────────────
_CASE_STATUS_MAP = {
    'not required': 'not_required',
    'not started':  'not_started',
    'waiting':      'waiting',
    'in progress':  'in_progress',
    'lodged':       'lodged',
    'appealed':     'appealed',
    're-applied':   're_applied',
    'completed':    'completed',
    'rejected':     'rejected',
    'invited':      'invited',
    're-sit':       're_sit',
    'failed':       'failed',
}

def _norm_case_status(raw):
    if not raw:
        return False
    return _CASE_STATUS_MAP.get(raw.strip().lower(), False)

def _norm_float(raw):
    if not raw:
        return 0.0
    try:
        return float(str(raw).strip().rstrip('%').strip())
    except (ValueError, TypeError):
        return 0.0

# ── Stage mapping — HK Opportunity format ─────────────────────────────────────
# (sf_stage_lower → (hk_pipeline_stage_name, force_prob, is_lost))
_HKO_STAGE_MAP = {
    'closed won':               ('Ready to Close', 100, False),
    'sms to follow up':         ('Valid Whatsapp Op', None, False),
    'proposal/price quote':     ('Service Agreement', None, False),
    'met & follow up':          ('Met & Follow Up', None, False),
    'meeting to be confirmed':  ('Appointment', None, False),
    'meeting arranged':         ('Appointment', None, False),
    'called & not yet decided': ('Valid Whatsapp Op', None, False),
    'closed lost':              ('New Lead', None, True),
    'cancelled':                ('New Lead', None, True),
    'meeting cancelled':        ('New Lead', None, False),
    'fail to connect':          ('New Lead', None, False),
    'converted to lead':        ('New Lead', None, False),
    'cv await':                 ('New Lead', None, False),
    'cv received':              ('New Lead', None, False),
    'awaiting english':         ('New Lead', None, False),
    'skill assessment':         ('New Lead', None, False),
    'ready to close':           ('Ready to Close', None, False),
}

# ── Name aliases for HK Opportunity import ───────────────────────────────────
# Maps short names in the Excel → full Odoo user names
_HKO_USER_ALIAS = {
    'john': 'JOHN HU',
}

# ── Column indices — JHM HK Opportunity format (Opp SF final 2.xls, 74 cols) ─
HKO_COL_OPP_NAME          = 0
HKO_COL_LEAD_SOURCE        = 1
HKO_COL_APPOINTMENT_DATE   = 2
HKO_COL_BIRTHDAY           = 3
HKO_COL_OCCUPATION         = 4
HKO_COL_TELESALES          = 5   # → salesperson (first) + co-owners (rest)
HKO_COL_OWNERSHIP          = 6   # → process_team_ids
HKO_COL_ADMIN              = 7
# 8  Category — skip
# 9–14 Deadline fields — skip
HKO_COL_NOMINATION_DUE     = 15
HKO_COL_NOMINATION         = 16
# 17 Current Month Commission — skip (computed)
HKO_COL_COMMISSION_RATIO   = 18
HKO_COL_EOI                = 19
# 20 EOI Application — skip
HKO_COL_EOI_DATE           = 21
HKO_COL_LOS_DATE           = 22
HKO_COL_LODGMENT_DATE      = 23
HKO_COL_IELTS_DUE_DATE     = 24
HKO_COL_IELTS              = 25
HKO_COL_FOLLOWUP_DATE      = 26
HKO_COL_HEALTH_DUE_DATE    = 27
HKO_COL_HEALTH             = 28
HKO_COL_POLICE             = 29
HKO_COL_POLICE_DUE_DATE    = 30
HKO_COL_AMOUNT             = 31
HKO_COL_CLOSE_DATE         = 32
HKO_COL_STAGE              = 33
HKO_COL_EMAIL              = 34
HKO_COL_MOBILE             = 35
HKO_COL_CHILD_1            = 36
HKO_COL_CHILD_2            = 37
HKO_COL_CHILD_3            = 38
HKO_COL_CHILD_4            = 39
HKO_COL_PROBABILITY        = 40
# 41 Fiscal Period — skip
# 42 Age — skip
HKO_COL_CREATED_DATE       = 43
HKO_COL_OPP_OWNER          = 44
HKO_COL_PAYMENT_1          = 45
# 46 1st Payment Commission — skip (computed)
HKO_COL_PAYMENT_DATE_1     = 47
HKO_COL_PAYMENT_2          = 48
# 49 2nd Payment Commission — skip
HKO_COL_AUS_SKILL_STATUS   = 50
HKO_COL_ASSESSMENT_DUE     = 51
HKO_COL_ASSESSMENT         = 52
HKO_COL_PAYMENT_DATE_2     = 53
# 54 3rd mth date — skip
HKO_COL_PAYMENT_3          = 55
# 56 3rd Payment Commission — skip
HKO_COL_PAYMENT_DATE_3     = 57
# 58 4th Payment Commission — skip
HKO_COL_PAYMENT_4          = 59
HKO_COL_PAYMENT_DATE_4     = 60
HKO_COL_PAYMENT_5          = 61
# 62 5th Payment Commission — skip
HKO_COL_PAYMENT_DATE_5     = 63
# 64 6th mth date — skip
HKO_COL_ACCOUNT_NAME       = 65
HKO_COL_SPOUSE_EMAIL       = 66
HKO_COL_SPOUSE_MOBILE      = 67
HKO_COL_SPOUSE_NAME        = 68
HKO_COL_SPOUSE_QUAL        = 69
HKO_COL_SPOUSE_OCC         = 70
# 71 Spouse studied — skip
# 72 Balance — skip (computed)
# 73 Spouse Mobile duplicate — skip

# ── Column indices — JHM Vietnam format ──────────────────────────────────────
# Header is at row index 11; data starts at row index 12 (skip=12)
VN_COL_CREATE_DATE         = 1
VN_COL_LEAD_OWNER          = 3
VN_COL_LEAD_SOURCE         = 4
VN_COL_LAST_CALL_DATE      = 5
VN_COL_FOLLOWUP_DATE       = 6
VN_COL_APPOINTMENT_DATE    = 7
VN_COL_APPOINTMENT_DATE_2  = 8
VN_COL_PROBABILITY         = 9
VN_COL_INDUSTRY            = 10
VN_COL_LEAD_STATUS         = 11
VN_COL_FIRST_NAME          = 12
VN_COL_LAST_NAME           = 13
VN_COL_MOBILE              = 14
VN_COL_EMAIL               = 15

# ── Gender normalisation map ───────────────────────────────────────────────────
_GENDER_MAP = {
    'male': 'M', 'men': 'M', 'mr': 'M', 'mr.': 'M', '男': 'M', 'm': 'M',
    'female': 'F', 'women': 'F', 'ms': 'F', 'ms.': 'F', 'mrs': 'F', 'mrs.': 'F',
    '女': 'F', 'f': 'F',
}

# ── Time-to-close normalisation ────────────────────────────────────────────────
_TTC_MAP = {
    '1 month':    '1month',
    '1month':     '1month',
    '2-3 months': '2_3month',
    '2-3months':  '2_3month',
    '2_3month':   '2_3month',
    'tbd':        'tbd',
    '':           False,
}

_BATCH_CTX = {
    'tracking_disable':        True,
    'mail_notrack':            True,
    'mail_create_nosubscribe': True,
    'jhm_import':              True,
}


# ── HTML table parser ──────────────────────────────────────────────────────────
class _XlsHtmlParser(HTMLParser):
    """Parse an Excel-Web-Archive HTML file into list[list[str]]."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._cur_row = None
        self._cur_cell = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self._cur_row = []
        elif tag in ('td', 'th') and self._cur_row is not None:
            self._cur_cell = []
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self._in_cell:
            self._cur_row.append(''.join(self._cur_cell).strip())
            self._cur_cell = None
            self._in_cell = False
        elif tag == 'tr' and self._cur_row is not None:
            self.rows.append(self._cur_row)
            self._cur_row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cur_cell.append(data)

    def handle_entityref(self, name):
        if self._in_cell:
            import html
            self._cur_cell.append(html.unescape(f'&{name};'))

    def handle_charref(self, name):
        if self._in_cell:
            import html
            self._cur_cell.append(html.unescape(f'&#{name};'))


def _parse_date(raw):
    """Parse DD/MM/YYYY date string.  Returns date or None."""
    if not raw or raw.strip() in ('-', '', 'N/A'):
        return None
    raw = raw.strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _norm_gender(raw):
    if not raw:
        return False
    return _GENDER_MAP.get(raw.strip().lower(), False)


def _norm_probability(raw):
    if not raw:
        return False
    raw = raw.strip().rstrip('%').strip()
    if raw.upper() == 'TBD' or raw == '':
        return '10'
    valid = {'10', '30', '50', '70', '90', '100'}
    try:
        val = int(float(raw))
        closest = min(valid, key=lambda x: abs(int(x) - val))
        return closest
    except ValueError:
        return '10'


def _norm_ttc(raw):
    if not raw:
        return False
    key = raw.strip().lower()
    if key in _TTC_MAP:
        return _TTC_MAP[key]
    if '2' in key and '3' in key:
        return '2_3month'
    if '1' in key:
        return '1month'
    return 'tbd'


def _parse_file(file_data_b64, skip=1):
    """Decode and parse an uploaded XLS/XLSX file into data rows.

    `skip` = number of leading rows to discard (default 1 = header row only).
    Vietnam format passes skip=12 to drop 11 metadata rows + 1 header row.

    Supports:
      - Real .xlsx files (openpyxl)
      - Real .xls files (xlrd)
      - Excel-saved-as-HTML (.xls Web Archive) — legacy fallback
    """
    import io
    raw_bytes = base64.b64decode(file_data_b64)

    # ── Try openpyxl (.xlsx) ─────────────────────────────────────────────
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(['' if v is None else str(v) for v in row])
        wb.close()
        if rows:
            return rows[skip:]
    except Exception:
        pass

    # ── Try xlrd (.xls binary) ───────────────────────────────────────────
    try:
        import xlrd
        wb = xlrd.open_workbook(file_contents=raw_bytes)
        ws = wb.sheet_by_index(0)
        rows = []
        for i in range(ws.nrows):
            rows.append([str(ws.cell_value(i, j)) for j in range(ws.ncols)])
        if rows:
            return rows[skip:]
    except Exception:
        pass

    # ── Fallback: HTML-based XLS (Excel Web Archive) ─────────────────────
    try:
        content = raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        content = raw_bytes.decode('latin-1')
    parser = _XlsHtmlParser()
    parser.feed(content)
    return parser.rows[skip:] if parser.rows else []


class JhmCrmImportWizard(models.TransientModel):
    _name = 'jhm.crm.import.wizard'
    _description = 'JHM CRM Lead Import Wizard'

    file_ids           = fields.One2many('jhm.crm.import.file', 'wizard_id', string='Files')
    current_file_id    = fields.Many2one('jhm.crm.import.file', string='Current File')
    current_file_index = fields.Integer(default=0)
    total_files        = fields.Integer(default=1)
    grand_imported     = fields.Integer(default=0)
    grand_skipped      = fields.Integer(default=0)
    import_format = fields.Selection([
        ('hk',             'JHM HK Format'),
        ('hk_opportunity', 'JHM HK Opportunity'),
        ('taiwan',         'JHM Taiwan Format'),
        ('vietnam',        'JHM Vietnam Format'),
    ], string='File Format', default='hk', required=True)
    import_mode = fields.Selection([
        ('create', 'Create new opportunities'),
        ('update', 'Update existing opportunities (match by email / phone)'),
    ], string='Import Mode', default='create', required=True)

    # ── Progress / result fields ──────────────────────────────────────────────
    state = fields.Selection([
        ('draft',   'Ready'),
        ('running', 'Importing'),
        ('done',    'Done'),
    ], default='draft')

    total_rows    = fields.Integer('Total Rows',    readonly=True)
    total_batches = fields.Integer('Total Batches', readonly=True)
    current_batch = fields.Integer('Current Batch', readonly=True, default=0)
    imported_count = fields.Integer('Imported',          readonly=True)
    skipped_count  = fields.Integer('Skipped / Errors',  readonly=True)
    result_log     = fields.Text('Import Log',           readonly=True)

    # ── Persisted pre-pass state (internal, cleared after import) ─────────────
    import_visa_cache   = fields.Text()
    import_source_cache = fields.Text()
    import_user_cache   = fields.Text()
    import_lost_cache   = fields.Text()
    import_stage_new_id = fields.Integer()
    import_stage_met_id = fields.Integer()
    import_stage_svc_id = fields.Integer()
    import_fallback_uid = fields.Integer()
    import_mode_stored   = fields.Char()   # persisted copy of import_mode for batch phase
    import_format_stored = fields.Char()   # persisted copy of import_format for batch phase
    import_stage_cache   = fields.Text()   # Taiwan: stage_name → stage_id cache

    BATCH_SIZE = 1000

    # ─────────────────────────────────────────────────────────────────────────
    # Lookup helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_or_create_visa_program(env, cache, name):
        if not name:
            return False
        key = name.strip().lower()
        if key in cache:
            return cache[key]
        rec = env['jhm.visa.program'].search([('name', '=ilike', name.strip())], limit=1)
        if not rec:
            rec = env['jhm.visa.program'].create({'name': name.strip()})
        cache[key] = rec.id
        return rec.id

    @staticmethod
    def _get_or_create_lead_source(env, cache, name):
        if not name:
            return False
        key = name.strip().lower()
        if key in cache:
            return cache[key]
        rec = env['jhm.lead.source'].search([('name', '=ilike', name.strip())], limit=1)
        if not rec:
            rec = env['jhm.lead.source'].create({'name': name.strip()})
        cache[key] = rec.id
        return rec.id

    @staticmethod
    def _get_user(env, cache, name, fallback_id):
        if not name:
            return fallback_id
        key = name.strip().lower()
        if key in cache:
            return cache[key]
        # =ilike: exact case-insensitive match (not substring)
        rec = env['res.users'].search([
            ('name', '=ilike', name.strip()),
            ('share', '=', False),
        ], limit=1)
        if not rec:
            login = re.sub(r'\s+', '.', name.strip().lower()) + '@jhm.com'
            if env['res.users'].search([('login', '=', login)], limit=1):
                login = re.sub(r'\s+', '_', name.strip().lower()) + '_jhm@jhm.com'
            try:
                rec = env['res.users'].with_context(no_reset_password=True).create({
                    'name':      name.strip(),
                    'login':     login,
                    'email':     login,
                    'groups_id': [(4, env.ref('base.group_user').id)],
                })
                _logger.info('JHM Import: auto-created user "%s" (%s)', name.strip(), login)
            except Exception as e:
                _logger.warning('JHM Import: failed to create user "%s": %s', name.strip(), e)
                return fallback_id
        uid = rec.id
        cache[key] = uid
        return uid

    @staticmethod
    def _get_lost_reason(env, cache, name):
        key = name.lower()
        if key in cache:
            return cache[key]
        rec = env['crm.lost.reason'].search([('name', '=ilike', name)], limit=1)
        if not rec:
            rec = env['crm.lost.reason'].create({'name': name})
        cache[key] = rec.id
        return rec.id

    @staticmethod
    def _get_stage(env, cache, name):
        """Look up a pipeline stage by exact case-insensitive name. Returns stage ID or False."""
        if not name:
            return False
        key = name.strip().lower()
        if key in cache:
            return cache[key]
        rec = env['crm.stage'].search([('name', '=ilike', name.strip())], limit=1)
        sid = rec.id if rec else False
        cache[key] = sid
        return sid

    # ─────────────────────────────────────────────────────────────────────────
    # Row parser
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_row(self, env, row, fallback_uid,
                   stage_new_lead_id, stage_met_followup_id, stage_service_agr_id,
                   visa_cache, source_cache, user_cache, lost_cache):

        row = list(row) + [''] * max(0, 30 - len(row))

        def c(idx):
            try:
                return (row[idx] or '').strip()
            except IndexError:
                return ''

        first = c(COL_FIRST_NAME)
        last  = c(COL_LAST_NAME)
        contact_name = ' '.join(filter(None, [first, last])) or 'Unknown'

        jhm_owner_raw = c(COL_JHM_LEAD_OWNER)
        owner_parts   = [p.strip() for p in jhm_owner_raw.split(';') if p.strip()]
        primary_user_id = self._get_user(env, user_cache, owner_parts[0] if owner_parts else '', fallback_uid)
        co_owner_ids    = []
        for extra in owner_parts[1:]:
            uid = self._get_user(env, user_cache, extra, None)
            if uid:
                co_owner_ids.append(uid)

        lead_source_id = self._get_or_create_lead_source(env, source_cache, c(COL_LEAD_SOURCE))

        email    = c(COL_MAIN_EMAIL) or c(COL_EMAIL)
        gender   = _norm_gender(c(COL_GENDER))
        prob_str = _norm_probability(c(COL_PROBABILITY))
        ttc      = _norm_ttc(c(COL_TIME_TO_CLOSE))

        create_date_val  = _parse_date(c(COL_CREATE_DATE))
        appointment_date = _parse_date(c(COL_APPOINTMENT_DATE))
        last_call_date   = _parse_date(c(COL_LAST_CALL_DATE))
        followup_date    = _parse_date(c(COL_FOLLOWUP_DATE))

        visa_id      = self._get_or_create_visa_program(env, visa_cache, c(COL_INDUSTRY))
        prev_visa_id = self._get_or_create_visa_program(env, visa_cache, c(COL_PREV_INDUSTRY))

        immigration_country = c(COL_OCC_VISA_STATE)
        jhm_desc = '\n\n'.join(filter(None, [c(COL_QUESTION_COMMENTS), c(COL_DESCRIPTION)])) or False

        lead_status = c(COL_LEAD_STATUS).strip().lower()
        is_lost  = False
        stage_id = stage_new_lead_id

        if lead_status == 'open':
            stage_id = stage_new_lead_id
        elif lead_status == 'contacted':
            stage_id = stage_met_followup_id
        elif lead_status == 'qualified':
            stage_id = stage_service_agr_id
        elif lead_status == 'unqualified':
            is_lost  = True
            stage_id = stage_new_lead_id

        lost_reason_id = self._get_lost_reason(env, lost_cache, 'Unqualified') if is_lost else False

        vals = {
            'name':                              contact_name,
            'contact_name':                      contact_name,
            'type':                              'opportunity',
            'email_from':                        email or False,
            'phone':                             c(COL_MAIN_MOBILE) or False,
            'user_id':                           primary_user_id,
            'active':                            True,
            'partner_gender':                    gender or False,
            'partner_jhm_lead_source_id':        lead_source_id,
            'partner_visa_program_id':           visa_id,
            'partner_previous_visa_program_id':  prev_visa_id,
            'partner_immigration_country':       immigration_country or False,
            'partner_commission':                c(COL_COMMISSION) or False,
            'partner_facing_problems':           c(COL_FACING_PROBLEMS) or False,
            'partner_consultation_fee_paid':     c(COL_PAID) or False,
            'partner_appointment_date':          appointment_date,
            'partner_appointment_notes':         c(COL_APPOINTMENT_NOTES) or False,
            'partner_last_call_date':            last_call_date,
            'partner_sf_followup_date':          followup_date,
            'partner_chat_log':                  c(COL_CHAT_LOG) or False,
            'partner_jhm_description':           jhm_desc,
            'partner_spouse_phone':              c(COL_SPOUSE_PHONE) or False,
            'partner_spouse_email':              c(COL_SPOUSE_EMAIL) or False,
        }

        if stage_id:
            vals['stage_id'] = stage_id
        if prob_str:
            vals['jhm_probability'] = prob_str
            vals['probability'] = float(prob_str)
        if ttc:
            vals['time_to_close'] = ttc
        if lost_reason_id:
            vals['lost_reason_id'] = lost_reason_id
        if co_owner_ids:
            vals['co_owner_ids'] = [(4, uid) for uid in co_owner_ids]

        # Match key for update mode — used to find existing opportunity
        meta = {
            'create_date':  create_date_val,
            'is_lost':      is_lost,
            'match_email':  c(COL_MAIN_EMAIL) or c(COL_EMAIL),
            'match_phone':  c(COL_MAIN_MOBILE),
            'spouse_phone': c(COL_SPOUSE_PHONE) or False,
            'spouse_email': c(COL_SPOUSE_EMAIL) or False,
        }
        return vals, meta

    def _parse_row_taiwan(self, env, row, fallback_uid, stage_cache, user_cache):
        """Parse one row from the JHM Taiwan XLS format.
        Col 0: Lead ID (skip)
        Col 1: Lead Created Date → create_date
        Col 2: Webinar Name → source_details
        Col 3: Name → opportunity name
        Col 4: Email
        Col 5: Mobile
        Col 6: Line ID
        Col 7: Preferred Contact Time → appointment_notes
        Col 8: Budget → migration_budget
        Col 9: Salesperson
        Col 10: Stages → pipeline stage
        Col 11: Last Contact Date → last_call_date
        Col 12: Next Action → notes
        Col 13: Next Action Date → followup_date
        Col 14: Considering Others → notes
        Col 15: Notes → chat_log / description
        Col 16-19: Call Connected / Added on LINE / Email Sent / Group Created
        Col 20-23: Follow-up notes 1-4
        Col 26: Converted To
        Col 27: Converted Date
        """
        row = list(row) + [''] * max(0, 28 - len(row))

        def c(idx):
            try:
                return (row[idx] or '').strip()
            except IndexError:
                return ''

        def _tw_status(idx):
            v = c(idx).strip().lower()
            if not v:
                return False
            return 'true' if v in _TRUTHY else 'false'

        contact_name = c(TW_COL_NAME) or 'Unknown'
        email        = c(TW_COL_EMAIL)
        mobile       = c(TW_COL_MOBILE)

        user_id  = self._get_user(env, user_cache, c(TW_COL_SALESPERSON), fallback_uid)
        stage_id = self._get_stage(env, stage_cache, c(TW_COL_STAGE))

        create_date_val   = _parse_date(c(TW_COL_CREATE_DATE))
        last_contact_date = _parse_date(c(TW_COL_LAST_CONTACT_DATE))
        next_action_date  = _parse_date(c(TW_COL_NEXT_ACTION_DATE))

        # Combine Next Action + Considering Others + Notes into description
        notes_parts = list(filter(None, [
            ('Next Action: ' + c(TW_COL_NEXT_ACTION)) if c(TW_COL_NEXT_ACTION) else '',
            ('Considering Others: ' + c(TW_COL_CONSIDERING_OTHERS)) if c(TW_COL_CONSIDERING_OTHERS) else '',
            c(TW_COL_NOTES),
        ]))
        description = '\n'.join(filter(None, notes_parts)) or False

        vals = {
            'name':                          contact_name,
            'contact_name':                  contact_name,
            'type':                          'opportunity',
            'email_from':                    email or False,
            'phone':                         mobile or False,
            'user_id':                       user_id,
            'active':                        True,
            'partner_jhm_line_id':           c(TW_COL_LINE_ID) or False,
            'partner_source_details':        c(TW_COL_WEBINAR_NAME) or False,
            'webinar_name':                  c(TW_COL_WEBINAR_NAME) or False,
            'partner_appointment_notes':     c(TW_COL_PREFERRED_CONTACT_TIME) or False,
            'partner_migration_budget':      c(TW_COL_BUDGET) or False,
            'partner_last_call_date':        last_contact_date,
            'partner_sf_followup_date':      next_action_date,
            'partner_chat_log':              c(TW_COL_NOTES) or False,
            'partner_jhm_description':       description,
            'tw_followup_1':                 c(TW_COL_FOLLOWUP_1) or False,
            'tw_followup_2':                 c(TW_COL_FOLLOWUP_2) or False,
            'tw_followup_3':                 c(TW_COL_FOLLOWUP_3) or False,
            'tw_followup_4':                 c(TW_COL_FOLLOWUP_4) or False,
            'tw_call_connected':             _tw_status(TW_COL_CALL_CONNECTED),
            'tw_added_on_line':              _tw_status(TW_COL_ADDED_ON_LINE),
            'tw_email_sent':                 _tw_status(TW_COL_EMAIL_SENT),
            'tw_group_created':              _tw_status(TW_COL_GROUP_CREATED),
        }
        if stage_id:
            vals['stage_id'] = stage_id

        meta = {
            'create_date': create_date_val,
            'is_lost':     False,
            'match_email': email,
            'match_phone': mobile,
        }
        return vals, meta

    def _parse_row_vietnam(self, env, row, fallback_uid,
                           stage_cache, user_cache, visa_cache, source_cache, lost_cache):
        """Parse one row from the JHM Vietnam XLS format."""
        row = list(row) + [''] * max(0, 16 - len(row))

        def c(idx):
            try:
                return (row[idx] or '').strip()
            except IndexError:
                return ''

        first = c(VN_COL_FIRST_NAME)
        last  = c(VN_COL_LAST_NAME)
        contact_name = ' '.join(filter(None, [first, last])) or 'Unknown'

        user_id  = self._get_user(env, user_cache, c(VN_COL_LEAD_OWNER), fallback_uid)

        lead_source_id = self._get_or_create_lead_source(env, source_cache, c(VN_COL_LEAD_SOURCE))
        visa_id        = self._get_or_create_visa_program(env, visa_cache,  c(VN_COL_INDUSTRY))

        prob_str = _norm_probability(c(VN_COL_PROBABILITY))

        create_date_val   = _parse_date(c(VN_COL_CREATE_DATE))
        last_call_date    = _parse_date(c(VN_COL_LAST_CALL_DATE))
        followup_date     = _parse_date(c(VN_COL_FOLLOWUP_DATE))
        appointment_date  = _parse_date(c(VN_COL_APPOINTMENT_DATE))
        appointment_date2 = _parse_date(c(VN_COL_APPOINTMENT_DATE_2))

        lead_status = c(VN_COL_LEAD_STATUS).strip().lower()
        is_lost  = lead_status == 'unqualified'
        stage_id = self._get_stage(env, stage_cache, c(VN_COL_LEAD_STATUS))
        lost_reason_id = self._get_lost_reason(env, lost_cache, 'Unqualified') if is_lost else False

        vals = {
            'name':                          contact_name,
            'contact_name':                  contact_name,
            'type':                          'opportunity',
            'email_from':                    c(VN_COL_EMAIL) or False,
            'phone':                         c(VN_COL_MOBILE) or False,
            'user_id':                       user_id,
            'active':                        True,
            'partner_jhm_lead_source_id':    lead_source_id,
            'partner_visa_program_id':       visa_id,
            'partner_last_call_date':        last_call_date,
            'partner_sf_followup_date':      followup_date,
            'partner_appointment_date':      appointment_date,
            'partner_appointment_date_2':    appointment_date2,
        }
        if stage_id:
            vals['stage_id'] = stage_id
        if prob_str:
            vals['jhm_probability'] = prob_str
            vals['probability']     = float(prob_str)
        if lost_reason_id:
            vals['lost_reason_id'] = lost_reason_id

        meta = {
            'create_date': create_date_val,
            'is_lost':     is_lost,
            'match_email': c(VN_COL_EMAIL),
            'match_phone': c(VN_COL_MOBILE),
            'user_name':   c(VN_COL_LEAD_OWNER),
        }
        return vals, meta

    def _resolve_hko_user(self, env, user_cache, name, fallback_uid):
        """Look up an existing user by name (with alias map). If not found, return fallback.
        Never auto-creates users for the HK Opportunity format."""
        if not name:
            return fallback_uid
        resolved = _HKO_USER_ALIAS.get(name.strip().lower(), name.strip())
        key = resolved.lower()
        if key in user_cache:
            return user_cache[key]
        rec = env['res.users'].search([
            ('name', '=ilike', resolved),
            ('share', '=', False),
        ], limit=1)
        uid = rec.id if rec else fallback_uid
        user_cache[key] = uid
        return uid

    def _parse_row_hk_opportunity(self, env, row, fallback_uid,
                                  stage_cache, user_cache, source_cache, lost_cache):
        """Parse one row from the JHM HK Opportunity (Salesforce export) format."""
        row = list(row) + [''] * max(0, 74 - len(row))

        def c(idx):
            try:
                return (row[idx] or '').strip()
            except IndexError:
                return ''

        opp_name     = c(HKO_COL_OPP_NAME) or c(HKO_COL_ACCOUNT_NAME) or 'Unknown'
        contact_name = c(HKO_COL_ACCOUNT_NAME) or opp_name
        email        = c(HKO_COL_EMAIL)
        mobile       = c(HKO_COL_MOBILE)

        # Telesales Person → salesperson (first) + co-owners (rest)
        telesales_parts = [p.strip() for p in c(HKO_COL_TELESALES).split(';') if p.strip()]
        primary_name = telesales_parts[0] if telesales_parts else ''
        user_id      = self._resolve_hko_user(env, user_cache, primary_name, fallback_uid)
        co_owner_ids = []
        for extra in telesales_parts[1:]:
            uid = self._resolve_hko_user(env, user_cache, extra, None)
            if uid:
                co_owner_ids.append(uid)

        # Ownership → process_team_ids
        process_team_ids = []
        ownership_name = c(HKO_COL_OWNERSHIP)
        if ownership_name:
            uid = self._resolve_hko_user(env, user_cache, ownership_name, None)
            if uid:
                process_team_ids.append(uid)

        source_id    = self._get_or_create_lead_source(env, source_cache, c(HKO_COL_LEAD_SOURCE))

        # Stage mapping via _HKO_STAGE_MAP → look up target stage by name
        sf_stage_key  = c(HKO_COL_STAGE).strip().lower()
        target_stage_name, force_prob, is_lost = _HKO_STAGE_MAP.get(
            sf_stage_key, ('New Lead', None, False)
        )
        stage_id = self._get_stage(env, stage_cache, target_stage_name)

        prob_str = _norm_probability(c(HKO_COL_PROBABILITY))
        if force_prob is not None:
            prob_str = str(force_prob)

        create_date_val   = _parse_date(c(HKO_COL_CREATED_DATE))
        lost_reason_id    = self._get_lost_reason(env, lost_cache, 'Cancelled/Lost') if is_lost else False

        vals = {
            'name':                              opp_name,
            'contact_name':                      contact_name,
            'type':                              'opportunity',
            'email_from':                        email or False,
            'phone':                             mobile or False,
            'user_id':                           user_id,
            'active':                            True,
            'partner_jhm_lead_source_id':        source_id,
            'co_owner_ids':                      [(4, uid) for uid in co_owner_ids] if co_owner_ids else False,
            'process_team_ids':                  [(4, uid) for uid in process_team_ids] if process_team_ids else False,
            # Profile
            'partner_occupation':                c(HKO_COL_OCCUPATION) or False,
            'partner_birthday':                  _parse_date(c(HKO_COL_BIRTHDAY)),
            'partner_admin':                     c(HKO_COL_ADMIN) or False,
            # Case tracking
            'partner_nomination_due_date':       _parse_date(c(HKO_COL_NOMINATION_DUE)),
            'partner_nomination':                _norm_case_status(c(HKO_COL_NOMINATION)),
            'partner_eoi':                       _norm_case_status(c(HKO_COL_EOI)),
            'partner_eoi_date':                  _parse_date(c(HKO_COL_EOI_DATE)),
            'partner_los_date':                  _parse_date(c(HKO_COL_LOS_DATE)),
            'partner_lodgment_date':             _parse_date(c(HKO_COL_LODGMENT_DATE)),
            'partner_ielts_due_date':            _parse_date(c(HKO_COL_IELTS_DUE_DATE)),
            'partner_ielts':                     _norm_case_status(c(HKO_COL_IELTS)),
            'partner_sf_followup_date':          _parse_date(c(HKO_COL_FOLLOWUP_DATE)),
            'partner_health_due_date':           _parse_date(c(HKO_COL_HEALTH_DUE_DATE)),
            'partner_health':                    _norm_case_status(c(HKO_COL_HEALTH)),
            'partner_police':                    _norm_case_status(c(HKO_COL_POLICE)),
            'partner_police_due_date':           _parse_date(c(HKO_COL_POLICE_DUE_DATE)),
            'partner_aus_skill_status':          c(HKO_COL_AUS_SKILL_STATUS) or False,
            'partner_assessment_due_date':       _parse_date(c(HKO_COL_ASSESSMENT_DUE)),
            'partner_assessment':                _norm_case_status(c(HKO_COL_ASSESSMENT)),
            'partner_appointment_date':          _parse_date(c(HKO_COL_APPOINTMENT_DATE)),
            # Sales tab
            'sale_total_amount':                 _norm_float(c(HKO_COL_AMOUNT)),
            'sale_order_issue_date':             _parse_date(c(HKO_COL_CLOSE_DATE)),
            'sale_commission_ratio':             _norm_float(c(HKO_COL_COMMISSION_RATIO)),
            'sale_payment_1':                    _norm_float(c(HKO_COL_PAYMENT_1)),
            'sale_payment_date_1':               _parse_date(c(HKO_COL_PAYMENT_DATE_1)),
            'sale_payment_2':                    _norm_float(c(HKO_COL_PAYMENT_2)),
            'sale_payment_date_2':               _parse_date(c(HKO_COL_PAYMENT_DATE_2)),
            'sale_payment_3':                    _norm_float(c(HKO_COL_PAYMENT_3)),
            'sale_payment_date_3':               _parse_date(c(HKO_COL_PAYMENT_DATE_3)),
            'sale_payment_4':                    _norm_float(c(HKO_COL_PAYMENT_4)),
            'sale_payment_date_4':               _parse_date(c(HKO_COL_PAYMENT_DATE_4)),
            'sale_payment_5':                    _norm_float(c(HKO_COL_PAYMENT_5)),
            'sale_payment_date_5':               _parse_date(c(HKO_COL_PAYMENT_DATE_5)),
            # Spouse & children
            'partner_spouse_name':               c(HKO_COL_SPOUSE_NAME) or False,
            'partner_spouse_phone':              c(HKO_COL_SPOUSE_MOBILE) or False,
            'partner_spouse_email':              c(HKO_COL_SPOUSE_EMAIL) or False,
            'partner_spouse_highest_qualification': c(HKO_COL_SPOUSE_QUAL) or False,
            'partner_spouse_occupation':         c(HKO_COL_SPOUSE_OCC) or False,
            'partner_child_1':                   c(HKO_COL_CHILD_1) or False,
            'partner_child_2':                   c(HKO_COL_CHILD_2) or False,
            'partner_child_3':                   c(HKO_COL_CHILD_3) or False,
            'partner_child_4':                   c(HKO_COL_CHILD_4) or False,
        }
        if stage_id:
            vals['stage_id'] = stage_id
        if prob_str:
            vals['jhm_probability'] = min(str(prob_str), '100')
            vals['probability']     = float(prob_str)
        if lost_reason_id:
            vals['lost_reason_id'] = lost_reason_id

        meta = {
            'create_date': create_date_val,
            'is_lost':     is_lost,
            'match_email': email,
            'match_phone': mobile,
            'opp_name':    opp_name,
        }
        return vals, meta

    # ─────────────────────────────────────────────────────────────────────────
    # Pre-pass helper — warms all lookup caches for one set of data rows
    # ─────────────────────────────────────────────────────────────────────────

    def _run_prepass(self, data_rows, fmt, env, fallback_uid,
                     visa_cache, source_cache, user_cache, lost_cache, stage_cache):
        """Warm lookup caches from data_rows without writing CRM records.
        Returns (possibly updated) fallback_uid."""

        def _c(row, i):
            try:
                return (row[i] or '').strip()
            except IndexError:
                return ''

        if fmt == 'hk_opportunity':
            stefano = env['res.users'].search(
                [('name', '=ilike', 'Stefano'), ('share', '=', False)], limit=1
            )
            if stefano:
                fallback_uid = stefano.id
            for row in data_rows:
                row = list(row) + [''] * max(0, 74 - len(row))
                for part in [p.strip() for p in _c(row, HKO_COL_TELESALES).split(';') if p.strip()]:
                    resolved = _HKO_USER_ALIAS.get(part.lower(), part)
                    self._resolve_hko_user(env, user_cache, resolved, fallback_uid)
                own = _c(row, HKO_COL_OWNERSHIP)
                if own:
                    self._resolve_hko_user(env, user_cache, _HKO_USER_ALIAS.get(own.lower(), own), fallback_uid)
                sf_key = _c(row, HKO_COL_STAGE).strip().lower()
                target, _, is_lost = _HKO_STAGE_MAP.get(sf_key, ('New Lead', None, False))
                self._get_stage(env, stage_cache, target)
                self._get_or_create_lead_source(env, source_cache, _c(row, HKO_COL_LEAD_SOURCE))
                if is_lost:
                    self._get_lost_reason(env, lost_cache, 'Cancelled/Lost')
            _logger.info('JHM CRM Import (HK Opp) pre-pass: %d users, %d stages',
                         len(user_cache), len(stage_cache))

        elif fmt == 'vietnam':
            for row in data_rows:
                row = list(row) + [''] * max(0, 16 - len(row))
                self._get_user(env, user_cache, _c(row, VN_COL_LEAD_OWNER), fallback_uid)
                self._get_stage(env, stage_cache, _c(row, VN_COL_LEAD_STATUS))
                self._get_or_create_lead_source(env, source_cache, _c(row, VN_COL_LEAD_SOURCE))
                self._get_or_create_visa_program(env, visa_cache,  _c(row, VN_COL_INDUSTRY))
                if _c(row, VN_COL_LEAD_STATUS).strip().lower() == 'unqualified':
                    self._get_lost_reason(env, lost_cache, 'Unqualified')
            _logger.info('JHM CRM Import (Vietnam) pre-pass: %d users, %d stages, %d visa',
                         len(user_cache), len(stage_cache), len(visa_cache))

        elif fmt == 'taiwan':
            for row in data_rows:
                row = list(row) + [''] * max(0, 28 - len(row))
                self._get_user(env, user_cache, _c(row, TW_COL_SALESPERSON), fallback_uid)
                self._get_stage(env, stage_cache, _c(row, TW_COL_STAGE))
            _logger.info('JHM CRM Import (Taiwan) pre-pass: %d users, %d stages',
                         len(user_cache), len(stage_cache))

        else:  # hk
            for row in data_rows:
                row = list(row) + [''] * max(0, 30 - len(row))
                self._get_or_create_visa_program(env, visa_cache,  _c(row, COL_INDUSTRY))
                self._get_or_create_visa_program(env, visa_cache,  _c(row, COL_PREV_INDUSTRY))
                self._get_or_create_lead_source(env, source_cache, _c(row, COL_LEAD_SOURCE))
                parts = [p.strip() for p in _c(row, COL_JHM_LEAD_OWNER).split(';') if p.strip()]
                if parts:
                    self._get_user(env, user_cache, parts[0], fallback_uid)
                for part in parts[1:]:
                    self._get_user(env, user_cache, part, None)
                if _c(row, COL_LEAD_STATUS).strip().lower() == 'unqualified':
                    self._get_lost_reason(env, lost_cache, 'Unqualified')
            _logger.info('JHM CRM Import (HK) pre-pass: %d visa, %d sources, %d users',
                         len(visa_cache), len(source_cache), len(user_cache))

        return fallback_uid

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1 — Setup: parse file(s), run pre-pass, store state, launch progress UI
    # ─────────────────────────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()
        pending_files = self.file_ids.filtered(lambda f: f.state == 'pending').sorted('sequence')
        if not pending_files:
            raise UserError(_('Please upload at least one file.'))

        fmt  = self.import_format or 'hk'
        skip = 12 if fmt == 'vietnam' else 1

        # Use the first pending file
        first_file = pending_files[0]
        data_rows = _parse_file(first_file.file_data, skip=skip)
        if not data_rows:
            raise UserError(_('No data found in "%s".') % (first_file.file_name or 'file'))

        total_rows    = len(data_rows)
        total_batches = max(1, math.ceil(total_rows / self.BATCH_SIZE))
        total_files   = len(pending_files)
        _logger.info('JHM CRM Import: file 1/%d — %d rows → %d batches',
                     total_files, total_rows, total_batches)

        ctx = dict(self.env.context, **_BATCH_CTX)
        env = self.env(context=ctx)

        fallback_user = env['res.users'].search(
            [('name', '=ilike', 'Stephano'), ('share', '=', False)], limit=1
        )
        fallback_uid = fallback_user.id if fallback_user else self.env.uid

        stage_new = env['crm.stage'].search([('name', 'ilike', 'New Lead')],        limit=1)
        stage_met = env['crm.stage'].search([('name', 'ilike', 'Met & Follow Up')], limit=1)
        stage_svc = env['crm.stage'].search([('name', 'ilike', 'Service Agreement')], limit=1)

        visa_cache   = {}
        source_cache = {}
        user_cache   = {}
        lost_cache   = {}
        stage_cache  = {}

        fallback_uid = self._run_prepass(
            data_rows, fmt, env, fallback_uid,
            visa_cache, source_cache, user_cache, lost_cache, stage_cache,
        )

        env.flush_all()
        env.invalidate_all()

        first_file.write({'state': 'running'})

        self.write({
            'state':               'running',
            'total_rows':          total_rows,
            'total_batches':       total_batches,
            'current_batch':       0,
            'imported_count':      0,
            'skipped_count':       0,
            'result_log':          False,
            'current_file_id':     first_file.id,
            'current_file_index':  0,
            'total_files':         total_files,
            'grand_imported':      0,
            'grand_skipped':       0,
            'import_visa_cache':   json.dumps(visa_cache),
            'import_source_cache': json.dumps(source_cache),
            'import_user_cache':   json.dumps(user_cache),
            'import_lost_cache':   json.dumps(lost_cache),
            'import_stage_cache':  json.dumps(stage_cache),
            'import_stage_new_id': stage_new.id if stage_new else 0,
            'import_stage_met_id': stage_met.id if stage_met else 0,
            'import_stage_svc_id': stage_svc.id if stage_svc else 0,
            'import_fallback_uid': fallback_uid,
            'import_mode_stored':  self.import_mode,
            'import_format_stored': fmt,
        })

        return {
            'type':   'ir.actions.client',
            'tag':    'jhm_import_progress',
            'target': 'new',
            'params': {
                'wizard_id':    self.id,
                'total_batches': total_batches,
                'total_rows':    total_rows,
                'total_files':   total_files,
                'file_index':    0,
                'file_name':     first_file.file_name or '',
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Process one batch of BATCH_SIZE rows (called repeatedly by JS)
    # ─────────────────────────────────────────────────────────────────────────

    def action_process_next_batch(self):
        self.ensure_one()

        if self.state == 'done':
            return {
                'state':          'done',
                'current_batch':  self.current_batch,
                'total_batches':  self.total_batches,
                'imported':       self.imported_count,
                'skipped':        self.skipped_count,
                'grand_imported': self.grand_imported,
                'grand_skipped':  self.grand_skipped,
                'log':            self.result_log or '',
                'file_index':     self.current_file_index,
                'total_files':    self.total_files,
                'file_name':      self.current_file_id.file_name if self.current_file_id else '',
            }

        # Re-parse current file to get rows (avoids storing 25 MB of JSON)
        skip = 12 if self.import_format_stored == 'vietnam' else 1
        data_rows = _parse_file(self.current_file_id.file_data, skip=skip)

        visa_cache   = json.loads(self.import_visa_cache   or '{}')
        source_cache = json.loads(self.import_source_cache or '{}')
        user_cache   = json.loads(self.import_user_cache   or '{}')
        lost_cache   = json.loads(self.import_lost_cache   or '{}')
        stage_cache  = json.loads(self.import_stage_cache  or '{}')

        stage_new_id = self.import_stage_new_id or False
        stage_met_id = self.import_stage_met_id or False
        stage_svc_id = self.import_stage_svc_id or False
        fallback_uid = self.import_fallback_uid or self.env.uid

        ctx = dict(self.env.context, **_BATCH_CTX)
        env     = self.env(context=ctx)
        CrmLead = env['crm.lead']
        is_update_mode    = (self.import_mode_stored == 'update')
        is_taiwan_format  = (self.import_format_stored == 'taiwan')
        is_vietnam_format = (self.import_format_stored == 'vietnam')
        is_hk_opp_format  = (self.import_format_stored == 'hk_opportunity')

        batch_num  = self.current_batch
        start      = batch_num * self.BATCH_SIZE
        batch_rows = data_rows[start: start + self.BATCH_SIZE]

        batch_vals_list = []
        batch_meta_list = []
        log_lines       = []
        new_skipped     = 0

        import_company_id = self.env.company.id
        for i, row in enumerate(batch_rows):
            row_num = start + i + 2   # +2: header row + 1-based
            try:
                if is_hk_opp_format:
                    vals, meta = self._parse_row_hk_opportunity(
                        env, row, fallback_uid,
                        stage_cache, user_cache, source_cache, lost_cache,
                    )
                elif is_taiwan_format:
                    vals, meta = self._parse_row_taiwan(
                        env, row, fallback_uid, stage_cache, user_cache,
                    )
                elif is_vietnam_format:
                    vals, meta = self._parse_row_vietnam(
                        env, row, fallback_uid,
                        stage_cache, user_cache, visa_cache, source_cache, lost_cache,
                    )
                else:
                    vals, meta = self._parse_row(
                        env, row, fallback_uid,
                        stage_new_id, stage_met_id, stage_svc_id,
                        visa_cache, source_cache, user_cache, lost_cache,
                    )
                vals['company_id'] = import_company_id
                batch_vals_list.append(vals)
                batch_meta_list.append(meta)
            except Exception as exc:
                new_skipped += 1
                log_lines.append(f'Row {row_num} (parse): {exc}')
                _logger.warning('JHM Import row %d parse error: %s', row_num, exc)

        new_imported = 0
        if batch_vals_list:
            sp = f'import_b{batch_num}'
            self.env.cr.execute(f'SAVEPOINT {sp}')
            try:
                if is_update_mode:
                    # ── UPDATE mode: match existing opportunity, overwrite all fields ──
                    matched_leads = []
                    matched_meta  = []
                    company_id = self.env.company.id
                    for vals, meta in zip(batch_vals_list, batch_meta_list):
                        email = meta.get('match_email')
                        phone = meta.get('match_phone')
                        if not email and not phone:
                            new_skipped += 1
                            continue
                        # Find existing opportunity by email or phone (same company only)
                        domain = [('type', '=', 'opportunity'), ('company_id', '=', company_id)]
                        if email and phone:
                            domain += ['|', ('email_from', '=', email), ('phone', '=', phone)]
                        elif email:
                            domain += [('email_from', '=', email)]
                        else:
                            domain += [('phone', '=', phone)]
                        lead = CrmLead.search(domain, limit=1)
                        if not lead:
                            new_skipped += 1
                            log_lines.append(f'No match: email={email} phone={phone}')
                            continue
                        # Write all parsed fields from vals
                        update_vals = dict(vals)
                        # Spouse fields come from meta (not in vals)
                        if meta.get('spouse_phone'):
                            update_vals['partner_spouse_phone'] = meta['spouse_phone']
                        if meta.get('spouse_email'):
                            update_vals['partner_spouse_email'] = meta['spouse_email']
                        # Remove identity/match keys that should not be written as fields
                        update_vals.pop('type', None)
                        if update_vals:
                            lead.write(update_vals)
                        matched_leads.append(lead)
                        matched_meta.append(meta)
                        new_imported += 1
                    env.flush_all()

                    # Backfill create_date if provided
                    date_updates = [
                        (meta['create_date'], lead.id)
                        for lead, meta in zip(matched_leads, matched_meta)
                        if meta.get('create_date')
                    ]
                    if date_updates:
                        self.env.cr.executemany(
                            'UPDATE crm_lead SET create_date = %s WHERE id = %s',
                            date_updates,
                        )

                    # Mark as lost (archive) if flagged
                    lost_ids = [
                        lead.id
                        for lead, meta in zip(matched_leads, matched_meta)
                        if meta.get('is_lost')
                    ]
                    if lost_ids:
                        self.env.cr.execute(
                            'UPDATE crm_lead SET active = false WHERE id = ANY(%s)',
                            [lost_ids],
                        )
                    # Restore active if no longer lost
                    restore_ids = [
                        lead.id
                        for lead, meta in zip(matched_leads, matched_meta)
                        if not meta.get('is_lost')
                    ]
                    if restore_ids:
                        self.env.cr.execute(
                            'UPDATE crm_lead SET active = true WHERE id = ANY(%s)',
                            [restore_ids],
                        )

                else:
                    # ── CREATE mode ───────────────────────────────────────────────────────
                    # Skip rows where an opportunity with same email/phone already exists in same company
                    filtered_vals = []
                    filtered_meta = []
                    company_id = self.env.company.id
                    for vals, meta in zip(batch_vals_list, batch_meta_list):
                        email = meta.get('match_email')
                        phone = meta.get('match_phone')
                        domain = [('type', '=', 'opportunity'), ('company_id', '=', company_id)]
                        if email and phone:
                            domain += ['|', ('email_from', '=', email), ('phone', '=', phone)]
                        elif email:
                            domain += [('email_from', '=', email)]
                        elif phone:
                            domain += [('phone', '=', phone)]
                        else:
                            filtered_vals.append(vals)
                            filtered_meta.append(meta)
                            continue
                        if not CrmLead.search(domain, limit=1):
                            filtered_vals.append(vals)
                            filtered_meta.append(meta)
                        else:
                            new_skipped += 1
                    batch_vals_list = filtered_vals
                    batch_meta_list = filtered_meta
                    leads = CrmLead.create(batch_vals_list)
                    env.flush_all()

                    date_updates = [
                        (meta['create_date'], lead.id)
                        for lead, meta in zip(leads, batch_meta_list)
                        if meta['create_date']
                    ]
                    if date_updates:
                        self.env.cr.executemany(
                            'UPDATE crm_lead SET create_date = %s WHERE id = %s',
                            date_updates,
                        )

                    lost_ids = [
                        lead.id
                        for lead, meta in zip(leads, batch_meta_list)
                        if meta['is_lost']
                    ]
                    if lost_ids:
                        self.env.cr.execute(
                            'UPDATE crm_lead SET active = false WHERE id = ANY(%s)',
                            [lost_ids],
                        )
                    new_imported = len(leads)

                self.env.cr.execute(f'RELEASE SAVEPOINT {sp}')
                _logger.info('JHM Import: batch %d/%d done (%d processed)',
                             batch_num + 1, self.total_batches, new_imported)

            except Exception as exc:
                self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp}')
                self.env.cr.execute(f'RELEASE SAVEPOINT {sp}')
                new_skipped += len(batch_vals_list)
                log_lines.append(f'Batch {batch_num + 1}: {exc}')
                _logger.error('JHM Import batch %d error: %s', batch_num + 1, exc, exc_info=True)

        env.invalidate_all()

        next_batch     = batch_num + 1
        total_imported = (self.imported_count or 0) + new_imported
        total_skipped  = (self.skipped_count  or 0) + new_skipped
        file_batches_done = next_batch >= self.total_batches

        # Build log text — keep running errors, summarise at end of each file
        existing_errors = [l for l in (self.result_log or '').split('\n') if l.strip()]
        all_errors      = existing_errors + log_lines
        if file_batches_done:
            log_text = (
                f'Imported: {total_imported}  |  Skipped/Errors: {total_skipped}\n' +
                ('\nErrors (first 20):\n' + '\n'.join(all_errors[:20]) if all_errors else '')
            )
        else:
            log_text = '\n'.join(all_errors[-50:])

        # ── Not done with current file yet ────────────────────────────────
        if not file_batches_done:
            self.write({
                'current_batch':  next_batch,
                'imported_count': total_imported,
                'skipped_count':  total_skipped,
                'result_log':     log_text,
            })
            return {
                'state':          'running',
                'current_batch':  next_batch,
                'total_batches':  self.total_batches,
                'imported':       total_imported,
                'skipped':        total_skipped,
                'grand_imported': (self.grand_imported or 0) + total_imported,
                'grand_skipped':  (self.grand_skipped  or 0) + total_skipped,
                'log':            '',
                'file_index':     self.current_file_index,
                'total_files':    self.total_files,
                'file_name':      self.current_file_id.file_name if self.current_file_id else '',
            }

        # ── Current file finished — save results to file record ───────────
        if self.current_file_id:
            self.current_file_id.write({
                'state':          'done',
                'imported_count': total_imported,
                'skipped_count':  total_skipped,
                'result_log':     log_text,
            })

        new_grand_imported = (self.grand_imported or 0) + total_imported
        new_grand_skipped  = (self.grand_skipped  or 0) + total_skipped

        # ── Find next pending file ────────────────────────────────────────
        next_files = self.file_ids.filtered(lambda f: f.state == 'pending').sorted('sequence')

        if next_files:
            next_file = next_files[0]
            fmt  = self.import_format_stored or 'hk'
            skip = 12 if fmt == 'vietnam' else 1
            next_data_rows = _parse_file(next_file.file_data, skip=skip)

            if not next_data_rows:
                # Empty file — mark as done and treat it as finished
                next_file.write({
                    'state': 'done', 'imported_count': 0, 'skipped_count': 0,
                    'result_log': 'No data found in file.',
                })
                # Fall through to all-done below (no more files check happens on next call)
                next_files = self.file_ids.filtered(lambda f: f.state == 'pending').sorted('sequence')

            if next_files:
                next_file = next_files[0]
                next_data_rows = _parse_file(next_file.file_data, skip=skip)

                next_total_rows    = len(next_data_rows)
                next_total_batches = max(1, math.ceil(next_total_rows / self.BATCH_SIZE))
                next_file_index    = self.current_file_index + 1

                ctx      = dict(self.env.context, **_BATCH_CTX)
                env_pre  = self.env(context=ctx)
                new_fallback_uid = self.import_fallback_uid or self.env.uid
                new_visa_cache   = {}
                new_source_cache = {}
                new_user_cache   = {}
                new_lost_cache   = {}
                new_stage_cache  = {}
                new_fallback_uid = self._run_prepass(
                    next_data_rows, fmt, env_pre, new_fallback_uid,
                    new_visa_cache, new_source_cache, new_user_cache,
                    new_lost_cache, new_stage_cache,
                )
                env_pre.flush_all()
                env_pre.invalidate_all()

                next_file.write({'state': 'running'})

                self.write({
                    'state':               'running',
                    'current_file_id':     next_file.id,
                    'current_file_index':  next_file_index,
                    'total_rows':          next_total_rows,
                    'total_batches':       next_total_batches,
                    'current_batch':       0,
                    'imported_count':      0,
                    'skipped_count':       0,
                    'result_log':          False,
                    'grand_imported':      new_grand_imported,
                    'grand_skipped':       new_grand_skipped,
                    'import_visa_cache':   json.dumps(new_visa_cache),
                    'import_source_cache': json.dumps(new_source_cache),
                    'import_user_cache':   json.dumps(new_user_cache),
                    'import_lost_cache':   json.dumps(new_lost_cache),
                    'import_stage_cache':  json.dumps(new_stage_cache),
                    'import_fallback_uid': new_fallback_uid,
                })

                _logger.info('JHM CRM Import: advancing to file %d/%d (%s)',
                             next_file_index + 1, self.total_files, next_file.file_name)
                return {
                    'state':          'running',
                    'current_batch':  0,
                    'total_batches':  next_total_batches,
                    'total_rows':     next_total_rows,
                    'imported':       0,
                    'skipped':        0,
                    'grand_imported': new_grand_imported,
                    'grand_skipped':  new_grand_skipped,
                    'log':            '',
                    'file_index':     next_file_index,
                    'total_files':    self.total_files,
                    'file_name':      next_file.file_name or '',
                }

        # ── All files done ────────────────────────────────────────────────
        self.write({
            'state':               'done',
            'current_batch':       next_batch,
            'imported_count':      total_imported,
            'skipped_count':       total_skipped,
            'result_log':          log_text,
            'grand_imported':      new_grand_imported,
            'grand_skipped':       new_grand_skipped,
            'import_visa_cache':   False,
            'import_source_cache': False,
            'import_user_cache':   False,
            'import_lost_cache':   False,
            'import_stage_cache':  False,
        })
        return {
            'state':          'done',
            'current_batch':  next_batch,
            'total_batches':  self.total_batches,
            'imported':       total_imported,
            'skipped':        total_skipped,
            'grand_imported': new_grand_imported,
            'grand_skipped':  new_grand_skipped,
            'log':            log_text,
            'file_index':     self.current_file_index,
            'total_files':    self.total_files,
            'file_name':      '',
        }
