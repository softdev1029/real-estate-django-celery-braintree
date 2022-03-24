from whitenoise.django import GzipManifestStaticFilesStorage


class ErrorSquashingStorage(GzipManifestStaticFilesStorage):
    def url(self, *args, **kwargs):
        try:
            return super(ErrorSquashingStorage, self).url(*args, **kwargs)
        except:
            return args[0]
