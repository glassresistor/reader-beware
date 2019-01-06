import yaml
import json
import base64

from markdown2 import Markdown
from jinja2 import Environment, contextfilter


class NarativeWorldBuilder(object):

    def __init__(self, yaml_path):
        with open(yaml_path, 'r') as f:
            self.naratives = yaml.load(f)
        self.env = Environment()
        self.env.filters['explore'] = self.explore
        self.env.filters['choice'] = self.choice
        markdowner = Markdown()
        self.markdown_to_html = markdowner.convert

    def build_html(self):
        self.render_body('entrypoint', {})

    def body(self, narative_name):
        return self.naratives[narative_name]['body']

    def narative_path(self, narative, world):
        world_params = json.dumps(world, sort_keys=True)
        return narative + '-' + world_params + '.html'

    def render_body(self, narative_name, world):
        body = self.body(narative_name)
        markdown = self.env.from_string(body, globals=world).render()
        html = self.markdown_to_html(markdown)
        output_file = 'output/' + self.narative_path(narative_name, world)
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


example = NarativeWorldBuilder('example.yaml')
example.build_html()
