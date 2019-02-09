import os
import json
import base64
import shutil
from beware.build_html import NarativeWorldBuilder


class EPubWorldBuilder(NarativeWorldBuilder):
    def build(self):
        super(EPubWorldBuilder, self).build()
        template = self.env.get_template('epub/content.opf.j2')
        content_opf = template.render(section_names=self.section_names)
        with open(os.path.join(self.output_path, 'content.opf'), 'w') as f:
            f.write(content_opf)
        shutil.copyfile(
            os.path.join(self.base_dir, 'files', 'template.css'),
            os.path.join(
                self.output_path,
                'template.css'))
        shutil.make_archive(
            '%s.epub' %
            self.output_path,
            'zip',
            self.output_path)
        os.rename(
            '%s.epub.zip' %
            self.output_path,
            '%s.epub' %
            self.output_path)

    def narative_path(self, narative, world):
        world_params = narative + '-' + json.dumps(world, sort_keys=True)
        return '%s.html' % base64.b64encode(
            world_params.encode('ascii')).decode()
