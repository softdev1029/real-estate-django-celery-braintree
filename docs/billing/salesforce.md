Salesforce
==========

Purpose
-------

Sync to Salesforce will allow better metrics, prevent churn, etc.

Getting Started
---------------

Salesforce admin account was created by jason@leadsherpa.com for the org.  Additional account was
made for dev integration tied to dev@leadsherpa.com.  Once logged in as dev@leadsherpa.com, should
generate a token using the user icon in upper right corner => settings => reset my security token.
This will be required to use the API.

Production (the default from simple salesforce) is accessed at login.salesforce.com.
Sandbox (target of non-production webapp unless overridden in env) is accessed at test.salesforce.com.

Manual Invocation
-----------------

After setting up the BRAINTREE environment variables appropriately (NOT production),
you can seed the database and run the following command:

`docker-compose run --rm web ./manage.py push_to_salesforce`
