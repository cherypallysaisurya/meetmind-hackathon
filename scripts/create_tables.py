"""Create MeetMind's DynamoDB tables and prove a write and a read work.

Run from the repo root with the local stack up (docker compose up -d):
    backend/.venv/bin/python scripts/create_tables.py

Reads DYNAMODB_ENDPOINT, AWS_REGION and TABLE_PREFIX from the environment,
with the same defaults as .env.example. Tables that already exist are left alone.
"""

import os
import time

import boto3

ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT", "http://localhost:8000")
REGION = os.environ.get("AWS_REGION", "us-east-1")
PREFIX = os.environ.get("TABLE_PREFIX", "meetmind_")

# One entry per table from docs/03-architecture.md section 11.
# keys: (partition key, sort key or None). ttl: items carry a "ttl" attribute and expire.
TABLES = {
    "profiles": {"keys": ("userId", None), "ttl": False},
    "sessions": {"keys": ("userId", "sessionId"), "ttl": True},
    "session_items": {"keys": ("sessionId", "sortKey"), "ttl": True},  # sortKey holds "timestamp#type"
    "documents": {"keys": ("userId", "docId"), "ttl": False},
    "prep_cards": {"keys": ("sessionId", "cardId"), "ttl": True},
}


def connect():
    if ENDPOINT:
        # DynamoDB Local accepts any credentials, so we pass dummies and never need real keys.
        return boto3.resource(
            "dynamodb",
            region_name=REGION,
            endpoint_url=ENDPOINT,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    # Real DynamoDB (Phase 4): leave DYNAMODB_ENDPOINT empty, credentials come from the AWS CLI profile.
    return boto3.resource("dynamodb", region_name=REGION)


def create_table(dynamodb, name, partition_key, sort_key):
    key_schema = [{"AttributeName": partition_key, "KeyType": "HASH"}]
    attributes = [{"AttributeName": partition_key, "AttributeType": "S"}]
    if sort_key:
        key_schema.append({"AttributeName": sort_key, "KeyType": "RANGE"})
        attributes.append({"AttributeName": sort_key, "AttributeType": "S"})
    table = dynamodb.create_table(
        TableName=name,
        KeySchema=key_schema,
        AttributeDefinitions=attributes,
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()


def enable_ttl(dynamodb, name):
    dynamodb.meta.client.update_time_to_live(
        TableName=name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )


def round_trip(dynamodb):
    """Write one probe profile, read it back, delete it."""
    profiles = dynamodb.Table(PREFIX + "profiles")
    profiles.put_item(Item={"userId": "probe", "displayName": "probe", "createdAt": int(time.time())})
    item = profiles.get_item(Key={"userId": "probe"}).get("Item", {})
    profiles.delete_item(Key={"userId": "probe"})
    return item.get("displayName") == "probe"


def main():
    dynamodb = connect()
    existing = [table.name for table in dynamodb.tables.all()]
    for short_name, spec in TABLES.items():
        name = PREFIX + short_name
        if name in existing:
            print(f"{name}: already exists")
            continue
        partition_key, sort_key = spec["keys"]
        create_table(dynamodb, name, partition_key, sort_key)
        if spec["ttl"]:
            enable_ttl(dynamodb, name)
        print(f"{name}: created" + (" (ttl on)" if spec["ttl"] else ""))
    print("write and read ok" if round_trip(dynamodb) else "write and read FAILED")


if __name__ == "__main__":
    main()
