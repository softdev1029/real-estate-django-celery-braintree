from datetime import date, datetime
import json

import requests

from django.conf import settings
from django.contrib.sites.models import Site
from django.urls import reverse


YELLOW_LETTER_DETAILS_CONFIG = {
    'product': '1',
    'order_notes': "",
    'name_of_order': "",
}


class YellowLetterClient:
    """
    Client to connect to Yellow Letter API.
    """
    api_base = "https://api.yellowletterhq.com/"

    def upload(self, records, template, target_date, note, order_name):
        """
        Upload records to Yellow Letter to print.

        :records list: List of CampaignProspects to send to (formatted per API docs).
        :template string: ID of template to use.
        :target_date string: String with date formatted as YYYY-MM-DD
        :return: Response from Yellow Letter
        """
        YELLOW_LETTER_DETAILS_CONFIG['order_notes'] = note if note else ''
        YELLOW_LETTER_DETAILS_CONFIG['name_of_order'] = order_name if order_name else ''

        data = {
            'target_date': target_date,
            'details': YELLOW_LETTER_DETAILS_CONFIG,
            'template_on_file': template,
            'html': '',
            'records': records,
        }

        response = self.__post('upload', data).json()
        direct_mail_response = self.__create_response(response)

        if direct_mail_response.error:
            return direct_mail_response

        direct_mail_response.order_id = response.get('ref_id')
        direct_mail_response.record_count = response.get('number records')
        self.send_webhook_url()
        return direct_mail_response

    def send_webhook_url(self):
        """
        Send webhook URL to Yellow Letter API

        :return: Response from Yellow Letter
        """
        domain = Site.objects.get(id=settings.SITE_ID).domain
        endpoint = reverse('campaign-direct-mail-tracking')

        data = {
            'action': "webhook_url",
            'data': domain + endpoint,
        }
        return self.__post('action', data)

    def upload_template(self, template_name, html_template):
        """
        Upload template to Yellow Letter API

        :template_name string: Name of template.
        :html_template: Template formatted in HTML.
        :return: Response from Yellow Letter
        """
        data = {
            'action': 'html_template',
            'data': {
                'template_name': template_name,
                'html_template': html_template,
            },
        }
        return self.__post('action', data)

    def delete_template(self, template_name):
        """
        Delete template in Yellow Letter API

        :template_name string: Name of template to delete.
        :return: Response from Yellow Letter
        """
        data = {
            'delete': 'html',
            'reference': template_name,
        }

        return self.__post('delete', data)

    def delete_order(self, reference_id):
        """
        Delete order in Yellow Letter API

        :reference_id string: Reference ID of order to delete.
        :return: Response from Yellow Letter
        """
        data = {
            'delete': 'order',
            'reference': reference_id,
        }

        return self.__post('delete', data)

    def get_order(self, reference_id):
        """
        Get data about an order (including status) from Yellow Letter API

        :reference_id string: Reference ID of order.
        :return: Response from Yellow Letter API
        """
        data = {
            'query': 'details',
            'reference': reference_id,
        }

        response = self.__post('query', data).json()
        direct_mail_response = self.__create_response(response)

        if direct_mail_response.error:
            return direct_mail_response

        answer = response.get('answer')
        if not answer:
            direct_mail_response.status = DirectMailOrderStatus.FAILED
            direct_mail_response.error = "Order was not created."
            return direct_mail_response

        order_details = answer[0]
        if order_details['ref_id'] != reference_id:
            direct_mail_response.status = DirectMailOrderStatus.FAILED
            direct_mail_response.error = "Mismatched order id."
            return direct_mail_response

        direct_mail_response.drop_date = datetime.strptime(
            order_details['target_date'],
            "%Y-%m-%d",
        ).date()
        direct_mail_response.record_count = order_details['number_record']
        direct_mail_response.template = order_details['template']

        direct_mail_response.status = DirectMailOrderStatus.IN_PRODUCTION
        if order_details['status'] == 'created':
            direct_mail_response.status = DirectMailOrderStatus.PRODUCTION_COMPLETE

        return direct_mail_response

    def get_templates(self):
        """
        Get templates from Yellow Letter API

        :return: Response from Yellow Letter API
        """
        data = {
            'query': 'html',
            'reference': '',
        }

        return self.__post('query', data)

    def get_next_target_date(self, date_):
        """
        Get next available target date

        :return: Response from Yellow Letter API
        """
        data = {
            'query': 'target_date',
            'reference': date_,
        }

        return self.__post('query', data)

    def __post(self, endpoint, data):
        """
        Executes post request after adding token to payload and formatting data as json.
        """
        data['token'] = settings.YELLOW_LETTER_TOKEN
        url = f'{self.api_base}{endpoint}'

        response = requests.post(url, json.dumps(data))
        return response

    @staticmethod
    def __create_response(response):
        """
        Create `DirectMailResponse` from response. Initialize with errors if there are any.
        """
        direct_mail_response = DirectMailResponse()
        if not response.get('success'):
            direct_mail_response.status = DirectMailOrderStatus.FAILED
            direct_mail_response.error = response.get('error')[0] if response.get('error') else None
        return direct_mail_response


