import csv

import requests

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db.models import Q
from django.http import (
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse

from litigation.tasks import litigator_check_task
from .csv_uploader import CSVFieldMapper
from .forms import LitigatorCheckStartForm
from .models import LitigatorCheck, UploadLitigatorCheck


# litigator_check_home is a public page
def litigator_check_home(request):
    return render(request, 'litigator_check/litigator_check_home.html')


# litigator_check_select_file is a public page with a Captcha
def litigator_check_select_file(request):
    if request.method == 'POST':
        recaptcha_response = request.POST.get('g-recaptcha-response')
        data = {
            'secret': '6Lez4moUAAAAAJ49sanL--U1xFWxLlF4SxvMwTNl',
            'response': recaptcha_response,
        }
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=data)
        return JsonResponse(r.json())

    return render(request, 'litigator_check/litigator_check_select_file.html')


def litigator_check_map_fields(request):
    if request.method == 'POST':
        # rest framework viewsets have request.data instead of request.POST.
        request.data = request.POST
        csv_mapper = CSVFieldMapper(request)
        csv_mapper.map_upload_litigator_check()

        if csv_mapper.success:
            return JsonResponse({'id': csv_mapper.upload_object.token})

        return JsonResponse({'detail': 'Failed to upload file.'})


def litigator_check_start(request, check_litigator_hash):
    """
    Review the litigator check stats and begin the file processing.
    """
    upload_litigator_check = get_object_or_404(UploadLitigatorCheck, token=check_litigator_hash)
    row_count = upload_litigator_check.total_rows

    if request.method == 'POST':
        form = LitigatorCheckStartForm(request.POST, request.FILES)
        if form.is_valid():

            email_address = request.POST.get('email_address')

            try:
                validate_email(email_address)
            except ValidationError:

                return render(request, 'litigator_check/litigator_check_start.html', {
                    'row_count': row_count,
                    'form': form, 'show_alert': True,
                    'check_litigator_hash': check_litigator_hash,
                })

            if not upload_litigator_check.email_started_confirmation_sent \
                    or email_address != upload_litigator_check.email_address:
                # Email user here
                try:
                    ref_id_raw = check_litigator_hash[:5]
                    ref_id = ref_id_raw.replace("-", "7")
                except Exception:
                    ref_id = '82076'
                site = Site.objects.get_current()
                subject = 'Litigator Scrub Started - Ref# %s' % ref_id
                from_email = settings.DEFAULT_FROM_EMAIL
                to = email_address
                text_content = 'Litigator Check Started'
                html_content = render_to_string(
                    'email/email_litigator_check_started_confirmation.html',
                    {
                        'site': site,
                        'row_count': row_count,
                        'upload_litigator_check': upload_litigator_check,
                    })
                email = EmailMultiAlternatives(subject, text_content, from_email, [to])
                email.attach_alternative(html_content, "text/html")

                email.send()

            upload_litigator_check.email_address = email_address
            upload_litigator_check.email_started_confirmation_sent = True
            upload_litigator_check.save()

            # Call task here
            litigator_check_task.delay(upload_litigator_check.id)

            return HttpResponseRedirect(
                reverse('check_litigator_status', args=(check_litigator_hash,)))

    form = LitigatorCheckStartForm()

    return render(
        request,
        'litigator_check/litigator_check_start.html',
        {
            'row_count': row_count,
            'form': form, 'show_alert': False,
            'check_litigator_hash': check_litigator_hash,
            'upload_litigator_check': upload_litigator_check,
        })


def check_litigator_started_confirmation(request, check_litigator_hash):
    upload_litigator_check = get_object_or_404(UploadLitigatorCheck, token=check_litigator_hash)
    row_count = upload_litigator_check.total_rows
    email_address = upload_litigator_check.email_address

    return render(
        request,
        'litigator_check/litigator_check_started_confirmation.html',
        {
            'row_count': row_count,
            'email_address': email_address,
            'upload_litigator_check': upload_litigator_check,
        })


def check_litigator_status(request, check_litigator_hash):
    upload_litigator_check = get_object_or_404(UploadLitigatorCheck, token=check_litigator_hash)

    if request.is_ajax():
        return render(request, 'litigator_check/litigator_check_status_partial.html',
                      {'upload_litigator_check': upload_litigator_check})

    return render(request, 'litigator_check/litigator_check_status.html',
                  {'upload_litigator_check': upload_litigator_check})


