"""Validate an installed hash lock against another supported Python environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from project_utils import PROJECT_ROOT


LOCKED_REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)==([^ \\;]+)")


def read_lock_versions(path: Path) -> dict[str, str]:
    """Read exact versions from a pip-compile style lock."""
    versions: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line[0].isspace() or line.startswith(("#", "--")):
            continue
        match = LOCKED_REQUIREMENT.match(line)
        if not match:
            raise ValueError(f"{path.name}:{number}: requirement is not exactly pinned")
        name = canonicalize_name(match.group(1))
        if name in versions:
            raise ValueError(f"{path.name}:{number}: duplicate package {name}")
        versions[name] = match.group(2)
    if not versions:
        raise ValueError(f"{path.name}: lock is empty")
    return versions


def target_environment(python_version: str, platform: str) -> dict[str, str]:
    """Build marker values for a supported CPython target."""
    environment = default_environment()
    major, minor = python_version.split(".", 1)
    full_version = f"{major}.{minor}.0"
    environment.update(
        {
            "implementation_name": "cpython",
            "implementation_version": full_version,
            "platform_machine": "x86_64" if platform == "linux" else "AMD64",
            "platform_python_implementation": "CPython",
            "python_full_version": full_version,
            "python_version": python_version,
            "extra": "",
        }
    )
    if platform == "linux":
        environment.update(
            {
                "os_name": "posix",
                "platform_system": "Linux",
                "sys_platform": "linux",
            }
        )
    else:
        environment.update(
            {
                "os_name": "nt",
                "platform_system": "Windows",
                "sys_platform": "win32",
            }
        )
    return environment


def check_requirement_closure(
    locked_versions: Mapping[str, str],
    requirements_by_package: Mapping[str, Sequence[str]],
    environment: Mapping[str, str],
) -> list[str]:
    """Return missing or incompatible dependencies active in the target environment."""
    findings: set[str] = set()
    normalized_versions = {
        canonicalize_name(name): version for name, version in locked_versions.items()
    }
    for package, raw_requirements in requirements_by_package.items():
        source = canonicalize_name(package)
        for raw in raw_requirements:
            try:
                requirement = Requirement(raw)
            except InvalidRequirement:
                findings.add(f"{source}: invalid installed requirement metadata")
                continue
            if requirement.marker and not requirement.marker.evaluate(environment=environment):
                continue
            dependency = canonicalize_name(requirement.name)
            locked = normalized_versions.get(dependency)
            if locked is None:
                findings.add(f"{source}: active dependency {dependency} is missing from lock")
                continue
            try:
                compatible = not requirement.specifier or requirement.specifier.contains(
                    Version(locked),
                    prereleases=True,
                )
            except InvalidVersion:
                compatible = False
            if not compatible:
                findings.add(
                    f"{source}: locked {dependency}=={locked} does not satisfy "
                    f"{requirement.specifier}"
                )
    return sorted(findings)


def installed_requirements(
    locked_versions: Mapping[str, str],
) -> tuple[dict[str, list[str]], list[str]]:
    """Read requirement metadata for the exact distributions installed from the lock."""
    requirements: dict[str, list[str]] = {}
    findings: list[str] = []
    for package, locked in sorted(locked_versions.items()):
        try:
            distribution = importlib.metadata.distribution(package)
        except importlib.metadata.PackageNotFoundError:
            findings.append(f"{package}=={locked} is not installed")
            continue
        if distribution.version != locked:
            findings.append(
                f"{package}: installed {distribution.version}, lock requires {locked}"
            )
        requirements[package] = list(distribution.requires or [])
    return requirements, findings


def check_installed_lock(
    path: Path,
    *,
    python_version: str,
    platform: str,
) -> tuple[int, list[str]]:
    locked_versions = read_lock_versions(path)
    requirements, findings = installed_requirements(locked_versions)
    findings.extend(
        check_requirement_closure(
            locked_versions,
            requirements,
            target_environment(python_version, platform),
        )
    )
    return len(locked_versions), sorted(set(findings))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--python-version", choices=("3.10", "3.12"), required=True)
    parser.add_argument("--platform", choices=("linux", "windows"), required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = args.lock if args.lock.is_absolute() else PROJECT_ROOT / args.lock
    try:
        package_count, findings = check_installed_lock(
            path.resolve(),
            python_version=args.python_version,
            platform=args.platform,
        )
    except (OSError, ValueError) as exc:
        print(f"Lock closure check failed: {exc}")
        raise SystemExit(1) from exc
    if findings:
        print(
            f"Lock closure: FAILED ({args.python_version}/{args.platform}, "
            f"{package_count} packages)"
        )
        for finding in findings:
            print(f"- {finding}")
        raise SystemExit(1)
    print(
        f"Lock closure: OK ({args.python_version}/{args.platform}, "
        f"{package_count} packages)"
    )


if __name__ == "__main__":
    main()
