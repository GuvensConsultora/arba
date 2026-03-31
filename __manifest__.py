{
    'name': 'arba',
    'version': '1.0',
    'summary': 'Módulo scaffold base',
    'category': 'Tools',
    'author': 'Tu Nombre',
    'website': 'https://tusitio.com',
    'depends': [
        'base', 'web', 'mail', 'account', 'sale',
        'l10n_ar_percepciones', 'account_withholding_automatic',
        'l10n_ar_report_withholding', 'l10n_ar_report_payment_group',
        'guvens_ret_gcias_iva',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ret_tax_data.xml',
        'views/view.xml',
        'views/padron_arba_view.xml',
        'views/exportcsv.xml',
        'views/exportret.xml',
        'views/res_company_view.xml',
        'data/padron.xml',
        'data/mail_template_payment_group.xml',
        'report/report_withholding_certificate.xml',
        'report/report_payment_group.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'arba/static/src/js/main.js',
            'arba/static/src/css/style.css'
        ]
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False
}
