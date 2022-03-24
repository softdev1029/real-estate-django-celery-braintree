from django import forms

from sherpa.models import UploadLitigatorList


class LitigatorUploadCustomAddForm(forms.ModelForm):
    class Meta:
        model = UploadLitigatorList
        fields = ['file']

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        return super().__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        kwargs['commit'] = False
        obj = super().save(*args, **kwargs)
        if self.request:
            obj.created_by = self.request.user
        obj.save()
        return obj
