import unittest
from types import SimpleNamespace

from src.open_llm_vtuber.service_context import ServiceContext
from src.open_llm_vtuber.agent.output_types import SentenceOutput, DisplayText, Actions


class _MockAgent:
    async def chat(self, _batch):
        yield SentenceOutput(
            display_text=DisplayText(text="Babe, I checked Discord and didn't find clear study info yet."),
            tts_text="Babe, I checked Discord and didn't find clear study info yet.",
            actions=Actions(expressions=["expression1"]),
        )


class TestBackgroundPersonaRewrite(unittest.IsolatedAsyncioTestCase):
    async def test_rewrite_background_result_uses_agent_persona_text(self):
        ctx = ServiceContext()
        ctx.agent_engine = _MockAgent()
        ctx.character_config = SimpleNamespace(character_name="Nami", human_name="User", avatar=None)

        raw = "I checked Discord, but I did not find a clear message."
        rewritten = await ctx._rewrite_background_result_in_character(raw)
        self.assertIn("Babe, I checked Discord", rewritten)
        self.assertNotEqual(rewritten, raw)


if __name__ == "__main__":
    unittest.main()
