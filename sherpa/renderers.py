from io import BytesIO
from zipfile import ZipFile

from rest_framework.renderers import BaseRenderer


class ZipRenderer(BaseRenderer):
    media_type = 'application/x-zip-compressed'
    format = 'zip'

    def render(self, data, media_type=None, renderer_context=None):
        """
        Renders a zip file.
        :param data list<list>: Each inner list must be length two.  The first index is the
        filename and the second is the bytes to write into the zip file.
        """
        zip_io = BytesIO()
        zipf = ZipFile(zip_io, 'w')
        for d in data:
            zipf.writestr(d[0], d[1])
        zipf.close()
        return zip_io.getvalue()
