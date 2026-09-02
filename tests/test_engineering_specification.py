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
    assert "`eb5d8d4`" in rows["CLIENT-001"]
    assert "未解决" in rows["CLIENT-001"]
    assert "能力结论未完成" in rows["BASELINE-001"]
    assert "未解决" in rows["RESOURCE-001"]
    assert "条件性缺口" in rows["FINAL-001"]
    assert "S1-only 已撤销" in rows["COMP-001"]
    assert "未解决" in rows["OFFICIAL-002"]
    assert "官方口径未解决" in rows["JUDGE-001"]
    assert "未解决" in rows["SUBMIT-001"]


def test_normative_client_contract_is_the_three_argument_minimum() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "chat(messages=..., temperature=..., max_tokens=...)" in text
    assert "无 `**kwargs` 的三参数 fake" in text
    assert "伪 `config`" in text
    assert "**OUT-009**" in text
    assert "不得写“8 月 29～31 日平台收紧实锤”" in text


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
    assert "docs/OFFICIAL_MATERIALS_REGISTER.md" in REQUIRED_RELEASE_FILES


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


def test_official_material_registry_preserves_sources_conflicts_and_gaps() -> None:
    text = (ROOT / "docs" / "OFFICIAL_MATERIALS_REGISTER.md").read_text(
        encoding="utf-8"
    )

    for source in tuple(f"MAT-{index:03d}" for index in range(1, 10)):
        assert source in text
    for current_rule in (
        "2026-09-02",
        "`intern-s1-pro`",
        "`atomgit`",
        "RPM 30",
        "TPM 150000",
        "双通道",
    ):
        assert current_rule in text
    for conflict in (
        "INFO-CONFLICT-001",
        "INFO-CONFLICT-002",
        "INFO-CONFLICT-003",
        "INFO-CONFLICT-004",
        "INFO-CONFLICT-005",
        "INFO-CONFLICT-006",
        "INFO-CONFLICT-007",
        "INFO-CONFLICT-008",
        "INFO-CONFLICT-009",
    ):
        assert conflict in text
    for gap in (
        "OFFICIAL-GAP-CLIENT",
        "OFFICIAL-GAP-RESPONSE",
        "OFFICIAL-GAP-ERROR",
        "OFFICIAL-GAP-BUDGET",
        "OFFICIAL-GAP-MODEL",
        "OFFICIAL-GAP-RESOURCE",
        "OFFICIAL-GAP-JUDGE",
        "OFFICIAL-GAP-RUNNER",
        "OFFICIAL-GAP-TOOLS",
        "OFFICIAL-GAP-CHANGE",
    ):
        assert gap in text


def test_normative_documents_route_official_evidence_through_the_register() -> None:
    for relative in (
        "AGENTS.md",
        ".agents/skills/math-agent-maintainer/SKILL.md",
        "CONTRIBUTING.md",
        "README.md",
        "ARCHITECTURE.md",
        "SUBMISSION_INFO.md",
        "docs/COMPETITION_COMPLIANCE.md",
        "docs/ENGINEERING_SPECIFICATION.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "OFFICIAL_MATERIALS_REGISTER.md" in text, relative

    specification = SPEC_PATH.read_text(encoding="utf-8")
    for rule in (
        "COMP-011",
        "COMP-012",
        "API-009",
        "OUT-008",
        "RUN-005",
        "RUN-006",
    ):
        assert f"**{rule}**" in specification
