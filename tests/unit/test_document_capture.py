"""Capturing GraphQL query documents from live browser traffic."""

import json

from utility.graphql_hash_capture import _parse_operation_samples, save_documents


def _body(**overrides):
    payload = {
        "operationName": "SelectPickupFulfillment",
        "variables": {"storeId": 14},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": "abc"}},
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_parser_captures_query_document():
    document = "mutation SelectPickupFulfillment { selectFulfillment { __typename } }"
    (name, sha, variables, query), = _parse_operation_samples(_body(query=document))

    assert name == "SelectPickupFulfillment"
    assert sha == "abc"
    assert variables == {"storeId": 14}
    assert query == document


def test_parser_returns_none_when_document_absent():
    (_, _, _, query), = _parse_operation_samples(_body())
    assert query is None


def test_parser_ignores_blank_document():
    (_, _, _, query), = _parse_operation_samples(_body(query="   "))
    assert query is None


def test_save_documents_merges_and_skips_empty(tmp_path):
    path = tmp_path / "persisted_documents.json"

    save_documents({"A": "query A { x }"}, path=path)
    save_documents({"B": "query B { y }", "C": ""}, path=path)

    saved = json.loads(path.read_text())
    assert saved == {"A": "query A { x }", "B": "query B { y }"}


def test_save_documents_noop_when_nothing_to_save(tmp_path):
    path = tmp_path / "persisted_documents.json"
    assert save_documents({}, path=path) is None
    assert not path.exists()
