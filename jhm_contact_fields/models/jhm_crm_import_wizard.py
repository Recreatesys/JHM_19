# -*- coding: utf-8 -*-
import base64
import logging
import re
from datetime import datetime
from html.parser import HTMLParser

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ── Column indices in the source file ─────────────────────────────────────────
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
COL_OCC_VISA_STATE      = 21
COL_APPOINTMENT_DATE    = 22
COL_APPOINTMENT_NOTES   = 23
COL_LAST_CALL_DATE      = 24
COL_FOLLOWUP_DATE       = 25
COL_CHAT_LOG            = 26
COL_PAID                = 27

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
    # Round to nearest valid
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
    # partial match
    if '2' in key and '3' in key:
        return '2_3month'
    if '1' in key:
        return '1month'
    return 'tbd'


class JhmCrmImportWizard(models.TransientModel):
    _name = 'jhm.crm.import.wizard'
    _description = 'JHM CRM Lead Import Wizard'

    file_data = fields.Binary('XLS File', required=True, attachment=False)
    file_name = fields.Char('File Name')

    # ── Result fields (populated after import) ───────────────────────────────
    state = fields.Selection([
        ('draft', 'Ready'),
        ('done', 'Done'),
    ], default='draft')
    imported_count = fields.Integer('Imported', readonly=True)
    skipped_count  = fields.Integer('Skipped / Errors', readonly=True)
    result_log     = fields.Text('Import Log', readonly=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Lookup helpers (cached per wizard invocation)
    # ─────────────────────────────────────────────────────────────────────────

    # ── Lookup helpers — accept explicit env so they work with any cursor ────

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
        rec = env['res.users'].search([
            ('name', 'ilike', name.strip()),
            ('share', '=', False),
        ], limit=1)
        uid = rec.id if rec else fallback_id
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

    # ─────────────────────────────────────────────────────────────────────────
    # Row parser — returns (vals_dict, meta_dict) or raises
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_row(self, env, row, fallback_uid,
                   stage_new_lead_id, stage_met_followup_id, stage_service_agr_id,
                   visa_cache, source_cache, user_cache, lost_cache):

        row = list(row) + [''] * max(0, 28 - len(row))

        def c(idx):
            try:
                return (row[idx] or '').strip()
            except IndexError:
                return ''

        # ── Contact / lead name ───────────────────────────────────────────
        first = c(COL_FIRST_NAME)
        last  = c(COL_LAST_NAME)
        contact_name = ' '.join(filter(None, [first, last])) or 'Unknown'

        # ── Salesperson / co-owners ───────────────────────────────────────
        jhm_owner_raw = c(COL_JHM_LEAD_OWNER)
        owner_parts   = [p.strip() for p in jhm_owner_raw.split(';') if p.strip()]
        primary_user_id = self._get_user(env, user_cache, owner_parts[0] if owner_parts else '', fallback_uid)
        co_owner_ids    = []
        for extra in owner_parts[1:]:
            uid = self._get_user(env, user_cache, extra, None)
            if uid:
                co_owner_ids.append(uid)

        # ── Lead Source ────────────────────────────────────────────────────
        lead_source_id = self._get_or_create_lead_source(env, source_cache, c(COL_LEAD_SOURCE))

        # ── Email / phone ─────────────────────────────────────────────────
        email = c(COL_MAIN_EMAIL) or c(COL_EMAIL)

        # ── Gender ────────────────────────────────────────────────────────
        gender = _norm_gender(c(COL_GENDER))

        # ── Probability ───────────────────────────────────────────────────
        prob_str = _norm_probability(c(COL_PROBABILITY))

        # ── Time to close ─────────────────────────────────────────────────
        ttc = _norm_ttc(c(COL_TIME_TO_CLOSE))

        # ── Dates ─────────────────────────────────────────────────────────
        create_date_val  = _parse_date(c(COL_CREATE_DATE))
        appointment_date = _parse_date(c(COL_APPOINTMENT_DATE))
        last_call_date   = _parse_date(c(COL_LAST_CALL_DATE))
        followup_date    = _parse_date(c(COL_FOLLOWUP_DATE))

        # ── Visa programs ─────────────────────────────────────────────────
        visa_id      = self._get_or_create_visa_program(env, visa_cache, c(COL_INDUSTRY))
        prev_visa_id = self._get_or_create_visa_program(env, visa_cache, c(COL_PREV_INDUSTRY))

        # ── Free-text immigration ──────────────────────────────────────────
        immigration_country = c(COL_OCC_VISA_STATE)

        # ── Description ───────────────────────────────────────────────────
        jhm_desc = '\n\n'.join(filter(None, [c(COL_QUESTION_COMMENTS), c(COL_DESCRIPTION)])) or False

        # ── Stage / lost ───────────────────────────────────────────────────
        lead_status = c(COL_LEAD_STATUS).strip().lower()
        is_lost  = False
        stage_id = stage_new_lead_id  # default

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

        # ── Build vals ─────────────────────────────────────────────────────
        vals = {
            'name':                              contact_name,
            'contact_name':                      contact_name,
            'type':                              'opportunity',
            'email_from':                        email or False,
            'phone':                             c(COL_MAIN_MOBILE) or False,
            'user_id':                           primary_user_id,
            'active':                            True,   # set False via SQL after flush
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

        meta = {
            'create_date': create_date_val,
            'is_lost':     is_lost,
        }
        return vals, meta

    # ─────────────────────────────────────────────────────────────────────────
    # Main import action
    # ─────────────────────────────────────────────────────────────────────────

    BATCH_SIZE = 500

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('Please upload a file first.'))

        raw_bytes = base64.b64decode(self.file_data)
        try:
            content = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            content = raw_bytes.decode('latin-1')

        parser = _XlsHtmlParser()
        parser.feed(content)
        all_rows = parser.rows

        if not all_rows:
            raise UserError(_('No data found in the file.'))

        data_rows = all_rows[1:]  # skip header
        _logger.info('JHM CRM Import: %d data rows to process', len(data_rows))

        uid       = self.env.uid
        wizard_id = self.id
        registry  = self.env.registry

        # ── One-time lookups using the request cursor (read-only, no commit) ─
        fallback_user = self.env['res.users'].search(
            [('name', 'ilike', 'Stephano'), ('share', '=', False)], limit=1
        )
        fallback_uid = fallback_user.id if fallback_user else uid

        stage_new_lead     = self.env['crm.stage'].search([('name', 'ilike', 'New Lead')], limit=1)
        stage_met_followup = self.env['crm.stage'].search([('name', 'ilike', 'Met & Follow Up')], limit=1)
        stage_service_agr  = self.env['crm.stage'].search([('name', 'ilike', 'Service Agreement')], limit=1)

        stage_new_id = stage_new_lead.id if stage_new_lead else False
        stage_met_id = stage_met_followup.id if stage_met_followup else False
        stage_svc_id = stage_service_agr.id if stage_service_agr else False

        # Caches shared across all batches (keyed by lowercase name → DB id)
        visa_cache   = {}
        source_cache = {}
        user_cache   = {}
        lost_cache   = {}

        # ── Pre-pass: create all lookup records in one committed transaction ─
        # Using a separate cursor so the main request cursor is never committed.
        with registry.cursor() as pre_cr:
            pre_env = api.Environment(pre_cr, uid, {})
            for row in data_rows:
                row = list(row) + [''] * max(0, 28 - len(row))
                def _c(r, i):
                    try:
                        return (r[i] or '').strip()
                    except IndexError:
                        return ''
                self._get_or_create_visa_program(pre_env, visa_cache, _c(row, COL_INDUSTRY))
                self._get_or_create_visa_program(pre_env, visa_cache, _c(row, COL_PREV_INDUSTRY))
                self._get_or_create_lead_source(pre_env, source_cache, _c(row, COL_LEAD_SOURCE))
                if _c(row, COL_LEAD_STATUS).strip().lower() == 'unqualified':
                    self._get_lost_reason(pre_env, lost_cache, 'Unqualified')
            pre_cr.commit()

        _logger.info('JHM CRM Import pre-pass done: %d visa, %d sources',
                     len(visa_cache), len(source_cache))

        imported  = 0
        skipped   = 0
        log_lines = []

        _BATCH_CTX = {
            'tracking_disable':       True,
            'mail_notrack':           True,
            'mail_create_nosubscribe': True,
            'jhm_import':             True,
        }

        # ── Process each batch in its own independent cursor/transaction ─────
        for batch_start in range(0, len(data_rows), self.BATCH_SIZE):
            batch = data_rows[batch_start: batch_start + self.BATCH_SIZE]
            batch_vals_list = []
            batch_meta_list = []

            # Parse rows using a temporary env for user lookups (read-only DB hits)
            with registry.cursor() as parse_cr:
                parse_env = api.Environment(parse_cr, uid, _BATCH_CTX)
                for i, row in enumerate(batch):
                    row_num = batch_start + i + 2
                    try:
                        vals, meta = self._parse_row(
                            parse_env, row, fallback_uid,
                            stage_new_id, stage_met_id, stage_svc_id,
                            visa_cache, source_cache, user_cache, lost_cache,
                        )
                        batch_vals_list.append(vals)
                        batch_meta_list.append(meta)
                    except Exception as exc:
                        skipped += 1
                        msg = f'Row {row_num} (parse): {exc}'
                        log_lines.append(msg)
                        _logger.warning('JHM CRM Import - %s', msg, exc_info=True)
                # parse_cr is read-only — no commit needed, auto-closes

            if not batch_vals_list:
                continue

            # Create leads in a fresh cursor/transaction
            with registry.cursor() as cr:
                try:
                    env = api.Environment(cr, uid, _BATCH_CTX)
                    leads = env['crm.lead'].create(batch_vals_list)
                    env.flush_all()

                    # Backdate create_date
                    date_updates = [
                        (meta['create_date'], lead.id)
                        for lead, meta in zip(leads, batch_meta_list)
                        if meta['create_date']
                    ]
                    if date_updates:
                        cr.executemany(
                            'UPDATE crm_lead SET create_date = %s WHERE id = %s',
                            date_updates,
                        )

                    # Mark lost leads
                    lost_ids = [
                        lead.id
                        for lead, meta in zip(leads, batch_meta_list)
                        if meta['is_lost']
                    ]
                    if lost_ids:
                        cr.execute(
                            'UPDATE crm_lead SET active = false WHERE id = ANY(%s)',
                            [lost_ids],
                        )

                    cr.commit()
                    imported += len(leads)
                    _logger.info('JHM CRM Import batch %d–%d: %d created',
                                 batch_start + 2, batch_start + len(batch_vals_list) + 1,
                                 len(leads))

                except Exception as exc:
                    cr.rollback()
                    skipped += len(batch_vals_list)
                    msg = (f'Batch rows {batch_start + 2}–'
                           f'{batch_start + len(batch_vals_list) + 1}: {exc}')
                    log_lines.append(msg)
                    _logger.error('JHM CRM Import - %s', msg, exc_info=True)

        # ── Write results back via the main request cursor ────────────────────
        log_summary = f'Imported: {imported}  |  Skipped/Errors: {skipped}\n'
        if log_lines:
            log_summary += '\nErrors (first 20):\n' + '\n'.join(log_lines[:20])

        self.write({
            'state':          'done',
            'imported_count': imported,
            'skipped_count':  skipped,
            'result_log':     log_summary,
        })

        return {
            'type':      'ir.actions.act_window',
            'res_model': 'jhm.crm.import.wizard',
            'res_id':    wizard_id,
            'view_mode': 'form',
            'target':    'new',
        }
