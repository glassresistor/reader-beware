import os
import base64
import yaml
import json
import base64

from markdown2 import Markdown
from jinja2 import Environment, contextfilter, FileSystemLoader, select_autoescape


class NarativeWorldBuilder(object):
    def __init__(self, yaml_path, output_path):
        with open(yaml_path, 'r') as f:
            self.naratives = yaml.load(f)
        self.env = Environment(
            loader=FileSystemLoader('beware/templates'),
        )
        self.env.filters['explore'] = self.explore
        self.env.filters['choice'] = self.choice
        markdowner = Markdown()
        self.markdown_to_html = markdowner.convert
        self.output_path = output_path
        self.section_names = []

    def build():
        os.makedir(self.output_path)
        self.render_body('entrypoint', {})

    def body(self, narative_name):
        return self.naratives[narative_name]['body']

    def narative_path(self, narative, world):
        world_params = narative + '-' + json.dumps(world, sort_keys=True)
        return str(base64.b64encode(world_params.encode('ascii'))) + '.html'

    def render_body(self, narative_name, world):
        path = self.narative_path(narative_name, world)
        if path in self.section_names:
            return
        self.section_names.append(path)
        body = self.body(narative_name)
        markdown = self.env.from_string(body, globals=world).render()
        body = self.markdown_to_html(markdown)
        template = self.env.get_template('html/narative.html.j2')
        html = template.render(narative_name=narative_name, body=body)
        output_file = os.path.join(
            self.output_path, path)
        with open(output_file, 'w') as output:
            output.write(html)

    @contextfilter
    def explore(self, context, value):
        return self.choice(context, value)

    @contextfilter
    def choice(self, context, next_narative, **update_vars):
        world = context.vars
        world.update(update_vars)
        self.render_body(next_narative, world)
        return self.narative_path(next_narative, world)
