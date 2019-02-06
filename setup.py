from setuptools import setup

setup(
    name='reader-beware',
    version='0.1',
    py_modules=['beware'],
    install_requires=[
        'click',
        'jinja2',
        'pyyaml',
        'markdown2',
    ],
    entry_points='''
        [console_scripts]
        beware=beware.cli:cli
    ''',
)
