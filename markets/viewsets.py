from drf_yasg.utils import swagger_auto_schema

from django.conf import settings
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin, UpdateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from core.mixins import CompanyAccessMixin
from core.utils import clean_phone
from phone.choices import Provider
from sherpa.models import AreaCodeState, Market, PhoneNumber
from sms.clients import TelnyxClient
from .docs import (
    market_availability_query_parameters,
    market_best_effort_query_parameter,
    market_number_availability_query_parameters,
    market_return_phone_numbers_query_parameter,
)
from .serializers import (
    MarketPurchaseRequestSerializer,
    MarketSerializer,
    ParentMarketSerializer,
    PurchaseNumbersSerializer,
    TelephonyMarketSerializer,
)
from .tasks import purchase_additional_market_task
from .utils import format_telnyx_available_numbers


class MarketViewSet(
        CompanyAccessMixin,
        ListModelMixin,
        UpdateModelMixin,
        RetrieveModelMixin,
        GenericViewSet):
    serializer_class = MarketSerializer
    model = Market
    filterset_fields = ('is_active',)

    def __is_valid_quantity(self, quantity_param):
        """
        Validate the quantity param for purchasing or checking available numbers.

        :return: Tuple with is_valid (bool), quantity (int)
        """
        try:
            quantity = int(quantity_param)
        except (ValueError, TypeError):
            return False, None

        if quantity <= 0:
            return False, quantity

        return True, quantity

    @swagger_auto_schema(
        responses={200: {}},
        request_body=MarketPurchaseRequestSerializer,
    )
    @action(detail=False, methods=['post'], serializer_class=MarketSerializer)
    def telephony_market(self, request):
        """
        Create or update a market based on user's own Telephony setup including numbers provided.
        """
        serializer = TelephonyMarketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.data.get('name')
        call_forwarding_number = clean_phone(serializer.data.get('call_forwarding'))
        phone_number_ids = serializer.data.get('numbers')
        provider_id = serializer.data.get('provider_id')

        market, _ = Market.objects.get_or_create(
            company=request.user.profile.company,
            name=name,
            call_forwarding_number=call_forwarding_number,
        )
        PhoneNumber.objects.filter(
            company=request.user.profile.company,
            id__in=phone_number_ids,
        ).update(market=market, provider=Provider.get(provider_id))

        serializer = MarketSerializer(market)
        return Response(serializer.data)

    @swagger_auto_schema(
        responses={200: {}},
        request_body=MarketPurchaseRequestSerializer,
    )
    @action(detail=False, methods=['post'], serializer_class=MarketSerializer)
    def purchase(self, request):
        """
        Purchase a new market.

        If the market will be the company's only active market, then they will not be charged nor
        have an add-on added to their subscription.
        """
        serializer = MarketPurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile = request.user.profile
        market_name = serializer.data.get('market_name')
        area_code = serializer.data.get('area_code')
        best_effort = serializer.data.get('best_effort')
        call_forwarding_number = clean_phone(serializer.data.get('call_forwarding_number'))
        parent_market = AreaCodeState.objects.get(
            id=serializer.data.get('master_area_code_state_id'))

        # Create market right away, but the async actions should come in follow-up task.
        market, _ = Market.objects.update_or_create(
            company=profile.company,
            parent_market=parent_market,
            defaults={
                'name': market_name,
                'area_code1': area_code,
                'area_code2': area_code,
                'call_forwarding_number': call_forwarding_number,
                'is_active': True,
            },
        )

        purchase_additional_market_task.delay(
            profile.company_id,
            request.user.email,
            area_code,
            market_name,
            call_forwarding_number,
            parent_market.id,
            best_effort=best_effort,
        )

        serializer = MarketSerializer(market)
        return Response(serializer.data)

    @swagger_auto_schema(
        responses={200: {}},
        manual_parameters=[
            market_availability_query_parameters,
            market_best_effort_query_parameter,
        ],
    )
    @action(detail=False, pagination_class=None, filterset_fields=None, methods=['get'])
    def check_availability(self, request):
        """
        Check if a market is available for a company.
        """
        area_code_state_id = self.request.query_params.get('area_code_state_id')
        if not area_code_state_id:
            data = {'detail': 'Must include query parameter `area_code_state_id`'}
            return Response(data, status=400)

        area_code_state = AreaCodeState.objects.get(id=area_code_state_id)
        company = request.user.profile.company
        if Market.objects.filter(
            company=company,
            parent_market=area_code_state,
            is_active=True,
        ).exists():
            parent_market = Market.objects.filter(
                parent_market=area_code_state, company=company).first()
            data = {'detail': f'Company is already in the parent {parent_market.name} market.'}
            return Response(data, status=400)

        # Determine if we should search nearby areas for available numbers.
        best_effort = self.request.query_params.get('best_effort', 'false') == 'true'

        # If the market's area code has minimum amount for a campaign (20), then allow signup.
        if area_code_state.is_open:
            client = TelnyxClient()
            available_response = client.get_available_numbers(
                area_code_state.area_code,
                best_effort=best_effort,
            )
            if len(available_response['data']) >= 20 or settings.TEST_MODE:
                return Response(
                    format_telnyx_available_numbers(available_response, return_numbers=False),
                )

        return Response({'detail': 'Market is not available.'}, status=400)

    @swagger_auto_schema(
        responses={200: {}},
        manual_parameters=[
            market_number_availability_query_parameters,
            market_return_phone_numbers_query_parameter,
            market_best_effort_query_parameter,
        ],
    )
    @action(detail=True, methods=['get'], pagination_class=None, filterset_fields=None)
    def check_number_availability(self, request, pk=None):
        """
        Check if a given quantity of numbers is available in the market.
        """
        # Check that quantity is valid.
        quantity_param = self.request.query_params.get('quantity')
        is_valid, quantity = self.__is_valid_quantity(quantity_param)
        if not is_valid:
            invalid_message = '`quantity` parameter must be a valid integer greater than 0.'
            return Response({'detail': invalid_message}, status=400)

        # Determine if we should search nearby areas for available numbers.
        best_effort = self.request.query_params.get('best_effort', 'false') == 'true'
        return_numbers = self.request.query_params.get('return_numbers', 'false') == 'true'

        # Check if the numbers are available in the market.
        market = self.get_object()
        available_numbers = market.get_available_numbers(
            limit=quantity,
            best_effort=best_effort,
            return_numbers=return_numbers,
        )
        total_results = available_numbers['quantity']

        # Return response based on how many numbers are available.
        if total_results == quantity:
            return Response(available_numbers)
        elif total_results == 0:
            return Response(
                {'detail': f'No numbers are available with area code {market.area_code1}'},
                status=400,
            )
        else:
            message = f'Only {total_results} numbers are available with area code {market.area_code1}.'  # noqa: E501
            return Response({'detail': message}, status=400)

    @swagger_auto_schema(
        responses={200: {}},
        request_body=PurchaseNumbersSerializer,
    )
    @action(detail=True, methods=['post'])
    def purchase_numbers(self, request, pk=None):
        """
        market_purchase_numbers

        Purchase a given amount (quantity in payload) of numbers for the market.
        """
        market = self.get_object()

        if not market.is_active:
            return Response(
                {'detail': 'Cannot purchase numbers for inactive markets.'},
                status=400,
            )

        # Check that quantity is valid.
        serializer = PurchaseNumbersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Purchase the numbers in the market if they're available.
        quantity = int(request.data.get('quantity'))
        best_effort = serializer.data['best_effort']
        available_numbers = market.get_available_numbers(limit=quantity, best_effort=best_effort)
        total_results = available_numbers['quantity']
        if total_results == quantity:
            market.add_numbers(quantity, request.user, best_effort)
            return Response({})
        else:
            error_message = f'Only {total_results} numbers available for {market.name}.'
            return Response({'detail': error_message}, status=400)


class ParentMarketViewSet(ListModelMixin, GenericViewSet):
    """
    Returns a list of parent markets with their area code, city and state data.
    """
    serializer_class = ParentMarketSerializer
    queryset = AreaCodeState.objects.filter(parent_market=True)
    pagination_class = None
