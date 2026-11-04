"""Store adapter on DynamoDB. Locally it talks to DynamoDB Local in Docker; in Phase 4 the same
class talks to the real service by leaving the endpoint empty. Table layout: docs/03-architecture.md.

boto3 is synchronous, so every call runs in a thread. The low-level client is used because it is
thread safe; the type serializer turns plain Python values into DynamoDB's typed format.
Records are dataclasses with snake_case fields; the tables use camelCase, as the data model says.
"""

import asyncio
import re
from dataclasses import MISSING, asdict, fields
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from ...ports import Document, PrepCard, Profile, Session, SessionItem, Store

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def snake(name: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), name)


def for_dynamo(value: Any) -> Any:
    """DynamoDB takes Decimal, not float. Applied to whole records, including nested payloads."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: for_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [for_dynamo(v) for v in value]
    return value


def from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def to_item(record) -> dict:
    item = {camel(k): for_dynamo(v) for k, v in asdict(record).items() if v is not None}
    if isinstance(record, SessionItem):
        item["sortKey"] = f"{record.timestamp:013d}#{record.type}"   # zero padded so string order is time order
    return {k: _serializer.serialize(v) for k, v in item.items()}


def from_item(cls, item: dict):
    values = {snake(k): from_dynamo(_deserializer.deserialize(v)) for k, v in item.items()}
    names = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in values.items() if k in names}
    for f in fields(cls):
        if f.default is MISSING and f.default_factory is MISSING:
            kwargs.setdefault(f.name, None)   # optional fields that were not stored, like endedAt
    return cls(**kwargs)   # fields with a default (agenda on an older session) keep it


def key(**parts) -> dict:
    return {k: _serializer.serialize(v) for k, v in parts.items()}


class DynamoDbStore(Store):
    def __init__(self, endpoint_url: str, region: str, table_prefix: str):
        options: dict = {"region_name": region}
        if endpoint_url:
            # DynamoDB Local accepts any credentials. Real AWS uses the CLI profile instead.
            options.update(endpoint_url=endpoint_url, aws_access_key_id="local", aws_secret_access_key="local")
        self.client = boto3.client("dynamodb", **options)
        self.prefix = table_prefix

    async def _call(self, method: str, **kwargs):
        return await asyncio.to_thread(getattr(self.client, method), **kwargs)

    async def _put(self, table: str, record) -> None:
        await self._call("put_item", TableName=self.prefix + table, Item=to_item(record))

    async def _get(self, table: str, cls, **key_parts):
        response = await self._call("get_item", TableName=self.prefix + table, Key=key(**key_parts))
        return from_item(cls, response["Item"]) if "Item" in response else None

    async def _query(self, table: str, cls, key_name: str, key_value: str) -> list:
        items, start_key = [], None
        while True:
            kwargs = dict(
                TableName=self.prefix + table,
                KeyConditionExpression="#k = :v",
                ExpressionAttributeNames={"#k": key_name},
                ExpressionAttributeValues={":v": _serializer.serialize(key_value)},
            )
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            response = await self._call("query", **kwargs)
            items += [from_item(cls, item) for item in response["Items"]]
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return items

    async def _delete(self, table: str, **key_parts) -> None:
        await self._call("delete_item", TableName=self.prefix + table, Key=key(**key_parts))

    # profiles
    async def save_profile(self, profile: Profile) -> None:
        await self._put("profiles", profile)

    async def get_profile(self, user_id: str) -> Profile | None:
        return await self._get("profiles", Profile, userId=user_id)

    # sessions
    async def save_session(self, session: Session) -> None:
        await self._put("sessions", session)

    async def get_session(self, user_id: str, session_id: str) -> Session | None:
        return await self._get("sessions", Session, userId=user_id, sessionId=session_id)

    async def list_sessions(self, user_id: str) -> list[Session]:
        sessions = await self._query("sessions", Session, "userId", user_id)
        return sorted(sessions, key=lambda s: s.started_at, reverse=True)

    async def delete_session(self, user_id: str, session_id: str) -> None:
        for item in await self.list_items(session_id):
            await self._delete("session_items", sessionId=session_id, sortKey=f"{item.timestamp:013d}#{item.type}")
        for card in await self.list_prep_cards(session_id):
            await self._delete("prep_cards", sessionId=session_id, cardId=card.card_id)
        await self._delete("sessions", userId=user_id, sessionId=session_id)

    # session items
    async def add_item(self, item: SessionItem) -> None:
        await self._put("session_items", item)

    async def list_items(self, session_id: str) -> list[SessionItem]:
        return await self._query("session_items", SessionItem, "sessionId", session_id)

    # documents
    async def save_document(self, document: Document) -> None:
        await self._put("documents", document)

    async def list_documents(self, user_id: str) -> list[Document]:
        return await self._query("documents", Document, "userId", user_id)

    async def delete_document(self, user_id: str, doc_id: str) -> None:
        await self._delete("documents", userId=user_id, docId=doc_id)

    # prep cards
    async def save_prep_card(self, card: PrepCard) -> None:
        await self._put("prep_cards", card)

    async def list_prep_cards(self, session_id: str) -> list[PrepCard]:
        return await self._query("prep_cards", PrepCard, "sessionId", session_id)

    async def delete_prep_card(self, session_id: str, card_id: str) -> None:
        await self._delete("prep_cards", sessionId=session_id, cardId=card_id)
