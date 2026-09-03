import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from competition_policy import (
    FORMAL_COMPETITION_MODEL,
    FORMAL_COMPETITION_MODELS,
    OFFICIAL_BASELINE_COMMIT,
    OFFICIAL_EVIDENCE_VERIFIED_ON,
    OFFICIAL_EVIDENCE_URLS,
    OFFICIAL_MATERIAL_SHA256,
    OFFICIAL_WEB_EVIDENCE_VERIFIED_ON,
)
from scripts.build_release import (
    REQUIRED_QUALITY_CHECKS,
    ReleaseError,
    build_release,
)
from scripts.project_utils import atomic_write_json, git_snapshot, sha256_file


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _git_bytes(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "math_agent").mkdir(parents=True)
    files = {
        ".gitignore": ".quality/\ndist/\n",
        "ARCHITECTURE.md": "# Architecture\n",
        "docs/COMPETITION_COMPLIANCE.md": "# Compliance\n",
        "docs/ENGINEERING_SPECIFICATION.md": "# Engineering specification\n",
        "docs/OFFICIAL_MATERIALS_REGISTER.md": "# Official materials\n",
        "LICENSE": "All rights reserved.\n",
        "README.md": "# Project\n",
        "math_agent/__init__.py": "class AgentConfig:\n    pass\n",
        "math_agent/competition_policy.py": "FORMAL_COMPETITION_MODEL = 'intern-s1'\n",
        "requirements.lock": "sample==1.0 --hash=sha256:" + "a" * 64 + "\n",
        "requirements-dev.lock": "sample-dev==1.0 --hash=sha256:" + "b" * 64 + "\n",
        "scripts/check_competition_compliance.py": "VALUE = 1\n",
        "user_agent.py": "VALUE = 1\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "config", "user.email", "release@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


def _quality_report(root: Path) -> Path:
    snapshot = git_snapshot(root)
    report = {
        "schema_version": 1,
        "status": "passed",
        "dependency_audit_included": True,
        "code": snapshot,
        "worktree_after": snapshot,
        "checks": [
            {"name": name, "status": "passed"}
            for name in sorted(REQUIRED_QUALITY_CHECKS)
        ],
    }
    path = root / ".quality" / "quality-report.json"
    atomic_write_json(path, report)
    return path


def test_formal_release_is_deterministic_and_contains_provenance(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)

    first, first_digest, first_manifest = build_release(
        root,
        root / "dist",
        quality,
        model=FORMAL_COMPETITION_MODEL,
        name="first",
    )
    second, _, second_manifest = build_release(
        root,
        root / "dist",
        quality,
        model=FORMAL_COMPETITION_MODEL,
        name="second",
    )

    assert first_manifest["status"] == second_manifest["status"] == "formal"
    assert first_manifest["source"]["commit"] == git_snapshot(root)["commit"]
    assert sha256_file(first) == sha256_file(second)
    assert first_digest.read_text(encoding="ascii").startswith(sha256_file(first))
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "release/release-manifest.json" in names
        assert "release/quality-report.json" in names
        assert not any(name.endswith(".env") or name.startswith("outputs/") for name in names)
        manifest = json.loads(archive.read("release/release-manifest.json"))
        assert manifest["quality"]["status"] == "passed"
        assert manifest["competition"]["official_materials_sha256"] == dict(
            OFFICIAL_MATERIAL_SHA256
        )
        assert (
            manifest["competition"]["official_baseline_commit"]
            == OFFICIAL_BASELINE_COMMIT
        )
        assert manifest["competition"]["official_evidence_urls"] == dict(
            OFFICIAL_EVIDENCE_URLS
        )
        assert manifest["competition"]["official_evidence_verified_on"] == dict(
            OFFICIAL_EVIDENCE_VERIFIED_ON
        )
        assert (
            manifest["competition"]["official_web_evidence_verified_on"]
            == OFFICIAL_WEB_EVIDENCE_VERIFIED_ON
        )
        assert manifest["competition"]["formal_models_allowed"] == sorted(
            FORMAL_COMPETITION_MODELS
        )
        assert archive.read("README.md") == _git_bytes(root, "show", "HEAD:README.md")
        readme_record = next(item for item in manifest["files"] if item["path"] == "README.md")
        assert readme_record["bytes"] == len(archive.read("README.md"))
        assert len({entry.date_time for entry in archive.infolist()}) == 1


def test_formal_release_refuses_dirty_tree_and_draft_is_marked(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)
    (root / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ReleaseError, match="clean Git worktree"):
        build_release(root, root / "dist", quality, model=FORMAL_COMPETITION_MODEL)

    archive, _, manifest = build_release(
        root,
        root / "dist",
        quality,
        model=FORMAL_COMPETITION_MODEL,
        allow_dirty=True,
    )
    assert archive.is_file()
    assert manifest["status"] == "draft"
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.read("README.md") == (root / "README.md").read_bytes()


def test_formal_release_requires_complete_quality_evidence(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    snapshot = git_snapshot(root)
    quality = root / ".quality" / "quality-report.json"
    atomic_write_json(
        quality,
        {
            "status": "passed",
            "dependency_audit_included": False,
            "code": snapshot,
            "worktree_after": snapshot,
            "checks": [],
        },
    )

    with pytest.raises(ReleaseError, match="dependency audit"):
        build_release(root, root / "dist", quality, model=FORMAL_COMPETITION_MODEL)


def test_draft_release_scans_untracked_source_for_secrets(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)
    token = "sk-" + "B" * 24
    (root / "math_agent" / "unsafe.py").write_text(
        f'TOKEN = "{token}"\n',
        encoding="utf-8",
    )

    with pytest.raises(ReleaseError, match="failed secret scan") as error:
        build_release(
            root,
            root / "dist",
            quality,
            model=FORMAL_COMPETITION_MODEL,
            allow_dirty=True,
        )
    assert token not in str(error.value)


def test_draft_release_rejects_unscannable_source(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)
    (root / "math_agent" / "unscannable.py").write_bytes(b"\0binary")

    with pytest.raises(ReleaseError, match="binary content"):
        build_release(
            root,
            root / "dist",
            quality,
            model=FORMAL_COMPETITION_MODEL,
            allow_dirty=True,
        )


def test_draft_release_scans_embedded_quality_report(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)
    report = json.loads(quality.read_text(encoding="utf-8"))
    token = "sk-" + "C" * 24
    report["diagnostic"] = token
    atomic_write_json(quality, report)

    with pytest.raises(ReleaseError, match="quality report failed secret scan") as error:
        build_release(
            root,
            root / "dist",
            quality,
            model=FORMAL_COMPETITION_MODEL,
            allow_dirty=True,
        )
    assert token not in str(error.value)


def test_draft_release_excludes_gitignored_source(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)
    ignored = root / "math_agent" / "private.py"
    ignored.write_text("TOKEN = 'private local material'\n", encoding="utf-8")
    with (root / ".gitignore").open("a", encoding="utf-8") as file:
        file.write("math_agent/private.py\n")

    archive, _, _ = build_release(
        root,
        root / "dist",
        quality,
        model=FORMAL_COMPETITION_MODEL,
        allow_dirty=True,
    )

    with zipfile.ZipFile(archive) as zipped:
        assert "math_agent/private.py" not in zipped.namelist()


def test_release_rejects_external_quality_report(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    external = tmp_path / "quality.json"
    external.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ReleaseError, match="inside the repository"):
        build_release(
            root,
            root / "dist",
            external,
            model=FORMAL_COMPETITION_MODEL,
            allow_dirty=True,
        )


def test_release_name_cannot_escape_output_directory(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)

    with pytest.raises(ReleaseError, match="release name"):
        build_release(
            root,
            root / "dist",
            quality,
            model=FORMAL_COMPETITION_MODEL,
            name="../escape",
        )


def test_formal_release_accepts_documented_s2_and_rejects_unknown_model(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    quality = _quality_report(root)

    _, _, s2_manifest = build_release(
        root,
        root / "dist",
        quality,
        model="intern-s2-preview",
        name="documented-s2",
    )
    assert s2_manifest["status"] == "formal"
    assert s2_manifest["competition"]["formal_model_match"] is True

    with pytest.raises(ReleaseError, match="documented Intern-S model"):
        build_release(root, root / "dist", quality, model="unrelated-model")

    _, _, manifest = build_release(
        root,
        root / "dist",
        quality,
        model="unrelated-model",
        allow_dirty=True,
        name="unknown-draft",
    )
    assert manifest["status"] == "draft"
    assert manifest["competition"]["formal_model_match"] is False
