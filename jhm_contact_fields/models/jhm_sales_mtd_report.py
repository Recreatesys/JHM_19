import math
from odoo import api, fields, models


class JhmSalesMtdLine(models.Model):
    """SQL view: one row per (salesperson × period).
    Two periods: 'Current Month' and 'Previous'.

    Current Month:
      - New Leads:       created in current month
      - Qualified Leads: created in current month, probability >= 50%
      - Appointment:     created in current month, appointment_date in current month
      - Sales #/$:       sale orders in current month from leads created in current month

    Previous:
      - New Leads:       created in previous month (one month before)
      - Qualified Leads: created BEFORE current month, probability >= 50%,
                         updated (write_date) in current month
      - Appointment:     created BEFORE current month, appointment_date in current month
      - Sales #/$:       sale orders in current month from leads created BEFORE current month
    """
    _name = 'jhm.sales.mtd.line'
    _description = 'Sales Report (MTD)'
    _auto = False
    _rec_name = 'user_id'
    _order = 'period, user_id'

    user_id          = fields.Many2one('res.users',       string='Salesperson',  readonly=True)
    period           = fields.Char(string='Period', readonly=True)

    new_leads           = fields.Integer(string='New Leads',              readonly=True)
    qualified_leads     = fields.Integer(string='Qualified Leads',        readonly=True)
    qualified_pct       = fields.Integer(string='% Qualified',            readonly=True, aggregator='avg')
    appointments        = fields.Integer(string='Appointment',            readonly=True)
    appointment_pct     = fields.Integer(string='% Appointment',          readonly=True, aggregator='avg')
    sales_count         = fields.Integer(string='Sales #',                readonly=True)
    sales_pct           = fields.Integer(string='% Sales',                readonly=True, aggregator='avg')
    sales_amount        = fields.Float(string='Sales $',                  readonly=True, digits=(16, 2))

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_sales_mtd_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_sales_mtd_line AS
            WITH
            cur_month AS (
                SELECT date_trunc('month', now() AT TIME ZONE 'UTC')::date AS m
            ),

            -- ═══════════════════════════════════════════════════════════
            -- CURRENT MONTH
            -- ═══════════════════════════════════════════════════════════

            -- New Leads: created in current month AND last call date in current month
            c_nl AS (
                SELECT user_id, COUNT(*) AS cnt
                FROM crm_lead, cur_month
                WHERE type = 'opportunity' AND active = true
                  AND user_id IS NOT NULL
                  AND date_trunc('month', create_date AT TIME ZONE 'UTC')::date = cur_month.m
                  AND partner_last_call_date IS NOT NULL
                  AND date_trunc('month', partner_last_call_date)::date = cur_month.m
                GROUP BY user_id
            ),
            -- Qualified: created in current month, last call date in current month, prob >= 50
            c_ql AS (
                SELECT user_id, COUNT(*) AS cnt
                FROM crm_lead, cur_month
                WHERE type = 'opportunity' AND active = true
                  AND user_id IS NOT NULL
                  AND date_trunc('month', create_date AT TIME ZONE 'UTC')::date = cur_month.m
                  AND partner_last_call_date IS NOT NULL
                  AND date_trunc('month', partner_last_call_date)::date = cur_month.m
                  AND probability >= 50
                GROUP BY user_id
            ),
            -- Appointment: created in current month, appointment_date in current month
            c_ap AS (
                SELECT user_id, COUNT(*) AS cnt
                FROM crm_lead, cur_month
                WHERE type = 'opportunity' AND active = true
                  AND user_id IS NOT NULL
                  AND date_trunc('month', create_date AT TIME ZONE 'UTC')::date = cur_month.m
                  AND partner_appointment_date IS NOT NULL
                  AND date_trunc('month', partner_appointment_date)::date = cur_month.m
                GROUP BY user_id
            ),
            -- Sales: leads created in current month that have
            --   1st Payment > 0 OR a paid/in_payment invoice
            --   Sales $ = 1st Payment + first paid invoice amount
            c_inv AS (
                SELECT cl.id AS lead_id,
                       MIN(am.amount_untaxed) AS inv_amt
                FROM crm_lead cl
                JOIN sale_order so ON so.opportunity_id = cl.id AND so.state NOT IN ('cancel')
                JOIN sale_order_line sol ON sol.order_id = so.id
                JOIN sale_order_line_invoice_rel rel ON rel.order_line_id = sol.id
                JOIN account_move_line aml ON aml.id = rel.invoice_line_id
                JOIN account_move am ON am.id = aml.move_id
                    AND am.move_type = 'out_invoice'
                    AND am.payment_state IN ('paid', 'in_payment')
                CROSS JOIN cur_month
                WHERE cl.type = 'opportunity' AND cl.active = true
                  AND cl.user_id IS NOT NULL
                  AND date_trunc('month', cl.create_date AT TIME ZONE 'UTC')::date = cur_month.m
                GROUP BY cl.id
            ),
            c_so AS (
                SELECT cl.user_id,
                       COUNT(DISTINCT cl.id) AS cnt,
                       SUM(COALESCE(cl.sale_payment_1, 0) + COALESCE(c_inv.inv_amt, 0)) AS amt
                FROM crm_lead cl
                CROSS JOIN cur_month
                LEFT JOIN c_inv ON c_inv.lead_id = cl.id
                WHERE cl.type = 'opportunity' AND cl.active = true
                  AND cl.user_id IS NOT NULL
                  AND date_trunc('month', cl.create_date AT TIME ZONE 'UTC')::date = cur_month.m
                  AND (COALESCE(cl.sale_payment_1, 0) > 0 OR c_inv.inv_amt IS NOT NULL)
                GROUP BY cl.user_id
            ),

            -- ═══════════════════════════════════════════════════════════
            -- PREVIOUS
            -- ═══════════════════════════════════════════════════════════

            -- New Leads: created before current month AND last call date in current month
            p_nl AS (
                SELECT user_id, COUNT(*) AS cnt
                FROM crm_lead, cur_month
                WHERE type = 'opportunity' AND active = true
                  AND user_id IS NOT NULL
                  AND date_trunc('month', create_date AT TIME ZONE 'UTC')::date < cur_month.m
                  AND partner_last_call_date IS NOT NULL
                  AND date_trunc('month', partner_last_call_date)::date = cur_month.m
                GROUP BY user_id
            ),
            -- Qualified: created BEFORE current month, last call date in current month, prob >= 50
            p_ql AS (
                SELECT user_id, COUNT(*) AS cnt
                FROM crm_lead, cur_month
                WHERE type = 'opportunity' AND active = true
                  AND user_id IS NOT NULL
                  AND date_trunc('month', create_date AT TIME ZONE 'UTC')::date < cur_month.m
                  AND partner_last_call_date IS NOT NULL
                  AND date_trunc('month', partner_last_call_date)::date = cur_month.m
                  AND probability >= 50
                GROUP BY user_id
            ),
            -- Appointment: created BEFORE current month, appointment_date in current month
            p_ap AS (
                SELECT user_id, COUNT(*) AS cnt
                FROM crm_lead, cur_month
                WHERE type = 'opportunity' AND active = true
                  AND user_id IS NOT NULL
                  AND date_trunc('month', create_date AT TIME ZONE 'UTC')::date < cur_month.m
                  AND partner_appointment_date IS NOT NULL
                  AND date_trunc('month', partner_appointment_date)::date = cur_month.m
                GROUP BY user_id
            ),
            -- Sales: leads created BEFORE current month where
            --   invoice date is in current month OR 1st payment date is in current month
            p_inv AS (
                SELECT cl.id AS lead_id,
                       MIN(am.amount_untaxed) AS inv_amt
                FROM crm_lead cl
                JOIN sale_order so ON so.opportunity_id = cl.id AND so.state NOT IN ('cancel')
                JOIN sale_order_line sol ON sol.order_id = so.id
                JOIN sale_order_line_invoice_rel rel ON rel.order_line_id = sol.id
                JOIN account_move_line aml ON aml.id = rel.invoice_line_id
                JOIN account_move am ON am.id = aml.move_id
                    AND am.move_type = 'out_invoice'
                    AND am.payment_state IN ('paid', 'in_payment')
                CROSS JOIN cur_month
                WHERE cl.type = 'opportunity' AND cl.active = true
                  AND cl.user_id IS NOT NULL
                  AND date_trunc('month', cl.create_date AT TIME ZONE 'UTC')::date < cur_month.m
                  AND date_trunc('month', am.invoice_date)::date = cur_month.m
                GROUP BY cl.id
            ),
            -- 1st Payment: only if payment date is in current month
            p_pay AS (
                SELECT cl.id AS lead_id, cl.user_id, cl.sale_payment_1 AS pay_amt
                FROM crm_lead cl
                CROSS JOIN cur_month
                WHERE cl.type = 'opportunity' AND cl.active = true
                  AND cl.user_id IS NOT NULL
                  AND date_trunc('month', cl.create_date AT TIME ZONE 'UTC')::date < cur_month.m
                  AND COALESCE(cl.sale_payment_1, 0) > 0
                  AND cl.sale_payment_date_1 IS NOT NULL
                  AND date_trunc('month', cl.sale_payment_date_1)::date = cur_month.m
            ),
            p_so AS (
                SELECT COALESCE(p_pay.user_id, cl.user_id) AS user_id,
                       COUNT(DISTINCT COALESCE(p_pay.lead_id, cl.id)) AS cnt,
                       SUM(COALESCE(p_pay.pay_amt, 0) + COALESCE(p_inv.inv_amt, 0)) AS amt
                FROM (
                    SELECT lead_id FROM p_inv
                    UNION
                    SELECT lead_id FROM p_pay
                ) all_leads
                LEFT JOIN p_inv ON p_inv.lead_id = all_leads.lead_id
                LEFT JOIN p_pay ON p_pay.lead_id = all_leads.lead_id
                LEFT JOIN crm_lead cl ON cl.id = all_leads.lead_id
                GROUP BY COALESCE(p_pay.user_id, cl.user_id)
            ),

            -- ═══════════════════════════════════════════════════════════
            -- Combine all users
            -- ═══════════════════════════════════════════════════════════
            all_users AS (
                SELECT user_id FROM c_nl
                UNION SELECT user_id FROM p_nl
                UNION SELECT user_id FROM c_ql
                UNION SELECT user_id FROM p_ql
            )

            -- Current Month rows
            SELECT
                row_number() OVER () AS id,
                u.user_id,
                'Current Month'::text AS period,
                COALESCE(c_nl.cnt, 0) AS new_leads,
                COALESCE(c_ql.cnt, 0) AS qualified_leads,
                CASE WHEN COALESCE(c_nl.cnt, 0) > 0
                     THEN CEIL(COALESCE(c_ql.cnt, 0)::numeric / c_nl.cnt * 100)::int
                     ELSE 0 END AS qualified_pct,
                COALESCE(c_ap.cnt, 0) AS appointments,
                CASE WHEN COALESCE(c_nl.cnt, 0) > 0
                     THEN CEIL(COALESCE(c_ap.cnt, 0)::numeric / c_nl.cnt * 100)::int
                     ELSE 0 END AS appointment_pct,
                COALESCE(c_so.cnt, 0) AS sales_count,
                CASE WHEN COALESCE(c_ql.cnt, 0) > 0
                     THEN CEIL(COALESCE(c_so.cnt, 0)::numeric / c_ql.cnt * 100)::int
                     ELSE 0 END AS sales_pct,
                COALESCE(c_so.amt, 0.0) AS sales_amount
            FROM all_users u
            LEFT JOIN c_nl ON c_nl.user_id = u.user_id
            LEFT JOIN c_ql ON c_ql.user_id = u.user_id
            LEFT JOIN c_ap ON c_ap.user_id = u.user_id
            LEFT JOIN c_so ON c_so.user_id = u.user_id

            UNION ALL

            -- Previous rows
            SELECT
                (SELECT COUNT(*) FROM all_users) + row_number() OVER () AS id,
                u.user_id,
                'Previous'::text AS period,
                COALESCE(p_nl.cnt, 0) AS new_leads,
                COALESCE(p_ql.cnt, 0) AS qualified_leads,
                CASE WHEN COALESCE(p_nl.cnt, 0) > 0
                     THEN CEIL(COALESCE(p_ql.cnt, 0)::numeric / p_nl.cnt * 100)::int
                     ELSE 0 END AS qualified_pct,
                COALESCE(p_ap.cnt, 0) AS appointments,
                CASE WHEN COALESCE(p_nl.cnt, 0) > 0
                     THEN CEIL(COALESCE(p_ap.cnt, 0)::numeric / p_nl.cnt * 100)::int
                     ELSE 0 END AS appointment_pct,
                COALESCE(p_so.cnt, 0) AS sales_count,
                CASE WHEN COALESCE(p_ql.cnt, 0) > 0
                     THEN CEIL(COALESCE(p_so.cnt, 0)::numeric / p_ql.cnt * 100)::int
                     ELSE 0 END AS sales_pct,
                COALESCE(p_so.amt, 0.0) AS sales_amount
            FROM all_users u
            LEFT JOIN p_nl ON p_nl.user_id = u.user_id
            LEFT JOIN p_ql ON p_ql.user_id = u.user_id
            LEFT JOIN p_ap ON p_ap.user_id = u.user_id
            LEFT JOIN p_so ON p_so.user_id = u.user_id
        """)
