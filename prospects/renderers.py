from rest_framework_csv.renderers import CSVStreamingRenderer

from .utils import CP_EXPORT_HEADERS, PROSPECT_EXPORT_HEADERS


class CampaignProspectRenderer(CSVStreamingRenderer):
    """
    Render the campaign prospects as a csv export.
    """
    header = CP_EXPORT_HEADERS


class ProspectExportRenderer(CSVStreamingRenderer):
    """
    Render the prospects as a csv export.
    """
    header = PROSPECT_EXPORT_HEADERS
