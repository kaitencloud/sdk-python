# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The README's examples are valid Python, everything they call exists, and its links resolve.

A README is the first code a user copies. These tests keep it from drifting away from the SDK:
every ``python`` block must parse, every name it imports from ``kaitencloud`` must exist, and
every ``client.x.y()`` / ``platform.x.y()`` call must name a real method. What surrounds the
examples is held to the same rule: the error tree, and the API reference's namespaces and
methods, name only what the package has. The links of both READMEs -- this one and
``examples/README.md``, which it hands the playbook over to -- must point at a file that exists
and a heading that is really there.
"""

from __future__ import annotations

import ast
import importlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers import BASE_URL, PLATFORM_URL

import kaitencloud
from kaitencloud import KaitenClient, KaitenPlatformClient, targeting, usage

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
MARKDOWN = {
    path: path.read_text(encoding="utf-8")
    for path in (ROOT / "README.md", ROOT / "examples" / "README.md", ROOT / "CONTRIBUTING.md")
}
LINK = re.compile(r"\[[^\]]+\]\((?!https?:)([^)#]*)(#[^)]+)?\)")
EXAMPLES = re.findall(r"```python\n(.*?)```", README, flags=re.DOTALL)
CLIENT_CALL = re.compile(r"\b(client|platform)\.(\w+)(?:\.(\w+))?\(")
HELPER_CALL = re.compile(r"\b(targeting|usage)\.(\w+)\(")
ENVIRONMENT_ASSUMED = "With `KAITEN_BASE_URL` and `KAITEN_AUTH_TOKEN` set"


@pytest.fixture
def clients() -> Iterator[dict[str, object]]:
    core = KaitenClient(token="ksh_readme", base_url=BASE_URL)
    platform = KaitenPlatformClient(token="ksm_readme", base_url=PLATFORM_URL)
    yield {"client": core, "platform": platform}
    core.close()
    platform.close()


def test_the_readme_shows_real_code() -> None:
    assert len(EXAMPLES) >= 10


@pytest.mark.parametrize(
    "example", EXAMPLES, ids=[f"example-{n + 1}" for n in range(len(EXAMPLES))]
)
def test_every_example_is_valid_python(example: str) -> None:
    ast.parse(example)


def test_every_import_from_the_sdk_exists() -> None:
    for example in EXAMPLES:
        for node in ast.walk(ast.parse(example)):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("kaitencloud"):
                module = importlib.import_module(str(node.module))
                for alias in node.names:
                    assert hasattr(module, alias.name), f"from {node.module} import {alias.name}"


def test_every_client_call_names_a_real_method(clients: dict[str, object]) -> None:
    calls = [call for example in EXAMPLES for call in CLIENT_CALL.findall(example)]
    assert calls
    for owner, attribute, method in calls:
        target = getattr(clients[owner], attribute)
        if method:
            target = getattr(target, method)
        assert callable(target), f"{owner}.{attribute}.{method}"


def test_every_helper_call_names_a_real_function() -> None:
    modules = {"targeting": targeting, "usage": usage}
    for example in EXAMPLES:
        for module, function in HELPER_CALL.findall(example):
            assert callable(getattr(modules[module], function)), f"{module}.{function}"


def test_the_first_examples_name_the_api_address() -> None:
    """An example shown before the environment is assumed passes ``base_url``.

    There is no default address, so without it the first line a reader copies raises.
    """
    standalone, sentence, _ = README.partition(ENVIRONMENT_ASSUMED)
    assert sentence, "the README no longer says where it starts assuming the environment"
    built = [
        node
        for example in re.findall(r"```python\n(.*?)```", standalone, flags=re.DOTALL)
        for node in ast.walk(ast.parse(example))
        if isinstance(node, ast.Call) and getattr(node.func, "id", "").endswith("KaitenClient")
    ]
    assert built
    for call in built:
        assert {"base_url", "token"} <= {keyword.arg for keyword in call.keywords}


def test_the_error_tree_names_real_exceptions() -> None:
    tree = re.search(r"```text\nKaitenError\n(.*?)```", README, flags=re.DOTALL)
    assert tree is not None
    names = re.findall(r"── (\w+)", tree.group(1))
    assert names
    for name in names:
        error = getattr(kaitencloud, name, None)
        assert isinstance(error, type), name
        assert issubclass(error, kaitencloud.KaitenError), name


def test_the_api_reference_names_real_namespaces_and_methods(clients: dict[str, object]) -> None:
    """The reference is tables rather than ``python`` blocks, so the checks above skip it."""
    reference = README[README.index("\n## API reference") : README.index("\n## How the SDK stays")]
    namespaces = re.findall(r"<b>(client|platform)\.(\w+)</b>", reference)
    calls = CLIENT_CALL.findall(reference)
    assert namespaces
    assert calls
    for owner, attribute in namespaces:
        assert hasattr(clients[owner], attribute), f"{owner}.{attribute}"
    for owner, attribute, method in calls:
        target = getattr(clients[owner], attribute)
        if method:
            target = getattr(target, method)
        assert callable(target), f"{owner}.{attribute}.{method}"


def anchors(text: str) -> set[str]:
    """The fragments GitHub derives from a document's headings."""
    found = set()
    for heading in re.findall(r"^#+ +(.+?)\s*$", text, flags=re.MULTILINE):
        slug = re.sub(r"[^\w -]", "", heading.replace("`", "").lower()).strip()
        found.add("#" + slug.replace(" ", "-"))
    return found


@pytest.mark.parametrize("source", MARKDOWN, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_link_points_at_something_that_exists(source: Path) -> None:
    for target, fragment in LINK.findall(MARKDOWN[source]):
        destination = (source.parent / target).resolve() if target else source
        assert destination.exists(), f"{source.name}: {target} does not exist"
        if fragment and destination.suffix == ".md":
            text = MARKDOWN.get(destination) or destination.read_text(encoding="utf-8")
            assert fragment in anchors(text), f"{source.name}: {target}{fragment} has no heading"
