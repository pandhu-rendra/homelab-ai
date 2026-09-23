from __future__ import annotations


def test_github_skill_source() -> None:
    from homelab_ai.skill_manager import _github_archive

    result = _github_archive("gh:nextlevelbuilder/ui-ux-pro-max-skill")
    assert result is not None
    url, name = result
    assert url.endswith("/nextlevelbuilder/ui-ux-pro-max-skill/zip/refs/heads/main")
    assert name == "ui-ux-pro-max-skill"


def test_skill_context_only_activates_for_relevant_queries(tmp_path, monkeypatch) -> None:
    import homelab_ai.skill_manager as manager

    skill = tmp_path / "ui-ux-pro-max" / ".agents" / "skills" / "ui-ux-pro-max"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Use accessible layouts.", encoding="utf-8")
    monkeypatch.setattr(manager, "SKILL_DIR", tmp_path)

    assert manager.build_skill_context("say hello") == ""
    assert "Use accessible layouts" in manager.build_skill_context("build a dashboard")


def test_project_local_skill_uses_frontmatter_triggers(tmp_path, monkeypatch) -> None:
    import homelab_ai.skill_manager as manager

    skill = tmp_path / "python-review"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: Python Review\ndescription: Review Python code\nkeywords: python, lint, refactor\n---\n"
        "Prefer small, tested refactors.",
        encoding="utf-8",
    )
    monkeypatch.setattr(manager, "SKILL_DIR", tmp_path)
    monkeypatch.setattr(manager, "LEGACY_SKILL_DIR", tmp_path / "missing")

    context = manager.build_skill_context("refactor this Python module")

    assert "Python Review" in context
    assert "Prefer small, tested refactors" in context


def test_skill_list_marks_project_origin(tmp_path, monkeypatch) -> None:
    import homelab_ai.skill_manager as manager

    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "skill.md").write_text("Demo instructions", encoding="utf-8")
    monkeypatch.setattr(manager, "SKILL_DIR", tmp_path)
    monkeypatch.setattr(manager, "LEGACY_SKILL_DIR", tmp_path / "missing")

    listed = manager.list_skills()

    assert listed[0]["origin"] == "project"
    assert listed[0]["has_instructions"] is True