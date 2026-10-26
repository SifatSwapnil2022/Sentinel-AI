"""Check every JSON file of the Power BI project against Microsoft's published schemas.

Usage:
    git clone --depth 1 https://github.com/microsoft/json-schemas.git /tmp/json-schemas
    uv run --with jsonschema python bi/validate_powerbi.py /tmp/json-schemas

TMDL has no JSON schema; Power BI Desktop is the check for the semantic model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource

BASE = "https://developer.microsoft.com/json-schemas/"
PROJECT = Path(__file__).resolve().parent / "powerbi"


def main(schemas: Path) -> int:
    def local(uri: str) -> Path:
        return schemas / uri.removeprefix(BASE).split("#")[0]

    registry = Registry(
        retrieve=lambda uri: Resource.from_contents(json.loads(local(uri).read_text()))
    )
    failures = 0
    files = sorted(
        p for p in PROJECT.rglob("*") if p.suffix in {".json", ".pbir", ".pbism", ".pbip"}
    )
    for path in files:
        doc = json.loads(path.read_text())
        validator = Draft7Validator(
            json.loads(local(doc["$schema"]).read_text()), registry=registry
        )
        for error in validator.iter_errors(doc):
            failures += 1
            print(f"{path.relative_to(PROJECT)}: {'/'.join(map(str, error.path))}: {error.message}")
    print(f"{len(files)} files, {failures} problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