class DirectMailOrderStatus:
    """
    Static values for the direct mail order status so we can use the same ones across providers.
    """
    SCHEDULED = 'scheduled'
    LOCKED = 'locked'
    PROCESSING = 'processing'
    IN_PRODUCTION = 'in_production'
    PRODUCTION_COMPLETE = 'production_complete'
    OUT_FOR_DELIVERY = 'out_for_delivery'
    COMPLETE = 'complete'
    FAILED = 'failed'
    INCOMPLETE = 'incomplete'
    CANCELLED = 'cancelled'

    CHOICES = (
        (SCHEDULED, 'scheduled'),
        (PROCESSING, 'processing'),
        (IN_PRODUCTION, 'in_production'),
        (PRODUCTION_COMPLETE, 'production_complete'),
        (COMPLETE, 'complete'),
        (OUT_FOR_DELIVERY, 'out_for_delivery'),
        (FAILED, 'failed'),
        (LOCKED, 'locked'),
        (INCOMPLETE, 'incomplete'),
        (CANCELLED, 'cancelled'),
    )

    @staticmethod
    def is_printing(status):
        """
        Boolean indicating if status is in the printing stage
        """
        return status in [DirectMailOrderStatus.PROCESSING, DirectMailOrderStatus.IN_PRODUCTION]


class DirectMailResponse:
    """
    Response to return for any Direct Mail API client used.
    """
    def __init__(
            self,
            status: DirectMailOrderStatus.CHOICES = DirectMailOrderStatus.PROCESSING,
            order_id: str = None,
            record_count: int = 0,
            drop_date: date = None,
            template: str = None,
            error: str = None,
    ):
        self.status: DirectMailOrderStatus.CHOICES = status
        self.error: str = error
        self.order_id: str = order_id
        self.record_count: int = record_count
        self.drop_date: date = drop_date
        self.template: str = template


class DirectMailStatusResponse:
    """
    Response to return for any Direct Mail Tracker API client used.
    """
    def __init__(
            self,
            record_count: int = 0,
            not_scanned: int = 0,
            early: int = 0,
            on_time: int = 0,
            late: int = 0,
            en_route: int = 0,
            error: str = None,
    ):
        self.record_count: int = record_count
        self.not_scanned: int = not_scanned
        self.early: int = early
        self.on_time: int = on_time
        self.late: int = late
        self.en_route: int = en_route
        self.error = error


class TrackingDetailResponse:
    """
    Response to return when getting tracking info per piece.
    """
    def __init__(self, data: list = None, error: str = None):
        self.data: list = data
        self.error: str = error


class AccuTraceClient:
    """
    Client to connect to AccuTrace API.
    """
    token = settings.ACCUZIP_TOKEN
    api_prefix = "sherpa"
    api_base = f"https://{api_prefix}.iaccutrace.com/servoy-service/rest_ws/mod_rest"
    api_report_base = url = f'{api_base}/ws_job_reports'

    def get_status(self, tracking_url):
        """
        Get status for specified job.

        :job_id: Job ID to query specific job
        """
        uid = tracking_url.split('uid=')[1]
        url = f'{self.api_base}/ws_jobs/{uid}/'
        job_data = requests.get(url)

        if not job_data.status_code == 200 and not job_data.json().get('jobs'):
            return DirectMailStatusResponse(error='Could not get job id')

        job_id = job_data.json().get('jobs')[0].get('job_id')

        url = f'{self.api_report_base}/{uid}/jobId={job_id}&reportNumber=2&level=1&getDataSet=true'
        response = requests.get(url)
        error, data = self.__validate_response(response)

        if error:
            return DirectMailStatusResponse(error=error)

        counts = data.get('dataset').get('rows')
        return DirectMailStatusResponse(
            record_count=job_data.json().get('jobs')[0].get('mailtotal'),
            not_scanned=counts[0][1],
            early=counts[1][1],
            on_time=counts[2][1],
            late=counts[3][1],
            en_route=counts[4][1],
        )

    def get_returned(self, job_id):
        """
        Get returned pieces for specified job.

        :job_id: Job ID to query specific job
        """
        return self.__get_by_status(job_id, 'singlePieceReturn')

    def get_redirected(self, job_id):
        """
        Get redirected pieces for specified job.

        :job_id: Job ID to query specific job
        """
        return self.__get_by_status(job_id, 'singlePieceRedirect')

    def get_delivered(self, job_id):
        """
        Get delivered pieces for specified job.

        :job_id: Job ID to query specific job
        """
        status = ['Early', 'On Time', 'Late']
        results = TrackingDetailResponse()
        for stat in status:
            current_resp = self.__get_by_status(job_id, stat, 2, 2)
            results.data.extend(current_resp.data)
            results.error = current_resp.error if current_resp.error else results.error
        return results

    def __get_by_status(self, job_id, status, report=13, level=1):
        """
        Get pieces by status for given job

        :job_id: Job ID to query specific job
        :status: Status to query
        :report: Report to query
        :level: Level of data to get
        """
        status_name = 'additionalOptions' if report == 13 else 'status'
        url = f'{self.api_report_base}jobId={job_id}&reportNumber={report}&level={level}' \
              f'&getDataSet=true&{status_name}={status}'

        error, data = self.__validate_response(requests.get(url))
        if error:
            return TrackingDetailResponse(error=error)

        return TrackingDetailResponse(
            data=[{'barcode': x[0], 'imd': x[1]} for x in data.get('dataset').get('rows')],
        )

    @staticmethod
    def __validate_response(response):
        """
        Verify response is OK and has data.dataset.rows
        """

        if response.status_code != 200:
            return "Count not get tracking information.", None

        data = response.json().get('data')
        if not data or not data.get('dataset') or not data.get('dataset').get('rows'):
            return "Invalid response", None

        return None, data
