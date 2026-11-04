"""Auth port: who is connecting.

Local mode has one user and no login screen. Cognito mode (Phase 4) validates a token
before any audio is accepted.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class User:
    user_id: str
    display_name: str


class Auth(ABC):
    @property
    @abstractmethod
    def mode(self) -> str:
        """"local" or "cognito". Shown in the UI banner so nobody mistakes local mode for a login."""

    @abstractmethod
    async def authenticate(self, token: str | None) -> User | None:
        """The user behind this token, or None if the token is rejected."""
