import unittest

from packages.ai.pipelines import PaperPipelines


class SkimCleanupTest(unittest.TestCase):
    def test_skim_fallback_does_not_show_prompt_or_provider_text(self):
        pipeline = PaperPipelines.__new__(PaperPipelines)
        report = pipeline._build_skim_structured(
            abstract=(
                "We introduce ETCHR, a framework for thinking with images in multimodal "
                "reasoning. It compares prior tool-based paradigms with a more direct "
                "visual reasoning workflow and reports improvements on benchmark tasks."
            ),
            llm_text=(
                "[skim] provider=zhipu; model=glm-4.7-flash; summary=请只输出单个 JSON 对象，"
                "不要输出 markdown 代码块包裹。"
            ),
            parsed_json=None,
            title="ETCHR: Thinking with Images for Multimodal Reasoning",
        )

        combined = "\n".join([report.one_liner, *report.innovations])
        self.assertNotIn("provider=", combined)
        self.assertNotIn("请只输出", combined)
        self.assertNotIn("JSON", combined)
        self.assertIn("ETCHR", report.one_liner)
        self.assertGreaterEqual(len(report.innovations), 3)

    def test_skim_parsed_json_filters_placeholders_and_prompt_leakage(self):
        pipeline = PaperPipelines.__new__(PaperPipelines)
        report = pipeline._build_skim_structured(
            abstract="This paper proposes a retrieval augmented agent for scientific reading.",
            llm_text="",
            parsed_json={
                "one_liner": "请只输出单个 JSON 对象，不要输出 markdown 代码块包裹",
                "innovations": ["创新点1", "提出面向科研阅读的检索增强 agent 流程"],
                "keywords": ["keyword1", "retrieval", "agent"],
                "title_zh": "中文标题",
                "abstract_zh": "中文摘要",
                "relevance_score": 0.8,
            },
            title="Retrieval Augmented Agents for Scientific Reading",
        )

        self.assertNotIn("请只输出", report.one_liner)
        self.assertIn("提出面向科研阅读的检索增强 agent 流程", report.innovations)
        self.assertNotIn("创新点1", report.innovations)
        self.assertIn("retrieval", report.keywords)
        self.assertNotIn("keyword1", report.keywords)
        self.assertEqual(report.title_zh, "")
        self.assertEqual(report.abstract_zh, "")

    def test_skim_parsed_json_filters_schema_descriptions(self):
        pipeline = PaperPipelines.__new__(PaperPipelines)
        report = pipeline._build_skim_structured(
            abstract=(
                "We introduce ETCHR, a framework for thinking with images in multimodal "
                "reasoning. It compares prior tool-based paradigms with a direct visual "
                "reasoning workflow."
            ),
            llm_text="",
            parsed_json={
                "one_liner": "60-100 字中文，直接说明论文解决的问题、核心方法和最主要贡献",
                "innovations": ["3-5", "3-5 条中文要点，每条必须来自标题或摘要，不写空话"],
                "keywords": ["3-8 个英文技术关键词"],
                "title_zh": "中文标题，不能写占位符",
                "abstract_zh": "120-220 字中文摘要，不能写模板说明",
                "relevance_score": 0.5,
            },
            title="ETCHR: Thinking with Images for Multimodal Reasoning",
        )

        combined = "\n".join([report.one_liner, *report.innovations, *report.keywords])
        self.assertNotIn("60-100", combined)
        self.assertNotIn("3-5", combined)
        self.assertNotIn("3-8", combined)
        self.assertIn("ETCHR", report.one_liner)
        self.assertGreaterEqual(len(report.innovations), 3)
        self.assertEqual(report.title_zh, "")
        self.assertEqual(report.abstract_zh, "")



if __name__ == "__main__":
    unittest.main()
