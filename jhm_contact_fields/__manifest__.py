{
    'name': 'JHM Contact Fields',
    'version': '19.0.1.0.0',
    'summary': 'Custom fields for JHM contacts and CRM leads',
    'category': 'Technical',
    'depends': ['base', 'contacts', 'crm', 'documents', 'sale', 'jhm_partner_fullname'],
    'data': [
        'security/ir.model.access.csv',
        'data/jhm_data.xml',
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
        'views/daily_sales_report_wizard.xml',
        'views/sales_mtd_report.xml',
        'views/ready_to_close_report.xml',
        'views/sales_report.xml',
        'views/sales_channel_report.xml',
        'views/lead_reports.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jhm_contact_fields/static/src/css/chatter_width.css',
            'jhm_contact_fields/static/src/js/import_patch.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
