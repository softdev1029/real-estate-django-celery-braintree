from django import forms

from .models import UploadLitigatorCheck


class LitigatorCheckStartForm(forms.ModelForm):
    class Meta:
        model = UploadLitigatorCheck
        fields = ['email_address']

    def __init__(self, *args, **kwargs):
        super(LitigatorCheckStartForm, self).__init__(*args, **kwargs)
        self.fields['email_address'].widget.attrs['class'] = 'form-control'
        self.fields['email_address'].widget.attrs['placeholder'] = 'email address'
        self.fields['email_address'].widget.attrs['autofocus'] = 'autofocus'
