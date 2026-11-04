"""Contract every Auth adapter must pass.

The subclass provides a token the adapter accepts. If it also has tokens it rejects (Cognito does,
local mode does not), it overrides invalid_token() to return one.
"""

import pytest

from app.ports import Auth


class AuthContract:
    def make_adapter(self) -> Auth:
        raise NotImplementedError("the adapter test must build its adapter here")

    def valid_token(self) -> str | None:
        raise NotImplementedError("the adapter test must provide a token the adapter accepts")

    def invalid_token(self) -> str | None:
        return None

    def test_mode_is_named(self):
        assert self.make_adapter().mode in ("local", "cognito")

    async def test_valid_token_gives_a_user(self):
        user = await self.make_adapter().authenticate(self.valid_token())
        assert user is not None
        assert user.user_id
        assert user.display_name

    async def test_invalid_token_is_rejected(self):
        token = self.invalid_token()
        if token is None:
            pytest.skip("this adapter has no invalid tokens (local single-user mode)")
        assert await self.make_adapter().authenticate(token) is None
