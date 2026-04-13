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


def _parse_file(file_data_b64):
    """Decode and parse the uploaded XLS-HTML file into data rows (header stripped)."""
    raw_bytes = base64.b64decode(file_data_b64)
    try:
        content = raw_bytes.decode('utf-8')
    except UnicodeDecodeError:
        content = raw_bytes.decode('latin-1')
    parser = _XlsHtmlParser()
    parser.feed(content)
    return parser.rows[1:] if parser.rows else []  # skip header


class JhmCrmImportWizard(models.TransientModel):
    _name = 'jhm.crm.import.wizard'
    _description = 'JHM CRM Lead Import Wizard'

    file_data = fields.Binary('XLS File', required=True, attachment=False)
    file_name = fields.Char('File Name')

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

    # ─────────────────────────────────────────────────────────────────────────
    # Row parser
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
    # Phase 1 — Setup: parse file, run pre-pass, store state, launch progress UI
    # ─────────────────────────────────────────────────────────────────────────

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('Please upload a file first.'))

        data_rows = _parse_file(self.file_data)
        if not data_rows:
            raise UserError(_('No data found in the file.'))

        total_rows    = len(data_rows)
        total_batches = max(1, math.ceil(total_rows / self.BATCH_SIZE))
        _logger.info('JHM CRM Import: %d rows → %d batches of %d',
                     total_rows, total_batches, self.BATCH_SIZE)

        env = self.env.with_context(_BATCH_CTX)

        fallback_user = env['res.users'].search(
            [('name', '=ilike', 'Stephano'), ('share', '=', False)], limit=1
        )
        fallback_uid = fallback_user.id if fallback_user else self.env.uid

        stage_new     = env['crm.stage'].search([('name', 'ilike', 'New Lead')], limit=1)
        stage_met     = env['crm.stage'].search([('name', 'ilike', 'Met & Follow Up')], limit=1)
        stage_svc     = env['crm.stage'].search([('name', 'ilike', 'Service Agreement')], limit=1)

        visa_cache   = {}
        source_cache = {}
        user_cache   = {}
        lost_cache   = {}

        for row in data_rows:
            row = list(row) + [''] * max(0, 28 - len(row))

            def _c(r, i):
                try:
                    return (r[i] or '').strip()
                except IndexError:
                    return ''

            self._get_or_create_visa_program(env, visa_cache,   _c(row, COL_INDUSTRY))
            self._get_or_create_visa_program(env, visa_cache,   _c(row, COL_PREV_INDUSTRY))
            self._get_or_create_lead_source(env, source_cache,  _c(row, COL_LEAD_SOURCE))
            parts = [p.strip() for p in _c(row, COL_JHM_LEAD_OWNER).split(';') if p.strip()]
            if parts:
                self._get_user(env, user_cache, parts[0], fallback_uid)
            for part in parts[1:]:
                self._get_user(env, user_cache, part, None)
            if _c(row, COL_LEAD_STATUS).strip().lower() == 'unqualified':
                self._get_lost_reason(env, lost_cache, 'Unqualified')

        env.flush_all()
        env.invalidate_all()

        _logger.info('JHM CRM Import pre-pass done: %d visa, %d sources, %d users',
                     len(visa_cache), len(source_cache), len(user_cache))

        self.write({
            'state':              'running',
            'total_rows':         total_rows,
            'total_batches':      total_batches,
            'current_batch':      0,
            'imported_count':     0,
            'skipped_count':      0,
            'result_log':         False,
            'import_visa_cache':   json.dumps(visa_cache),
            'import_source_cache': json.dumps(source_cache),
            'import_user_cache':   json.dumps(user_cache),
            'import_lost_cache':   json.dumps(lost_cache),
            'import_stage_new_id': stage_new.id if stage_new else 0,
            'import_stage_met_id': stage_met.id if stage_met else 0,
            'import_stage_svc_id': stage_svc.id if stage_svc else 0,
            'import_fallback_uid': fallback_uid,
        })

        return {
            'type':   'ir.actions.client',
            'tag':    'jhm_import_progress',
            'target': 'new',
            'params': {
                'wizard_id':    self.id,
                'total_batches': total_batches,
                'total_rows':    total_rows,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Process one batch of BATCH_SIZE rows (called repeatedly by JS)
    # ─────────────────────────────────────────────────────────────────────────

    def action_process_next_batch(self):
        self.ensure_one()

        if self.state == 'done':
            return {
                'state':         'done',
                'current_batch': self.current_batch,
                'total_batches': self.total_batches,
                'imported':      self.imported_count,
                'skipped':       self.skipped_count,
                'log':           self.result_log or '',
            }

        # Re-parse file to get rows (fast; avoids storing 25 MB of JSON)
        data_rows = _parse_file(self.file_data)

        visa_cache   = json.loads(self.import_visa_cache   or '{}')
        source_cache = json.loads(self.import_source_cache or '{}')
        user_cache   = json.loads(self.import_user_cache   or '{}')
        lost_cache   = json.loads(self.import_lost_cache   or '{}')

        stage_new_id = self.import_stage_new_id or False
        stage_met_id = self.import_stage_met_id or False
        stage_svc_id = self.import_stage_svc_id or False
        fallback_uid = self.import_fallback_uid or self.env.uid

        env     = self.env.with_context(_BATCH_CTX)
        CrmLead = env['crm.lead']

        batch_num  = self.current_batch
        start      = batch_num * self.BATCH_SIZE
        batch_rows = data_rows[start: start + self.BATCH_SIZE]

        batch_vals_list = []
        batch_meta_list = []
        log_lines       = []
        new_skipped     = 0

        for i, row in enumerate(batch_rows):
            row_num = start + i + 2   # +2: header row + 1-based
            try:
                vals, meta = self._parse_row(
                    env, row, fallback_uid,
                    stage_new_id, stage_met_id, stage_svc_id,
                    visa_cache, source_cache, user_cache, lost_cache,
                )
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

                self.env.cr.execute(f'RELEASE SAVEPOINT {sp}')
                new_imported = len(leads)
                _logger.info('JHM Import: batch %d/%d done (%d created)',
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
        is_done        = next_batch >= self.total_batches

        # Build log text — keep running errors, summarise at the end
        existing_errors = [l for l in (self.result_log or '').split('\n') if l.strip()]
        all_errors      = existing_errors + log_lines
        if is_done:
            log_text = (
                f'Imported: {total_imported}  |  Skipped/Errors: {total_skipped}\n' +
                ('\nErrors (first 20):\n' + '\n'.join(all_errors[:20]) if all_errors else '')
            )
        else:
            log_text = '\n'.join(all_errors[-50:])   # keep last 50 error lines while running

        write_vals = {
            'current_batch': next_batch,
            'imported_count': total_imported,
            'skipped_count':  total_skipped,
            'result_log':     log_text,
            'state':          'done' if is_done else 'running',
        }
        if is_done:
            # Free the large cache fields
            write_vals.update({
                'import_visa_cache':   False,
                'import_source_cache': False,
                'import_user_cache':   False,
                'import_lost_cache':   False,
            })
        self.write(write_vals)

        return {
            'state':         'done' if is_done else 'running',
            'current_batch': next_batch,
            'total_batches': self.total_batches,
            'imported':      total_imported,
            'skipped':       total_skipped,
            'log':           log_text if is_done else '',
        }