def check_litigator_export(request, check_litigator_hash):
    upload_litigator_check = UploadLitigatorCheck.objects.get(token=check_litigator_hash)

    class Echo:
        def write(self, value):
            return value

    def data():
        writer = csv.writer(Echo())
        writer.writerow([
            'first_name',
            'last_name',
            'mailing_address',
            'mailing_city',
            'mailing_state',
            'mailing_zip',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'validated_mailing_status',
            'validated_mailing_delivery_line_1',
            'validated_mailing_delivery_line_2',
            'validated_mailing_city_name',
            'validated_mailing_state_abbreviation',
            'validated_mailing_zipcode',
            'validated_mailing_vacant',
            'validated_property_status',
            'validated_property_delivery_line_1',
            'validated_property_delivery_line_2',
            'validated_property_city_name',
            'validated_property_state_abbreviation',
            'validated_property_zipcode',
            'validated_property_vacant',
            'email',
            'phone1',
            'phone2',
            'phone3',
            'custom1',
            'custom2',
            'custom3',
            'litigator_type',
        ])

        litigator_check_list = LitigatorCheck.objects.filter(
            Q(upload_litigator_check=upload_litigator_check),
        ).order_by('sort_order')

        yield writer.writerow(['First Name',
                               'Last Name',
                               'Mailing Street',
                               'Mailing City',
                               'Mailing State',
                               'Mailing Zipcode',
                               'Property Street',
                               'Property City',
                               'Property State',
                               'Property Zipcode',
                               'Mailing Validation Status',
                               'Validated Mailing Street 1',
                               'Validated Mailing Street 2',
                               'Validated Mailing City',
                               'Validated Mailing State',
                               'Validated Mailing Zipcode',
                               'Validated Mailing Vacant?',
                               'Property Validation Status',
                               'Validated Property Street 1',
                               'Validated Property Street 2',
                               'Validated Property City',
                               'Validated Property State',
                               'Validated Property Zipcode',
                               'Validated Property Vacant?',
                               'Email',
                               'Phone1',
                               'Phone2',
                               'Phone3',
                               'Custom 1',
                               'Custom 2',
                               'Custom 3',
                               'Litigator Type',
                               ])

        for litigator_check in litigator_check_list:
            yield writer.writerow([litigator_check.first_name,
                                   litigator_check.last_name,
                                   litigator_check.mailing_address,
                                   litigator_check.mailing_city,
                                   litigator_check.mailing_state,
                                   litigator_check.mailing_zip,
                                   litigator_check.property_address,
                                   litigator_check.property_city,
                                   litigator_check.property_state,
                                   litigator_check.property_zip,
                                   litigator_check.validated_mailing_status,
                                   litigator_check.validated_mailing_delivery_line_1,
                                   litigator_check.validated_mailing_delivery_line_2,
                                   litigator_check.validated_mailing_city_name,
                                   litigator_check.validated_mailing_state_abbreviation,
                                   litigator_check.validated_mailing_zipcode,
                                   litigator_check.validated_mailing_vacant,
                                   litigator_check.validated_property_status,
                                   litigator_check.validated_property_delivery_line_1,
                                   litigator_check.validated_property_delivery_line_2,
                                   litigator_check.validated_property_city_name,
                                   litigator_check.validated_property_state_abbreviation,
                                   litigator_check.validated_property_zipcode,
                                   litigator_check.validated_property_vacant,
                                   litigator_check.email,
                                   litigator_check.phone1,
                                   litigator_check.phone2,
                                   litigator_check.phone3,
                                   litigator_check.custom1,
                                   litigator_check.custom2,
                                   litigator_check.custom3,
                                   litigator_check.litigator_type,
                                   ])

    original_file_name_raw1 = upload_litigator_check.uploaded_filename
    original_file_name_raw2 = original_file_name_raw1.replace(".csv", "")
    original_file_name_raw3 = original_file_name_raw2.replace(".", "")
    original_file_name = original_file_name_raw3.replace(" ", "-")

    filename = "LITIGATOR-SCRUB-%s" % (original_file_name)

    response = StreamingHttpResponse(data(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename=%s.csv' % filename

    return response


def status(request):
    """
    Return a 200 response for checking the status of our servers.
    """
    return HttpResponse('OK')
