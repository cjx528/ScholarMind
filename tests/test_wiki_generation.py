from packages.ai.graph_service import (
    _fallback_topic_overview,
    _sanitize_wiki_text,
    repair_topic_wiki_payload,
)


def test_sanitize_rejects_pseudo_wiki_overview() -> None:
    bad = (
        "[wiki_overview] provider=zhipu; model=glm-5.1; "
        "summary=你是世界顶级学术综述作者。请为「continual learning」主题撰写概述。"
    )

    assert _sanitize_wiki_text(bad, keyword="continual learning", min_chars=10) == ""


def test_fallback_topic_overview_uses_local_context() -> None:
    overview = _fallback_topic_overview(
        keyword="continual learning",
        paper_contexts=[
            {
                "title": "Gradient Episodic Memory for Continual Learning",
                "year": 2017,
                "abstract": "Continual learning benchmark paper.",
            }
        ],
        sections=[{"title": "主要方法谱系"}],
        survey_data={
            "summary": {
                "overview": "持续学习关注模型在连续任务中吸收新知识，同时尽量保留旧知识。"
            }
        },
        timeline={},
    )

    assert "provider=" not in overview
    assert "model=" not in overview
    assert "Gradient Episodic Memory" in overview
    assert "主要方法谱系" in overview


def test_repair_topic_wiki_payload_replaces_bad_history_content() -> None:
    bad = (
        "[wiki_overview] provider=zhipu; model=glm-5.1; "
        "summary=你是世界顶级学术综述作者。请为「continual learning」主题撰写概述。"
    )
    repaired = repair_topic_wiki_payload(
        {
            "wiki_content": {
                "overview": bad,
                "sections": [{"title": "背景", "content": bad}],
            },
            "survey": {
                "summary": {
                    "overview": "持续学习旨在解决模型在非静态数据流中面临的灾难性遗忘问题。"
                }
            },
            "timeline": {
                "seminal": [
                    {
                        "title": "Overcoming catastrophic forgetting in neural networks",
                        "year": 2017,
                    }
                ]
            },
        },
        "continual learning",
    )

    content = repaired["wiki_content"]
    assert "provider=" not in content["overview"]
    assert "model=" not in content["overview"]
    assert "灾难性遗忘" in content["overview"]
    assert "provider=" not in content["sections"][0]["content"]
    assert repaired["markdown"].startswith("# continual learning")
