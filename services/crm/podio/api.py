from .utils import for_all_methods, refresh, response_handler


class ApiResource(object):
    """
    Base class for common operations for different podio APIs.
    """
    def __init__(self, client, refresh_handler):
        """
        :param client PodioClient:       The authenticated podio client instance
        :param refresh_handler Function: Function that wraps refres token logic
        """
        self._client = client
        self._refresh_handler = refresh_handler


@for_all_methods(refresh)
@for_all_methods(response_handler)
class Item(ApiResource):
    """
    Interface with the Podio Item API providing refresh-token logic for
    all methods. Used to create/update podio items that we sync from sherpa.
    """
    def get(self, item_id):
        return self._client.Item.find(item_id=item_id)

    def create(self, app_id, attrs):
        return self._client.Item.create(app_id, attrs, hook=False)

    def update(self, item_id, attrs, hook=False):
        return self._client.Item.update(item_id, attrs)


@for_all_methods(refresh)
@for_all_methods(response_handler)
class Comment(ApiResource):
    """
    Interface with the Podio Comment API providing refresh-token logic for
    all methods. Used to create prospect messages on the podio-item's comment
    section.
    """
    def create(self, object_type, object_id, attrs):
        return self._client.Comment.create(object_type, object_id, attrs)

    def get_comments_for_item(self, item_id, limit=100, offset=0):
        return self._client.Comment.get_comments('item', item_id, limit, offset)


@for_all_methods(refresh)
@for_all_methods(response_handler)
class Organization(ApiResource):
    """
    Interface with the Podio Organization API providing refresh-token logic for
    all methods.
    """
    def get_all(self):
        return self._client.Org.get_all()

    def get_all_workspaces(self, org_id):
        return self._client.Org.get_all_spaces(org_id)


@for_all_methods(refresh)
@for_all_methods(response_handler)
class Workspace(ApiResource):
    """
    Interface with the Podio Workspace API providing refresh-token logic for
    all methods.
    """
    def get(self, workspace_id):
        return self._client.Space.find(workspace_id)

    def get_applications(self, workspace_id):
        return self._client.Application.list_in_space(workspace_id)


@for_all_methods(refresh)
@for_all_methods(response_handler)
class Application(ApiResource):
    """
    Interface with the Podio Application API providing refresh-token logic for
    all methods.
    """
    def export_items_xlsx(self, app_id, view_id=None):
        return self._client.Application.export_items_xlsx(app_id, view_id)

    def get(self, app_id):
        return self._client.Application.find(app_id)

    def get_items(self, app_id):
        return self._client.Application.get_items(app_id)


@for_all_methods(refresh)
@for_all_methods(response_handler)
class Webhook(ApiResource):
    """
    Interface with the Podio Webhook API providing refresh-token logic for
    all methods.
    """
    def create(self, hook_type, hook_id, attributes):
        return self._client.Hook.create(hook_type, hook_id, attributes)

    def verify(self, hook_id):
        return self._client.Hook.verify(hook_id)

    def validate(self, hook_id, code):
        return self._client.Hook.validate(hook_id, code)

    def delete(self, hook_id):
        return self._client.Hook.delete(hook_id)


@for_all_methods(refresh)
@for_all_methods(response_handler)
class View(ApiResource):
    """
    Interface with the Podio View API providing refresh-token logic for
    all methods.
    """
    def get_views(self, app_id):
        return self._client.View.get_views(app_id)


class API(object):
    """
    Combines all the different Podio API interfaces into 1 class.
    You can add/remove APIS by removing them from _APIS
    """
    _APIS = ("Application", "Item", "Organization", "Workspace", "View")

    def __init__(self, client, refresh_handler):
        self.Item = Item(client, refresh_handler)
        self.Application = Application(client, refresh_handler)
        self.Workspace = Workspace(client, refresh_handler)
        self.Organization = Organization(client, refresh_handler)
        self.View = View(client, refresh_handler)
        self.Comment = Comment(client, refresh_handler)
        self.Webhook = Webhook(client, refresh_handler)

    def _update_client(self, client):
        """update each api's client after a refresh logic occurs"""
        for item in self._APIS:
            attr = getattr(self, item)
            attr._client = client
