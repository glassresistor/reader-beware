import os
import shutil
from build_html import NarativeWorldBuilder


class EPubWorldBuilder(NarativeWorldBuilder):
    def build(self):
        try:
            os.makedirs(os.path.join(self.output_path))
        except Exception:
            pass
        self.render_body('entrypoint', {})
        # self.section_names.remove('entrypoint-{}.html')
        template = self.env.get_template('epub/content.opf.j2')
        content_opf = template.render(section_names=self.section_names)
        with open(os.path.join(self.output_path, 'content.opf'), 'w') as f:
            f.write(content_opf)
        shutil.make_archive(
            '%s.epub' %
            self.output_path,
            'zip',
            self.output_path)
