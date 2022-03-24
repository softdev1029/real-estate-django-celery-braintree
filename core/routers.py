from rest_framework import routers

from accounts.viewsets import UserProfileViewSet
from billing.viewsets import PlanViewSet
from calls.viewsets import CallViewSet
from campaigns.viewsets import (
    CampaignNoteViewSet,
    CampaignTagViewSet,
    CampaignViewSet,
    StatsBatchViewSet,
    UploadProspectViewSet,
)
from companies.viewsets import (
    CompanyGoalViewSet,
    CompanyViewSet,
    CompanyPropStackFilterSettingsViewSet,
    DNCViewSet,
    DownloadHistoryViewSet,
    LeadStageViewSet,
    SubscriptionCancellationRequestViewSet,
    TelephonyConnectionViewSet,
    CompanyPodioIntegrationViewSet,
    CompanyPodioWorkspaceViewSet,
    CompanyPodioApplicationViewSet,
    CompanyPodioFieldsViewSet,
    CompanyPodioItemsViewSet,
)
from markets.viewsets import MarketViewSet, ParentMarketViewSet
from phone.router import router as phone_router
from phone.viewsets import PhoneNumberViewSet
from properties.viewsets import PropertyTagViewSet
from prospects.viewsets import (
    CampaignProspectViewSet,
    ProspectNoteViewSet,
    ProspectRelayViewSet,
    ProspectTagViewSet,
    ProspectViewSet,
)
from search.router import router as search_router
from sherpa.viewsets import InvitationCodeViewSet, SupportLinkViewSet, ZapierWebhookViewSet
from skiptrace.viewsets import UploadSkipTraceViewSet
from sms.viewsets import (
    CarrierApprovedTemplateViewSet,
    QuickReplyViewSet,
    SMSMessageViewSet,
    SMSResultViewSet,
    SMSTemplateCategoriesViewSet,
    SMSTemplateViewSet,
)


router = routers.DefaultRouter()
router.register(r'campaigns', CampaignViewSet, basename='campaign')
router.register(r'campaign-tags', CampaignTagViewSet, basename='campaigntag')
router.register(r'upload-prospects', UploadProspectViewSet, basename='uploadprospect')
router.register(r'companies', CompanyViewSet, basename='company')
router.register(r'company-stacker-filters', CompanyPropStackFilterSettingsViewSet, basename='stackerfilters')
router.register(r'crm/podio/auth', CompanyPodioIntegrationViewSet, basename='crmpodiointegration')
router.register(r'crm/podio/organizations', CompanyPodioWorkspaceViewSet, basename='crmpodioorganizations')
router.register(r'crm/podio/applications', CompanyPodioApplicationViewSet, basename='crmpodioapplications')
router.register(r'crm/podio/items', CompanyPodioItemsViewSet, basename='crmpodioitems')
router.register(r'crm/podio/fields', CompanyPodioFieldsViewSet, basename='crmpodiofields')
router.register(r'goals', CompanyGoalViewSet, basename='companygoal')
router.register(r'telephony', TelephonyConnectionViewSet, basename='telephonyconnection')
router.register(r'prospects', ProspectViewSet, basename='prospect')
router.register(r'campaign-prospects', CampaignProspectViewSet, basename='campaignprospect')
router.register(r'leadstages', LeadStageViewSet, basename='leadstage')
router.register(r'download-history', DownloadHistoryViewSet, basename='downloadhistory')
router.register(r'dnc', DNCViewSet, basename='dnc')
router.register(r'prospect-notes', ProspectNoteViewSet, basename='prospectnote')
router.register(r'sms-templates', SMSTemplateViewSet, basename='smstemplate')
router.register(
    r'template-categories', SMSTemplateCategoriesViewSet, basename='smstemplatecategories')
router.register(r'sms-messages', SMSMessageViewSet, basename='smsmessage')
router.register(r'support-links', SupportLinkViewSet)
router.register(r'campaign-notes', CampaignNoteViewSet, basename='campaignnote')
router.register(r'markets', MarketViewSet, basename='market')
router.register(r'parent-markets', ParentMarketViewSet)
router.register(r'zapier-webhooks', ZapierWebhookViewSet, basename='zapierwebhook')
router.register(r'skip-traces', UploadSkipTraceViewSet, basename='uploadskiptrace')
router.register(r'stats-batches', StatsBatchViewSet, basename='statsbatch')
router.register(r'quick-replies', QuickReplyViewSet, basename='quickreply')
router.register(r'phone-numbers', PhoneNumberViewSet, basename='phonenumber')
router.register(r'sms-results', SMSResultViewSet, basename='smsresult')
router.register(r'calls', CallViewSet, basename='call')
router.register(r'user-profiles', UserProfileViewSet, basename='userprofile')
router.register(r'prospect-relays', ProspectRelayViewSet, basename='prospectrelay')
router.register(r'prospect-tags', ProspectTagViewSet, basename='prospecttag')
router.register(r'property-tags', PropertyTagViewSet, basename='propertytag')
router.register(r'plans', PlanViewSet)
router.register(r'invitation-codes', InvitationCodeViewSet)
router.register(r'cancellations', SubscriptionCancellationRequestViewSet, basename='cancellation')
router.register(
    r'carrier-approved-templates', CarrierApprovedTemplateViewSet, basename='carriertemplate')

# Attach search router
router.registry.extend(search_router.registry)

# Attach phone router
router.registry.extend(phone_router.registry)
