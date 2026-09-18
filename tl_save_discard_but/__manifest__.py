{
    "name": "Leas Save & Discard Buttons",
    "version": "19.0.0.0.0",
    "summary": "Save & Discard Buttons",
    "license": "AGPL-3",
    "category": "Tools",
    'author': "ThoughtLogik",
    'website': "http://www.thoughtlogik.com",
    "depends": ["web"],
    "data": [],
    # "images": ["static/description/main_screen.png"],
    "assets": {
        "web.assets_backend": [
            "tl_save_discard_but/static/src/scss/indicator_button.scss",
            "tl_save_discard_but/static/src/xml/template.xml",
            ('after', 'web/static/src/search/**/*', 'odoox_web_action_bigger_button/static/src/**/*'),
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
