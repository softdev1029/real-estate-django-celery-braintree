Billing
=======

The billing system adds to and extends the accounts system to enable pay-for-use services as well
as being the integration point to external billing systems.  Since external billing systems have a
limited number of care-abouts, it is essential that the modeling of the billing system captures all
of the information required by external billing systems, as well as complete and accurate auditing
of any relevant orders and transactions.

Braintree
---------

Since the first billing provider integrated was Braintree, we must look to their modelling for
inspiration.  Their concept is that you manually enter Plans, Add-ons, and Discounts through their
portal, and then using the API you exchange Customers and Payment Methods, as well as Subscriptions
and Transactions.  Since they are subscription focused, there is not much in the way of "caring"
about products that are _not_ subscription-based.  Thus, it is incumbent upon our system to
implement that modeling.

Salesforce
----------

