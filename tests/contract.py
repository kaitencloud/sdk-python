# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The contract snapshots as test tooling: operations, write-side validation, sample payloads."""

from __future__ import annotations

import copy
import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from helpers import Handler
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parent.parent
SPECS = {
    "core": ROOT / "openapi" / "openapi.yaml",
    "platform": ROOT / "openapi" / "platform-openapi.yaml",
}
HTTP_METHODS = ("get", "put", "post", "patch", "delete")

SAMPLE_TIME = "2026-09-14T12:00:00Z"
SAMPLE_UUID = "3f6b1a2c-7c1e-4d0b-9d5f-2b0a1c4e8d31"


@functools.cache
def document(surface: str) -> dict[str, Any]:
    return yaml.safe_load(SPECS[surface].read_text(encoding="utf-8"))


@functools.cache
def coverage() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "openapi" / "coverage.yaml").read_text(encoding="utf-8"))


@dataclass(frozen=True, eq=False)
class Operation:
    surface: str
    method: str
    path: str
    operation_id: str
    definition: dict[str, Any]

    @property
    def pattern(self) -> re.Pattern[str]:
        segments = [
            "[^/]+" if segment.startswith("{") and segment.endswith("}") else re.escape(segment)
            for segment in self.path.split("/")
        ]
        return re.compile("^" + "/".join(segments) + "$")

    @property
    def query_parameters(self) -> set[str]:
        return {
            parameter["name"]
            for parameter in self.definition.get("parameters", [])
            if parameter.get("in") == "query"
        }

    @property
    def request_schema(self) -> dict[str, Any] | None:
        content = (self.definition.get("requestBody") or {}).get("content") or {}
        media = content.get("application/json")
        return media["schema"] if media else None

    def success(self) -> tuple[int, dict[str, Any] | None]:
        """The operation's first success status, and the schema of its body if it has one."""
        for code in sorted(self.definition["responses"]):
            if code.startswith("2"):
                media = (self.definition["responses"][code].get("content") or {}).get(
                    "application/json"
                )
                return int(code), (media["schema"] if media else None)
        raise AssertionError(f"{self.operation_id} declares no success response")


@functools.cache
def operations(surface: str) -> tuple[Operation, ...]:
    found = [
        Operation(surface, method.upper(), path, item[method]["operationId"], item[method])
        for path, item in document(surface)["paths"].items()
        for method in HTTP_METHODS
        if method in item
    ]
    # Literal paths before templated ones, so /metadata-fields/reorder never reads as an id.
    return tuple(sorted(found, key=lambda operation: operation.path.count("{")))


def find_operation(surface: str, method: str, url_path: str) -> Operation:
    """The operation a request addresses, from its method and its path under ``/api``."""
    assert url_path.startswith("/api/"), f"{url_path} is not under /api/"
    relative = url_path[len("/api") :]
    for operation in operations(surface):
        if operation.method == method and operation.pattern.match(relative):
            return operation
    raise AssertionError(f"{method} {url_path} is no operation of the {surface} contract")


def write_errors(surface: str, schema: dict[str, Any], body: Any) -> list[str]:
    """Why the API would refuse ``body`` as a request against ``schema``: empty when it would not."""
    validator = Draft202012Validator(
        {"$ref": f"urn:kaiten:{surface}{schema['$ref']}"}, registry=_write_registry(surface)
    )
    return sorted(
        f"{'/'.join(map(str, error.absolute_path)) or '<body>'}: {error.message}"
        for error in validator.iter_errors(body)
    )


@functools.cache
def _write_registry(surface: str) -> Registry:
    """The contract as a JSON Schema resource, with the write-side rules applied.

    The API validates a request against the resource schema with its readOnly properties no
    longer required -- and a client has no business sending one -- so readOnly properties are
    dropped outright. Every body is ``additionalProperties: false``, so a request carrying one
    then fails exactly like a misspelled key.
    """
    writable = _without_read_only(copy.deepcopy(document(surface)))
    resource = Resource.from_contents(writable, default_specification=DRAFT202012)
    return Registry().with_resource(f"urn:kaiten:{surface}", resource)


def _without_read_only(node: Any) -> Any:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            read_only = {
                name
                for name, schema in properties.items()
                if isinstance(schema, dict) and schema.get("readOnly")
            }
            for name in read_only:
                del properties[name]
            if isinstance(node.get("required"), list):
                node["required"] = [name for name in node["required"] if name not in read_only]
        for value in node.values():
            _without_read_only(value)
    elif isinstance(node, list):
        for value in node:
            _without_read_only(value)
    return node


def sample(
    schema: Any, surface: str, *, full: bool = True, seen: frozenset[str] = frozenset()
) -> Any:
    """A value ``schema`` describes: with every property when ``full``, only required ones otherwise."""
    if not isinstance(schema, dict):
        return "anything"
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return None
        target = document(surface)["components"]["schemas"][name]
        return sample(target, surface, full=full, seen=seen | {name})
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return sample(schema[key][0], surface, full=full, seen=seen)
    if schema.get("enum"):
        return schema["enum"][0]

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), None)
    if kind is None and "properties" in schema:
        kind = "object"

    if kind == "string":
        return {"date-time": SAMPLE_TIME, "uuid": SAMPLE_UUID, "uri": "https://kaiten.test/p"}.get(
            schema.get("format", ""), "sample"
        )
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        # False, so a sampled page never claims more rows than it holds.
        return False
    if kind == "array":
        return [sample(schema.get("items"), surface, full=full, seen=seen)] if full else []
    if kind == "object":
        properties: dict[str, Any] = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        value = {
            name: sample(node, surface, full=full, seen=seen)
            for name, node in properties.items()
            if full or name in required
        }
        extra = schema.get("additionalProperties")
        if not properties and full:
            value["key"] = (
                sample(extra, surface, full=full, seen=seen)
                if isinstance(extra, dict) and extra
                else "value"
            )
        return value
    return "anything"


def contract_api(surface: str) -> Handler:
    """A fake API answering every operation the way the contract describes it."""

    def handler(request: httpx.Request) -> httpx.Response:
        operation = find_operation(surface, request.method, request.url.path)
        status, schema = operation.success()
        if schema is None:
            return httpx.Response(status)
        return httpx.Response(status, json=sample(schema, surface))

    return handler
