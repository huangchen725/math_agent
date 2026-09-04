import json
import subprocess

from evaluation.data.import_putnam_bench import _source_commit, build_benchmark, write_benchmark


def _source_item(year: int, section: str, number: int, *, target: bool, tag: str) -> dict:
    return {
        "problem_name": f"putnam_{year}_{section}{number}",
        "informal_statement": f"Problem {year} {section}{number}",
        "informal_solution": f"Show that the answer is {number}." if target else "None.",
        "tags": [tag],
    }


def test_putnam_import_is_deterministic_and_keeps_questions_out_of_manifest(tmp_path):
    source = tmp_path / "putnam.json"
    rows = []
    tags = ["algebra", "analysis", "geometry"]
    for offset, year in enumerate(range(2000, 2004)):
        for number in range(1, 7):
            rows.append(
                _source_item(
                    year,
                    "a" if offset % 2 == 0 else "b",
                    number,
                    target=(number + offset) % 2 == 0,
                    tag=tags[(number + offset) % len(tags)],
                )
            )
    source.write_text(json.dumps(rows), encoding="utf-8")
    commit = "a" * 40

    first, first_manifest = build_benchmark(
        source,
        source_commit=commit,
        count=12,
        answer_target_count=6,
        seed=42,
    )
    second, second_manifest = build_benchmark(
        source,
        source_commit=commit,
        count=12,
        answer_target_count=6,
        seed=42,
    )

    assert [item["idx"] for item in first] == [item["idx"] for item in second]
    assert sum(item["answer_type"] == "target_with_justification" for item in first) == 6
    assert all(item["grading_mode"] == "manual_blind" for item in first)
    assert first_manifest["selection"] == second_manifest["selection"]
    serialized_manifest = json.dumps(first_manifest)
    assert "Problem 2000" not in serialized_manifest

    output = tmp_path / "benchmark.jsonl"
    manifest_path = tmp_path / "manifest.json"
    write_benchmark(first, first_manifest, output_path=output, manifest_path=manifest_path)
    assert first_manifest["dataset_sha256"]
    assert len(output.read_text(encoding="utf-8").splitlines()) == 12

    recent, recent_manifest = build_benchmark(
        source,
        source_commit=commit,
        count=8,
        answer_target_count=4,
        seed=42,
        recent_from_year=2002,
        recent_count=4,
    )
    assert sum(item["source_year"] >= 2002 for item in recent) == 4
    assert recent_manifest["selection"]["recent_items"] == 4


def test_source_commit_ignores_untracked_file_inside_parent_repository(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Source Test"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "source@example.invalid"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repository, check=True)
    source = repository / "putnam.json"
    source.write_text("[]", encoding="utf-8")

    assert _source_commit(source) is None

    subprocess.run(["git", "add", "putnam.json"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add source"], cwd=repository, check=True)
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert _source_commit(source) == expected
