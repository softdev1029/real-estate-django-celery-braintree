from datetime import date
import logging

from sherpa.tests import NoDataBaseTestCase
from ..integrations.braintree import allowed_skus, gateway
from ..models import product

logging.disable(logging.CRITICAL)


class BraintreeGatewayTestCase(NoDataBaseTestCase):

    def test_plans(self):
        INACTIVE_PLAN = '500-3mo-trial'
        self.assertIn(INACTIVE_PLAN, gateway.get_plans())
        allowed_plans = gateway.get_allowed_plans()
        self.assertNotIn(INACTIVE_PLAN, allowed_plans)
        self.assertIn(product.SMS_CORE, allowed_plans)
        self.assertEqual(gateway.get_plans.cache_info().hits, 1)
        self.assertEqual(gateway.get_plans.cache_info().misses, 1)

    def test_add_ons(self):
        INACTIVE_ADD_ON = 'additional_market_100'
        self.assertIn(INACTIVE_ADD_ON, gateway.get_add_ons())
        allowed_add_ons = gateway.get_allowed_add_ons()
        self.assertNotIn(INACTIVE_ADD_ON, allowed_add_ons)
        self.assertIn(product.ADDITIONAL_MARKET, allowed_add_ons)
        self.assertEqual(gateway.get_add_ons.cache_info().hits, 1)
        self.assertEqual(gateway.get_add_ons.cache_info().misses, 1)

    def test_discounts(self):
        INACTIVE_DISCOUNT = 'podcast'
        self.assertIn(INACTIVE_DISCOUNT, gateway.get_discounts())
        allowed_discounts = gateway.get_allowed_discounts()
        self.assertNotIn(INACTIVE_DISCOUNT, allowed_discounts)
        self.assertEqual(allowed_discounts, {})
        self.assertEqual(gateway.get_discounts.cache_info().hits, 1)
        self.assertEqual(gateway.get_discounts.cache_info().misses, 1)

    def test_subscriptions(self):
        active_plan_subscription_ids = gateway.get_active_plan_subscription_ids()
        first_subscription_id = active_plan_subscription_ids[0]
        subscription = gateway.get_subscription(first_subscription_id)
        self.assertIn(subscription.plan_id, allowed_skus)
        gateway.get_subscription(first_subscription_id)
        self.assertEqual(gateway.get_active_plan_subscription_ids.cache_info().hits, 1)
        self.assertEqual(gateway.get_active_plan_subscription_ids.cache_info().misses, 1)
        self.assertEqual(gateway.get_subscription.cache_info().hits, 1)
        self.assertEqual(gateway.get_subscription.cache_info().misses, 1)

    def test_transactions(self):
        valid_date = date(2021, 8, 9)
        settled_transactions = gateway.get_settled_transactions_for_date(valid_date)
        self.assertTrue(len(settled_transactions.ids) > 0)
