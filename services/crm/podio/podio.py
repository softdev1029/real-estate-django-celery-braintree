from pypodio2 import transport
from pypodio2.api import OAuthClient, OAuthFromExistingTokens, OAuthRefreshTokenClient

from companies.models import CompanyPodioCrm
from .api import API


def _save_tokens_to_db(company, tokens):
    """
    Helper function that Creates or Updates company's integration
    after a successful authentication
    """
    companyPodioRecord, created = CompanyPodioCrm.objects.get_or_create(company=company)
    companyPodioRecord.access_token = tokens.access_token
    companyPodioRecord.refresh_token = tokens.refresh_token
    companyPodioRecord.expires_in_token = tokens.expires_in
    companyPodioRecord.save()


class PodioClient(object):
    """
    Podio interface that wraps pypodio2 library with re-authentication
    logic when tokens expires
    """
    def __init__(self, company, client_id, client_secret, tokens=None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = None
        self._tokens = tokens or {}
        self._authenticated = False
        self.api = None
        self.company = company

    def _save_tokens(self, client, auth):
        self._client = client
        self._tokens = {
            'access': auth.token.access_token,
            'refresh': auth.token.refresh_token,
            'expires_in': auth.token.expires_in,
        }
        self._authenticated = True

        # update or create a new client
        if self.api is not None:
            self.api._update_client(client)
        else:
            # used to update client used on the podio api
            self.api = API(client, self._refresh)
        _save_tokens_to_db(self.company, auth.token)

    def _login(self, username, password):
        """Login logic"""
        try:
            client, auth = OAuthClient(
                self._client_id,
                self._client_secret,
                username,
                password,
            )
            self._save_tokens(client, auth)
            return True, None
        except transport.TransportException as e:
            return False, e.content.get('error_description')

    def _refresh(self):
        """Refresh tokens logic"""
        refresh = self._tokens.get('refresh')
        try:
            client, auth = OAuthRefreshTokenClient(
                self._client_id,
                self._client_secret,
                refresh,
            )
            self._save_tokens(client, auth)
            return True, None
        except transport.TransportException:
            return False, "Could not refresh token"

    def _auth_with_existing_credentials(self):
        """Authentication with just tokens"""
        try:
            client, auth = OAuthFromExistingTokens(self._tokens)
            self._save_tokens(client, auth)
            return True, None
        except transport.TransportException:
            return False, "Invalid tokens"

    def authenticate(self, username=None, password=None):
        """
        General authentication function that dispatches the proper function
        depending on the users current authentication status
        """
        if self._tokens.get('access') and self._tokens.get('refresh'):
            return self._auth_with_existing_credentials()
        if self._tokens.get('refresh'):
            return self._refresh()
        else:
            return self._login(username, password)
