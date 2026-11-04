"""Contract every Store adapter must pass. Ids are random so runs never collide on a shared database."""

import time
from uuid import uuid4

from app.ports import Document, PrepCard, Profile, Session, SessionItem, Store


def new_id():
    return uuid4().hex


def far_future():
    return int(time.time()) + 30 * 24 * 3600


class StoreContract:
    def make_adapter(self) -> Store:
        raise NotImplementedError("the adapter test must build its adapter here")

    async def test_profile_round_trip_and_missing_profile(self):
        store = self.make_adapter()
        profile = Profile(
            user_id=new_id(), display_name="Surya", aliases=["Surya", "Sur"], role="Junior ML Engineer",
            topics=["retrieval", "evaluation"], bio="Works on retrieval.", current_projects="MeetMind",
            created_at=int(time.time()),
        )
        await store.save_profile(profile)
        assert await store.get_profile(profile.user_id) == profile
        assert await store.get_profile(new_id()) is None

    async def test_sessions_items_and_cascading_delete(self):
        store = self.make_adapter()
        user_id = new_id()
        older = Session(user_id, new_id(), "Standup", started_at=1000, ended_at=None, summary="", todos=[], ttl=far_future())
        newer = Session(user_id, new_id(), "Review", started_at=2000, ended_at=None, summary="", todos=[], ttl=far_future())
        await store.save_session(older)
        await store.save_session(newer)
        assert [s.session_id for s in await store.list_sessions(user_id)] == [newer.session_id, older.session_id]

        second = SessionItem(older.session_id, timestamp=2000, type="alert", payload={"text": "later"}, ttl=far_future())
        first = SessionItem(older.session_id, timestamp=1000, type="final_turn", payload={"text": "earlier"}, ttl=far_future())
        await store.add_item(second)
        await store.add_item(first)
        assert await store.list_items(older.session_id) == [first, second]

        card = PrepCard(older.session_id, new_id(), "What is the plan?", ["Plan?"], {"line": "We ship Friday."},
                        sources=[], user_edited=False, created_at=1000, ttl=far_future())
        await store.save_prep_card(card)
        assert await store.list_prep_cards(older.session_id) == [card]

        await store.delete_session(user_id, older.session_id)
        assert await store.get_session(user_id, older.session_id) is None
        assert await store.list_items(older.session_id) == []
        assert await store.list_prep_cards(older.session_id) == []
        assert [s.session_id for s in await store.list_sessions(user_id)] == [newer.session_id]
        await store.delete_session(user_id, newer.session_id)   # leave the shared database as we found it

    async def test_a_prepared_session_keeps_its_agenda_and_participants(self):
        store = self.make_adapter()
        user_id = new_id()
        prepared = Session(user_id, new_id(), "Dana 1:1", started_at=0, ended_at=None, summary="", todos=[], ttl=far_future(),
                           agenda="Release 6 review\nOpenPlaces timing", participants=["Dana"])
        await store.save_session(prepared)
        assert await store.get_session(user_id, prepared.session_id) == prepared
        await store.delete_session(user_id, prepared.session_id)

    async def test_documents(self):
        store = self.make_adapter()
        user_id = new_id()
        first = Document(user_id, new_id(), "notes.md", "md", added_at=1000, chunk_count=4, status="ready")
        second = Document(user_id, new_id(), "paper.pdf", "pdf", added_at=2000, chunk_count=40, status="ready")
        await store.save_document(first)
        await store.save_document(second)
        assert {d.doc_id for d in await store.list_documents(user_id)} == {first.doc_id, second.doc_id}
        await store.delete_document(user_id, first.doc_id)
        assert await store.list_documents(user_id) == [second]
        await store.delete_document(user_id, second.doc_id)

    async def test_prep_card_delete(self):
        store = self.make_adapter()
        session_id = new_id()
        card = PrepCard(session_id, new_id(), "Why twelve minutes?", [], {"line": "Because of the new index."},
                        sources=[{"document": "notes.md", "location": "section: results"}],
                        user_edited=True, created_at=1000, ttl=far_future())
        await store.save_prep_card(card)
        assert await store.list_prep_cards(session_id) == [card]
        await store.delete_prep_card(session_id, card.card_id)
        assert await store.list_prep_cards(session_id) == []
