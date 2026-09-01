from pathlib import Path

from scripts.build_release import REQUIRED_RELEASE_FILES


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "ENGINEERING_SPECIFICATION.md"


def test_engineering_specification_freezes_p1_through_s6_baseline() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "不是第二份架构文档" in text
    for stage, commit in {
        "P1": "a0df6d0",
        "S1": "3ba0610",
        "S2": "13fb638",
        "S3": "70ac53f",
        "S4": "70ac53f",
        "S5": "3cbd587",
        "S6": "3cbd587",
    }.items():
        assert f"| {stage} |" in text
        assert commit in text

    for rule in (
        "COMP-001",
        "API-001",
        "OUT-001",
        "TRUNC-001",
        "VER-001",
        "ARC-001",
        "TOOL-001",
        "RUN-001",
        "EVAL-001",
        "DEP-001",
        "QUAL-001",
        "REL-001",
        "VCS-001",
    ):
        assert f"**{rule}**" in text


def test_known_problem_registry_preserves_open_evidence_boundaries() -> None:
    rows = {
        line.split("|", 2)[1].strip(): line
        for line in SPEC_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith("|") and line.count("|") >= 5
    }

    assert "未解决" in rows["FORMAT-001"]
    assert "官方重跑待完成" in rows["CLIENT-001"]
    assert "能力结论未完成" in rows["BASELINE-001"]
    assert "未解决" in rows["RESOURCE-001"]
    assert "条件性缺口" in rows["FINAL-001"]
    assert "已失败关闭" in rows["COMP-001"]


def test_normative_entrypoints_reference_engineering_specification() -> None:
    for relative in (
        "AGENTS.md",
        ".agents/skills/math-agent-maintainer/SKILL.md",
        "CONTRIBUTING.md",
        "README.md",
        "ARCHITECTURE.md",
        "SUBMISSION_INFO.md",
        "docs/COMPETITION_COMPLIANCE.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "ENGINEERING_SPECIFICATION.md" in text, relative

    assert "docs/ENGINEERING_SPECIFICATION.md" in REQUIRED_RELEASE_FILES


def test_competition_handbook_facts_are_kept_in_compliance_specification() -> None:
    text = (ROOT / "docs" / "COMPETITION_COMPLIANCE.md").read_text(encoding="utf-8")

    for fact in (
        "18 个数学领域",
        "112 题",
        "正确性 60%",
        "系统设计 10%",
        "成果展示 20%",
        "创新与扩展性 10%",
        "结构化 JSON",
        "不超过 10 分钟视频",
        "9 月 5 日",
        "changshuai@pjlab.org.cn",
        "院校-申报人-作品名称-电话",
    ):
        assert fact in text
