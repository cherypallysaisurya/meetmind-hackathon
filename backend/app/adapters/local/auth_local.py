"""Local Auth adapter: one user on this Mac, no login. The UI shows the mode so nobody mistakes it
for a login. Phase 4 adds the Cognito adapter behind the same port."""

from ...ports import Auth, User

LOCAL_USER = User(user_id="local", display_name="Local user")


class LocalAuth(Auth):
    @property
    def mode(self) -> str:
        return "local"

    async def authenticate(self, token: str | None) -> User | None:
        return LOCAL_USER
