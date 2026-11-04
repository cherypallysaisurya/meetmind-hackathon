from app.adapters.factory import make_auth
from tests.contract.auth_contract import AuthContract


class TestLocalAuth(AuthContract):
    def make_adapter(self):
        return make_auth()

    def valid_token(self):
        return None   # local mode: nobody signs in
