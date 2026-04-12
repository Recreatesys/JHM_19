{
    'name': 'JHM Partner Full Name',
    'version': '19.0.1.0.0',
    'summary': 'Split contact name into First Name and Last Name fields',
    'category': 'Technical',
    'depends': ['base', 'contacts', 'crm'],
    'data': [
        'views/res_partner_views.xml',
        'views/crm_lead_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
