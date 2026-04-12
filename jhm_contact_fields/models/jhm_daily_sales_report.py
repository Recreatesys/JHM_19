from odoo import fields, models


class JhmSalesDailyLine(models.Model):
    """SQL view model backing the CRM Daily Sales pivot report.

    Each row = one (salesperson, date) pair with all daily metrics.
    The pivot groups by user_id (rows) and date (columns), with every
    metric as a selectable measure.
    """
    _name = 'jhm.sales.daily.line'
    _description = 'JHM Daily Sales Report Line'
    _auto = False          # backed by a SQL view, not a real table
    _rec_name = 'user_id'
    _order = 'date desc, user_id'

    user_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    date = fields.Date(string='Date', readonly=True)

    new_leads = fields.Integer(string='# New Leads', readonly=True)
    existing_leads = fields.Integer(string='# Existing Leads', readonly=True)
    existing_leads_lt50 = fields.Integer(string='# Existing Leads (<50%)', readonly=True)
    total_calls = fields.Integer(string='Total Call', readonly=True)
    support_count = fields.Integer(string='# Support (Manager/Consultant)', readonly=True)
    appointment_count = fields.Integer(string='# Appointment', readonly=True)
    daily_sales = fields.Float(string='$ Daily Sales', readonly=True, digits=(16, 2))

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_sales_daily_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_sales_daily_line AS
            WITH

            -- All (user_id, date) pairs that have any activity
            salesperson_dates AS (
                SELECT user_id, DATE(create_date AT TIME ZONE 'UTC') AS d
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL

                UNION

                SELECT cl.user_id, DATE(mm.date AT TIME ZONE 'UTC') AS d
                FROM mail_message mm
                JOIN mail_tracking_value mtv ON mtv.mail_message_id = mm.id
                JOIN crm_lead cl
                    ON cl.id = mm.res_id
                   AND cl.type = 'opportunity'
                   AND cl.user_id IS NOT NULL
                JOIN res_users ru ON ru.partner_id = mm.author_id AND ru.id = cl.user_id
                WHERE mm.model = 'crm.lead'
                  AND mtv.field_id IN (
                      SELECT imf.id FROM ir_model_fields imf
                      JOIN ir_model im ON im.id = imf.model_id
                      WHERE imf.name = 'partner_last_call_date' AND im.model = 'crm.lead'
                  )

                UNION

                SELECT lead_user_id AS user_id, log_date AS d
                FROM jhm_co_owner_log
                WHERE lead_user_id IS NOT NULL

                UNION

                SELECT user_id, partner_appointment_date AS d
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND partner_appointment_date IS NOT NULL
            ),

            -- New leads created on each date
            new_leads_agg AS (
                SELECT user_id, DATE(create_date AT TIME ZONE 'UTC') AS d, COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity' AND user_id IS NOT NULL
                GROUP BY 1, 2
            ),

            -- Snapshot: current active lead counts per salesperson
            existing_leads_agg AS (
                SELECT
                    user_id,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE probability < 50) AS lt50
                FROM crm_lead
                WHERE type = 'opportunity' AND active = true AND user_id IS NOT NULL
                GROUP BY 1
            ),

            -- Calls: salesperson updated last_call_date on their own leads
            calls_agg AS (
                SELECT cl.user_id, DATE(mm.date AT TIME ZONE 'UTC') AS d, COUNT(*) AS cnt
                FROM mail_message mm
                JOIN mail_tracking_value mtv ON mtv.mail_message_id = mm.id
                JOIN crm_lead cl
                    ON cl.id = mm.res_id
                   AND cl.type = 'opportunity'
                JOIN res_users ru ON ru.partner_id = mm.author_id AND ru.id = cl.user_id
                WHERE mm.model = 'crm.lead'
                  AND mtv.field_id IN (
                      SELECT imf.id FROM ir_model_fields imf
                      JOIN ir_model im ON im.id = imf.model_id
                      WHERE imf.name = 'partner_last_call_date' AND im.model = 'crm.lead'
                  )
                GROUP BY 1, 2
            ),

            -- Support: co-owner additions logged per salesperson per day
            support_agg AS (
                SELECT lead_user_id AS user_id, log_date AS d, SUM(added_count) AS cnt
                FROM jhm_co_owner_log
                WHERE lead_user_id IS NOT NULL
                GROUP BY 1, 2
            ),

            -- Appointments: leads whose appointment_date falls on each date
            appt_agg AS (
                SELECT user_id, partner_appointment_date AS d, COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND partner_appointment_date IS NOT NULL
                GROUP BY 1, 2
            ),

            -- Daily invoiced sales via sale order → invoice chain
            sales_agg AS (
                SELECT cl.user_id, am.invoice_date AS d,
                       SUM(am.amount_untaxed_signed) AS amt
                FROM account_move am
                JOIN account_move_line aml ON aml.move_id = am.id
                JOIN sale_order_line_invoice_rel sir ON sir.invoice_line_id = aml.id
                JOIN sale_order_line sol ON sol.id = sir.order_line_id
                JOIN sale_order so ON so.id = sol.order_id
                JOIN crm_lead cl
                    ON cl.id = so.opportunity_id
                   AND cl.user_id IS NOT NULL
                WHERE am.state = 'posted'
                  AND am.move_type IN ('out_invoice', 'out_refund')
                  AND am.invoice_date IS NOT NULL
                GROUP BY 1, 2
            )

            SELECT
                row_number() OVER () AS id,
                sd.user_id,
                sd.d                        AS date,
                COALESCE(nl.cnt,   0)       AS new_leads,
                COALESCE(el.total, 0)       AS existing_leads,
                COALESCE(el.lt50,  0)       AS existing_leads_lt50,
                COALESCE(ca.cnt,   0)       AS total_calls,
                COALESCE(su.cnt,   0)       AS support_count,
                COALESCE(ap.cnt,   0)       AS appointment_count,
                COALESCE(sa.amt,   0.0)     AS daily_sales
            FROM salesperson_dates sd
            LEFT JOIN new_leads_agg    nl ON nl.user_id = sd.user_id AND nl.d = sd.d
            LEFT JOIN existing_leads_agg el ON el.user_id = sd.user_id
            LEFT JOIN calls_agg        ca ON ca.user_id = sd.user_id AND ca.d = sd.d
            LEFT JOIN support_agg      su ON su.user_id = sd.user_id AND su.d = sd.d
            LEFT JOIN appt_agg         ap ON ap.user_id = sd.user_id AND ap.d = sd.d
            LEFT JOIN sales_agg        sa ON sa.user_id = sd.user_id AND sa.d = sd.d
        """)
