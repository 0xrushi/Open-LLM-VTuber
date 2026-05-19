from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel


class PipelineState(str, Enum):
    queued = "queued"
    running = "running"
    retrieved = "retrieved"
    synthesized = "synthesized"
    done = "done"
    error = "error"


class RetrievedEntry(BaseModel):
    header: str
    message: str


class BackgroundSearchResult(BaseModel):
    answer: str
    confidence: float
    evidence: List[str]
    no_answer_reason: str | None = None


class BackgroundSearchPipeline:
    """Typed post-processing pipeline for queued social search completions."""

    study_keywords = ("study", "studying", "class", "course", "homework", "exam", "learning")

    def __init__(self, tool_name: str, raw_text: str):
        self.tool_name = tool_name
        self.raw_text = (raw_text or "").strip()
        self.state = PipelineState.queued
        self.entries: List[RetrievedEntry] = []

    def run(self) -> BackgroundSearchResult:
        self.state = PipelineState.running
        self._retrieve_entries()
        self.state = PipelineState.retrieved
        result = self._synthesize()
        self.state = PipelineState.synthesized
        self.state = PipelineState.done
        return result

    def _retrieve_entries(self) -> None:
        # Strip internal scaffolding appended by tool templates.
        text = self.raw_text
        marker = "\n---\nINSTRUCTION:"
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx].rstrip()

        blocks = [b.strip() for b in text.split("\n\n---\n\n") if b.strip()]
        entries: List[RetrievedEntry] = []
        for block in blocks:
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            header = lines[0]
            message = ""
            for ln in lines[1:]:
                if ln.startswith(("Person:", "Server:", "Channel:", "URL:", "Links:")):
                    continue
                message = ln
                break
            if message:
                entries.append(RetrievedEntry(header=header, message=message))
        self.entries = entries

    def _synthesize(self) -> BackgroundSearchResult:
        if self.tool_name not in {"discord_search", "twitter_search"}:
            return BackgroundSearchResult(
                answer=self.raw_text,
                confidence=0.7 if self.raw_text else 0.0,
                evidence=[],
            )

        evidence = [e.message for e in self.entries[:3]]
        corpus = " ".join(evidence).lower()
        found_study_signal = any(k in corpus for k in self.study_keywords)

        if found_study_signal and evidence:
            return BackgroundSearchResult(
                answer="I checked Discord and found likely study-related mentions.",
                confidence=0.75,
                evidence=evidence,
            )

        if evidence:
            return BackgroundSearchResult(
                answer="I checked Discord, but I did not find a clear message about what he is studying today.",
                confidence=0.35,
                evidence=evidence,
                no_answer_reason="No explicit study-related content in top matches.",
            )

        return BackgroundSearchResult(
            answer="I checked Discord, but I could not find a clear answer in recent messages.",
            confidence=0.2,
            evidence=[],
            no_answer_reason="No parseable results returned.",
        )
