from __future__ import annotations


def test_github_skill_source() -> None:
    from homelab_ai.skill_manager import _github_archive

    result = _github_archive("gh:nextlevelbuilder/ui-ux-pro-max-skill")
    assert result is not None
    url, name = result
    assert url.endswith("/nextlevelbuilder/ui-ux-pro-max-skill/zip/refs/heads/main")
    assert name == "ui-ux-pro-max-skill"


def test_skill_context_only_activates_for_ui_queries(tmp_path, monkeypatch) -> None:
    import homelab_ai.skill_manager as manager

    skill = tmp_path / "ui-ux-pro-max" / ".agents" / "skills" / "ui-ux-pro-max"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Use accessible layouts.", encoding="utf-8")
    monkeypatch.setattr(manager, "SKILL_DIR", tmp_path)

    assert manager.build_skill_context("say hello") == ""
    assert "Use accessible layouts" in manager.build_skill_context("build a dashboard")