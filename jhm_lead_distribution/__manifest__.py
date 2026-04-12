{
    'name': 'JHM Lead Distribution',
    'version': '19.0.1.0.0',
    'summary': 'Round-robin lead assignment with sticky phone/email matching',
    'category': 'CRM',
    'depends': ['crm'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_users_views.xml',
        'views/assignment_tracker_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
