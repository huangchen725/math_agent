import builtins

import pytest

import demo


def test_demo_helpers_import_without_optional_gradio_dependency() -> None:
    assert demo._classify_step("policy_plain_0") == "② 候选生成（纯推理）"
    assert callable(demo.create_demo)


def test_create_demo_reports_missing_optional_dependency(monkeypatch) -> None:
    original_import = builtins.__import__

    def import_without_gradio(name, *args, **kwargs):
        if name == "gradio":
            raise ModuleNotFoundError("test: gradio unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_gradio)

    with pytest.raises(RuntimeError, match="requirements-demo.txt"):
        demo.create_demo()
