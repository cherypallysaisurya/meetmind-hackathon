"""Store port: the five record types from the data model and how to read and write them.

Table layout is in docs/03-architecture.md section 11. Vectors never go here, they live in the VectorStore.
Fields named ttl hold the unix time (seconds) at which the record expires.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Profile:
    user_id: str
    display_name: str
    aliases: list[str]
    role: str
    topics: list[str]
    bio: str                  # max 2,000 characters
    current_projects: str     # max 4,000 characters
    created_at: int


@dataclass
class Session:
    user_id: str
    session_id: str
    title: str
    started_at: int           # 0 for a meeting prepared but not held yet
    ended_at: int | None
    summary: str
    todos: list[str]
    ttl: int
    agenda: str = ""          # pasted when the meeting is prepared (Phase 2P)
    participants: list[str] = field(default_factory=list)


@dataclass
class SessionItem:
    session_id: str
    timestamp: int            # milliseconds, part of the sort key "timestamp#type"
    type: str                 # final_turn, alert, answer, doubt or notes
    payload: dict
    ttl: int


@dataclass
class Document:
    user_id: str
    doc_id: str
    name: str
    type: str                 # pdf, md, txt or docx
    added_at: int
    chunk_count: int
    status: str               # for example "ready" or "failed"


@dataclass
class PrepCard:
    session_id: str
    card_id: str
    predicted_question: str
    variants: list[str]
    card: dict                # the cue card: line, points, confidence
    sources: list[dict]
    user_edited: bool
    created_at: int
    ttl: int


class Store(ABC):
    @abstractmethod
    async def save_profile(self, profile: Profile) -> None: ...

    @abstractmethod
    async def get_profile(self, user_id: str) -> Profile | None: ...

    @abstractmethod
    async def save_session(self, session: Session) -> None:
        """Create or fully replace a session record."""

    @abstractmethod
    async def get_session(self, user_id: str, session_id: str) -> Session | None: ...

    @abstractmethod
    async def list_sessions(self, user_id: str) -> list[Session]:
        """Newest first."""

    @abstractmethod
    async def delete_session(self, user_id: str, session_id: str) -> None:
        """Remove the session, its items and its prep cards."""

    @abstractmethod
    async def add_item(self, item: SessionItem) -> None: ...

    @abstractmethod
    async def list_items(self, session_id: str) -> list[SessionItem]:
        """Oldest first."""

    @abstractmethod
    async def save_document(self, document: Document) -> None: ...

    @abstractmethod
    async def list_documents(self, user_id: str) -> list[Document]: ...

    @abstractmethod
    async def delete_document(self, user_id: str, doc_id: str) -> None: ...

    @abstractmethod
    async def save_prep_card(self, card: PrepCard) -> None: ...

    @abstractmethod
    async def list_prep_cards(self, session_id: str) -> list[PrepCard]: ...

    @abstractmethod
    async def delete_prep_card(self, session_id: str, card_id: str) -> None: ...
