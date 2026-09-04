"""Deterministic preflight for repository hard-rule triggers.

This tool reports which policy IDs a task touches and blocks locally detectable
violations. It does not replace human review or official evidence.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".agents" / "policies" / "policy_manifest.json"


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str
    path: str = ""


def _normalize_path(value: str | Path) -> str:
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            return path.as_posix()
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def load_manifest() -> dict:
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def changed_paths() -> list[str]:
    tracked = _git("diff", "--name-only", "HEAD").stdout.splitlines()
    untracked = _git("ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return sorted({_normalize_path(path) for path in [*tracked, *untracked] if path.strip()})


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(Path(path).name, pattern)


def triggered_rules(paths: Iterable[str], manifest: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for raw_path in paths:
        path = _normalize_path(raw_path)
        rules: set[str] = set(manifest.get("always_rules", []))
        for surface in manifest["surface_rules"]:
            if any(_matches(path, pattern) for pattern in surface["patterns"]):
                rules.update(surface["rules"])
        if rules:
            result[path] = rules
    return result


def triggered_actions(actions: Iterable[str], manifest: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    always = set(manifest.get("always_rules", []))
    for action in actions:
        result[f"action:{action}"] = always.union(manifest["action_rules"][action])
    return result


def _is_runtime_path(path: str, manifest: dict) -> bool:
    normalized = _normalize_path(path)
    name = Path(normalized).name
    if normalized in manifest["runtime_files"]:
        return True
    if "/" not in normalized and name.startswith(manifest["project_prefix"]) and name.endswith(".py"):
        return True
    return False


def _anchor_contains(path: str, manifest: dict) -> bool:
    proc = _git(
        "cat-file",
        "-e",
        f"{manifest['anchor_commit']}:{_normalize_path(path)}",
        check=False,
    )
    return proc.returncode == 0


def _validate_policy_files(manifest: dict) -> list[Finding]:
    findings: list[Finding] = []
    required_rules = set(manifest["required_rule_ids"])
    referenced_rules = set(manifest.get("always_rules", []))
    referenced_rules.update(
        rule for surface in manifest["surface_rules"] for rule in surface["rules"]
    )
    referenced_rules.update(
        rule for rules in manifest["action_rules"].values() for rule in rules
    )
    referenced_rules.update(item["rule"] for item in manifest["forbidden_runtime_patterns"])
    unknown_rules = sorted(referenced_rules.difference(required_rules))
    if unknown_rules:
        findings.append(
            Finding("POLICY-001", f"Manifest references undeclared rules: {', '.join(unknown_rules)}")
        )
    spec_path = ROOT / manifest["authoritative_spec"]
    if not spec_path.is_file():
        return [Finding("POLICY-001", "Authoritative engineering specification is missing.")]
    spec = spec_path.read_text(encoding="utf-8")
    for rule_id in required_rules:
        if rule_id not in spec:
            findings.append(
                Finding("POLICY-001", f"Required rule ID {rule_id} is missing from the specification.")
            )
    protocol = ROOT / manifest["human_protocol"]
    if not protocol.is_file():
        findings.append(Finding("POLICY-001", "Human trigger protocol is missing."))
    integration = manifest["agent_integration"]
    root_agent = ROOT / integration["root_file"]
    if not root_agent.is_file():
        findings.append(Finding("POLICY-001", "Root agent instructions are missing."))
    else:
        root_text = root_agent.read_text(encoding="utf-8")
        for token in integration["root_tokens"]:
            if token not in root_text:
                findings.append(
                    Finding("POLICY-001", f"Root agent instructions are missing token: {token}")
                )
    for overlay in manifest["required_skill_overlays"]:
        overlay_path = ROOT / overlay
        if not overlay_path.is_file():
            findings.append(Finding("SKILL-001", f"Required skill policy overlay is missing: {overlay}"))
            continue
        overlay_text = overlay_path.read_text(encoding="utf-8")
        for token in integration["overlay_tokens"]:
            if token not in overlay_text:
                findings.append(
                    Finding("SKILL-001", f"Skill overlay {overlay} is missing token: {token}")
                )
    skill_root = ROOT / ".agents" / "skills"
    for skill_file in skill_root.glob("*/SKILL.md"):
        overlay_path = skill_file.parent / "PROJECT_POLICY.md"
        if not overlay_path.is_file():
            findings.append(
                Finding(
                    "SKILL-001",
                    f"Skill {skill_file.parent.relative_to(ROOT).as_posix()} has no PROJECT_POLICY.md.",
                )
            )
        skill_text = skill_file.read_text(encoding="utf-8")
        for token in integration["skill_tokens"]:
            if token not in skill_text:
                findings.append(
                    Finding(
                        "SKILL-001",
                        f"Skill {skill_file.relative_to(ROOT).as_posix()} is missing token: {token}",
                    )
                )
    return findings


def _scan_python(path: str, manifest: dict) -> list[Finding]:
    full_path = ROOT / path
    if not full_path.is_file():
        return []
    try:
        text = full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [Finding("SECURITY-001", "Runtime source is not valid UTF-8.", path)]

    return scan_python_text(path, text, manifest)


def scan_python_text(path: str, text: str, manifest: dict) -> list[Finding]:
    """Audit formal Python source supplied by tests or the working tree."""

    findings: list[Finding] = []
    for item in manifest["forbidden_runtime_patterns"]:
        if re.search(item["pattern"], text):
            findings.append(Finding(item["rule"], item["message"], path))

    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return [*findings, Finding("SECURITY-001", f"Python syntax error: {exc.msg}", path)]

    if path == "user_agent.py" and not any(
        isinstance(node, ast.ClassDef) and node.name == "ReasoningAgent" for node in tree.body
    ):
        findings.append(
            Finding("ENTRY-001", "Root user_agent.py must physically declare ReasoningAgent.", path)
        )

    allowed_keywords = {"messages", "temperature", "max_tokens"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "chat":
            continue
        keyword_names = {keyword.arg for keyword in node.keywords}
        if None in keyword_names:
            findings.append(
                Finding("CLIENT-001", "Dynamic **kwargs are forbidden in formal client.chat calls.", path)
            )
        extras = sorted(name for name in keyword_names if name and name not in allowed_keywords)
        if extras:
            findings.append(
                Finding(
                    "CLIENT-001",
                    f"Formal client.chat call contains extra keywords: {', '.join(extras)}.",
                    path,
                )
            )
    return findings


def evaluate(
    paths: Iterable[str],
    manifest: dict,
    *,
    planned: bool = False,
    formal: bool = False,
    actions: Iterable[str] = (),
) -> tuple[dict[str, set[str]], list[Finding]]:
    normalized = sorted({_normalize_path(path) for path in paths if str(path).strip()})
    triggers = triggered_rules(normalized, manifest)
    triggers.update(triggered_actions(actions, manifest))
    blockers = _validate_policy_files(manifest)
    runtime_paths = [path for path in normalized if _is_runtime_path(path, manifest)]

    if manifest["phase"] == "R0" and runtime_paths:
        blockers.append(
            Finding(
                "ANCHOR-001",
                "R0 freezes the scored runtime; change the documented phase only after the official anchor result.",
                ", ".join(runtime_paths),
            )
        )

    if formal and manifest["phase"] == "R0":
        blockers.append(
            Finding(
                "ANCHOR-001",
                "A changed formal release is blocked during R0; only --anchor-canary is allowed.",
            )
        )

    for path in normalized:
        candidate = Path(path)
        if candidate.parent == Path(".") and candidate.suffix == ".py":
            if (
                candidate.stem in manifest["generic_module_stems"]
                and not _anchor_contains(path, manifest)
            ):
                blockers.append(
                    Finding(
                        "IMPORT-001",
                        f"New generic top-level module name is forbidden; use {manifest['project_prefix']}*.",
                        path,
                    )
                )

    if not planned and (manifest["phase"] != "R0" or formal):
        for path in runtime_paths:
            blockers.extend(_scan_python(path, manifest))

    topology_changed = "ARCHITECTURE.md" in normalized or any(
        path.endswith(".py") and not _anchor_contains(path, manifest) for path in normalized
    )
    strategy_paths = {
        "domain_prompts.py",
        "math_tools.py",
        "deterministic_verifier.py",
        "answer_equivalence.py",
    }
    if topology_changed and strategy_paths.intersection(normalized):
        blockers.append(
            Finding(
                "CHANGE-001",
                "Architecture/topology and mathematical strategy changed together.",
            )
        )

    if runtime_paths and not planned:
        required_docs = {"ARCHITECTURE.md", "README.md", manifest["authoritative_spec"]}
        missing = sorted(required_docs.difference(normalized))
        if missing:
            blockers.append(
                Finding(
                    "DOC-001",
                    f"Runtime changes must update recovery controls and architecture docs: {', '.join(missing)}.",
                )
            )

    unique = {(item.rule, item.message, item.path): item for item in blockers}
    return triggers, sorted(unique.values(), key=lambda item: (item.rule, item.path, item.message))


def _anchor_canary(manifest: dict) -> list[Finding]:
    proc = _git(
        "diff",
        "--exit-code",
        manifest["anchor_commit"],
        "--",
        *manifest["runtime_files"],
        check=False,
    )
    if proc.returncode != 0:
        return [
            Finding(
                "ANCHOR-001",
                "Active runtime no longer matches the scored anchor; canary submission is blocked.",
            )
        ]
    return _validate_policy_files(manifest)


def _print_report(
    mode: str,
    manifest: dict,
    paths: Iterable[str],
    triggers: dict[str, set[str]],
    blockers: list[Finding],
) -> None:
    print(f"policy_version={manifest['policy_version']} phase={manifest['phase']} mode={mode}")
    normalized = list(paths)
    if normalized:
        print("paths=" + ",".join(normalized))
    all_rules = sorted(
        set(manifest.get("always_rules", [])).union(
            rule for values in triggers.values() for rule in values
        )
    )
    print("triggered_rules=" + (",".join(all_rules) if all_rules else "none"))
    for path, rules in sorted(triggers.items()):
        print(f"trigger[{path}]={','.join(sorted(rules))}")
    if blockers:
        print("status=BLOCKED")
        for item in blockers:
            location = f" path={item.path}" if item.path else ""
            print(f"[POLICY BLOCK] {item.rule}{location}: {item.message}")
    else:
        print("status=PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--changed", action="store_true", help="Audit current Git changes.")
    modes.add_argument("--anchor-canary", action="store_true", help="Verify the frozen anchor runtime.")
    modes.add_argument("--formal", action="store_true", help="Audit all formal runtime files.")
    parser.add_argument("--paths", nargs="+", help="Planned repository-relative paths.")
    parser.add_argument(
        "--actions",
        nargs="+",
        choices=sorted(load_manifest()["action_rules"]),
        help="Planned side-effecting or policy-sensitive actions.",
    )
    args = parser.parse_args(argv)
    manifest = load_manifest()

    selected_mode = args.changed or args.anchor_canary or args.formal
    if selected_mode and (args.paths or args.actions):
        parser.error("--changed/--anchor-canary/--formal cannot be combined with --paths/--actions")
    if not selected_mode and not (args.paths or args.actions):
        parser.error("provide --paths and/or --actions, or select an audit mode")

    if args.anchor_canary:
        blockers = _anchor_canary(manifest)
        _print_report("anchor-canary", manifest, manifest["runtime_files"], {}, blockers)
        return 2 if blockers else 0

    if args.formal:
        paths = list(manifest["runtime_files"])
        triggers, blockers = evaluate(paths, manifest, formal=True)
        _print_report("formal", manifest, paths, triggers, blockers)
        return 2 if blockers else 0

    if args.changed:
        paths = changed_paths()
        triggers, blockers = evaluate(paths, manifest)
        _print_report("changed", manifest, paths, triggers, blockers)
        return 2 if blockers else 0

    paths = sorted({_normalize_path(path) for path in (args.paths or [])})
    actions = sorted(set(args.actions or []))
    triggers, blockers = evaluate(paths, manifest, planned=True, actions=actions)
    _print_report("planned", manifest, paths, triggers, blockers)
    return 2 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
