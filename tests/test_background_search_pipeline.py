import unittest

from src.open_llm_vtuber.mcpp.background_search_pipeline import (
    BackgroundSearchPipeline,
    PipelineState,
)


class TestBackgroundSearchPipeline(unittest.TestCase):
    def test_no_study_signal_returns_no_clear_answer(self):
        raw = (
            "[androso @ 2026-05-17T18:00:38.912000+00:00] (score: 0.5809)\n"
            "ahh\nPerson: androso\n\n---\n\n"
            "[androso @ 2026-05-17T17:26:18.180000+00:00] (score: 0.5234)\n"
            "it is me indeed\nPerson: androso"
        )
        p = BackgroundSearchPipeline("discord_search", raw)
        result = p.run()
        self.assertEqual(p.state, PipelineState.done)
        self.assertIn("did not find a clear message", result.answer)
        self.assertGreaterEqual(len(result.evidence), 1)

    def test_study_signal_detected(self):
        raw = (
            "[androso @ 2026-05-17T18:00:38.912000+00:00] (score: 0.5809)\n"
            "I am studying linear algebra today\nPerson: androso"
        )
        p = BackgroundSearchPipeline("discord_search", raw)
        result = p.run()
        self.assertEqual(p.state, PipelineState.done)
        self.assertIn("study-related", result.answer)
        self.assertGreater(result.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
