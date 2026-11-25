"""Offline configuration checks; these do not prove an inference used a model."""

import argparse
import json
from pathlib import Path
import sys
import tomllib


EXPECTED = {
    "member_experience": ("gpt-6.2-astra", "high"),
    "matchmaking": ("gpt-6.2-astra", "high"),
    "growth": ("gpt-6.2-sol", "high"),
    "content": ("gpt-6.2-sol", "low"),
    "verification": ("gpt-6.2-astra", "xhigh"),
}
AGENT_KEYS = {
    "name", "description", "model", "model_reasoning_effort", "developer_instructions"
}


def validate(root, catalog_path=None):
    errors = []
    config = tomllib.loads((root / ".codex/config.toml").read_text())
    agents = config.get("agents", {})
    if agents.get("enabled") is not True:
        errors.append("agents.enabled must be true")
    cap = agents.get("max_concurrent_threads_per_session")
    if type(cap) is not int or cap != 3:
        errors.append("agents.max_concurrent_threads_per_session must be integer 3")
    if set(agents) != {"enabled", "max_concurrent_threads_per_session"}:
        errors.append("Unexpected agents keys: review against the current official schema")
    if set(config) != {"agents"}:
        errors.append("Project config must preserve parent model/permissions/provider defaults")
    paths = sorted((root / ".codex/agents").glob("*.toml"))
    if {p.stem for p in paths} != set(EXPECTED):
        errors.append("Expected exactly the five named project agent files")
    seen = set()
    for path in paths:
        agent = tomllib.loads(path.read_text())
        name = agent.get("name")
        if name != path.stem or name in seen or name not in EXPECTED:
            errors.append(f"{path.name}: unknown, duplicate or mismatched name")
            continue
        seen.add(name)
        if set(agent) != AGENT_KEYS:
            errors.append(f"{name}: unexpected or missing agent keys")
        for key in AGENT_KEYS:
            if not isinstance(agent.get(key), str) or not agent[key].strip():
                errors.append(f"{name}: {key} must be nonempty text")
        expected = EXPECTED[name]
        actual = (agent.get("model"), agent.get("model_reasoning_effort"))
        if actual != expected:
            errors.append(f"{name}: model/effort {actual!r}, expected {expected!r}")
        print(f"{name}: {actual[0]} / {actual[1]}")
    if catalog_path:
        catalog = json.loads(catalog_path.read_text())
        models = {m["slug"]: m for m in catalog["models"]}
        for model, effort in set(EXPECTED.values()):
            levels = {
                item["effort"]
                for item in models.get(model, {}).get("supported_reasoning_levels", [])
            }
            if effort not in levels:
                errors.append(f"Catalog does not list {model} / {effort}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model-catalog", type=Path, help="JSON from codex debug models")
    args = parser.parse_args()
    try:
        errors = validate(args.root, args.model_catalog)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = [str(exc)]
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("PASS: static configuration only; runtime model/effort still require evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
