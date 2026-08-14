"""Self-registering persisted queries.

HEB runs Automatic Persisted Queries. When an operation's hash falls out of
their cache the server answers PersistedQueryNotFound forever, and previously
that was fatal. Capturing the query document lets the client re-register it
under a hash it computes itself, which survives HEB's hash rotation.
"""

import hashlib

from auto_grocier_mcp.clients import graphql as gql


def test_document_payload_uses_self_computed_hash():
    document = "mutation Probe { selectFulfillment { __typename } }"
    gql.PERSISTED_DOCUMENTS["Probe"] = document
    try:
        payload = gql._document_registration_payload("Probe", {"a": 1})
    finally:
        gql.PERSISTED_DOCUMENTS.pop("Probe", None)

    assert payload is not None
    assert payload["query"] == document
    assert payload["variables"] == {"a": 1}
    expected = hashlib.sha256(document.encode()).hexdigest()
    assert payload["extensions"]["persistedQuery"]["sha256Hash"] == expected


def test_document_payload_none_without_document():
    gql.PERSISTED_DOCUMENTS.pop("Missing", None)
    assert gql._document_registration_payload("Missing", {}) is None


def test_detects_persisted_query_miss():
    errors = [{"message": "PersistedQueryNotFound", "extensions": {"code": "X"}}]
    assert gql._has_persisted_query_miss(errors) is True
    assert gql._has_persisted_query_miss([{"message": "Something else"}]) is False


def test_document_overrides_load_from_file(tmp_path, monkeypatch):
    import json

    path = tmp_path / "persisted_documents.json"
    path.write_text(json.dumps({"Op": "query Op { __typename }"}))
    monkeypatch.setenv("GRAPHQL_DOCUMENTS_PATH", str(path))

    gql.PERSISTED_DOCUMENTS.pop("Op", None)
    gql._load_persisted_document_overrides()
    try:
        assert gql.PERSISTED_DOCUMENTS["Op"] == "query Op { __typename }"
    finally:
        gql.PERSISTED_DOCUMENTS.pop("Op", None)
