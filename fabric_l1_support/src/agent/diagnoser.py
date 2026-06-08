"""Claude-powered pipeline error diagnoser with RAG context."""
import json
import logging
from typing import Optional

import anthropic

from src.models.schemas import (
    DiagnosisResult,
    ErrorCategory,
    PipelineRun,
)
from src.rag.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Microsoft Fabric L1 Support Engineer.
Your job is to diagnose failed data pipeline errors and decide if they can be auto-fixed.

## Auto-Fixable Errors (set is_auto_fixable: true)
- Transient network timeouts
- HTTP 429 throttling / rate limits
- Temporary source system unavailability (retry after brief wait)
- Token expiry (AAD token refresh + rerun)
- Resource contention (capacity throttled, retry)

## NOT Auto-Fixable (set is_auto_fixable: false, alert human)
- Schema mismatch or column type errors
- Source file/table not found (FileNotFoundException, TableNotFoundException)
- Permission denied / access errors (403, Unauthorized)
- Data quality failures (null constraint, duplicate key)
- Unknown/ambiguous errors with no clear retry path

## Response Format
Always return a valid JSON object with these exact fields:
{
  "error_category": "<transient|auth|infra|schema|permission|data_quality|source_missing|unknown>",
  "is_auto_fixable": <true|false>,
  "root_cause": "<concise technical explanation>",
  "recommended_action": "<specific actionable next step>",
  "confidence_score": <0.0-1.0>,
  "summary": "<one sentence for Teams notification>"
}"""


class PipelineDiagnoser:
    """Diagnoses pipeline failures using Claude + RAG knowledge base."""

    def __init__(self, api_key: str, knowledge_base: KnowledgeBase):
        self._claude = anthropic.Anthropic(api_key=api_key)
        self._kb = knowledge_base

    async def diagnose(
        self,
        pipeline_run: PipelineRun,
        run_logs: str,
    ) -> DiagnosisResult:
        """Diagnose a pipeline failure and return structured result."""

        # Build error query for RAG
        error_query = f"{pipeline_run.error_message or ''} {pipeline_run.error_code or ''}"
        similar_docs = self._kb.search(error_query, n_results=5)

        # Build RAG context
        rag_context = self._build_rag_context(similar_docs)

        # Build diagnosis prompt
        user_message = self._build_diagnosis_prompt(pipeline_run, run_logs, rag_context)

        logger.info(f"Diagnosing pipeline {pipeline_run.pipeline_name} run {pipeline_run.run_id}")

        # Call Claude with prompt caching on system prompt
        response = self._claude.messages.create(
            model="claude-opus-4-8",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_message}],
        )

        # Parse Claude's JSON response
        raw_text = next(
            b.text for b in response.content if b.type == "text"
        )
        diagnosis_data = self._parse_response(raw_text)

        return DiagnosisResult(
            pipeline_run=pipeline_run,
            error_category=ErrorCategory(diagnosis_data.get("error_category", "unknown")),
            is_auto_fixable=diagnosis_data.get("is_auto_fixable", False),
            root_cause=diagnosis_data.get("root_cause", "Unknown"),
            recommended_action=diagnosis_data.get("recommended_action", "Investigate manually"),
            confidence_score=float(diagnosis_data.get("confidence_score", 0.0)),
            similar_past_errors=[d for d in similar_docs if d["type"] == "resolved_incident"],
            runbook_references=[d["source"] for d in similar_docs if d["type"] == "runbook"],
        )

    def _build_rag_context(self, similar_docs: list[dict]) -> str:
        if not similar_docs:
            return "No similar past errors found in knowledge base."
        lines = ["## Relevant Knowledge Base Entries\n"]
        for doc in similar_docs[:3]:
            lines.append(f"**Source**: {doc['source']} (relevance: {doc['relevance_score']})")
            lines.append(doc["content"][:500])
            lines.append("---")
        return "\n".join(lines)

    def _build_diagnosis_prompt(
        self,
        run: PipelineRun,
        logs: str,
        rag_context: str,
    ) -> str:
        return f"""## Failed Pipeline Run Details

**Pipeline**: {run.pipeline_name}
**Pipeline ID**: {run.pipeline_id}
**Run ID**: {run.run_id}
**Workspace**: {run.workspace_id}
**Failed At**: {run.end_time}

**Error Message**:
{run.error_message or 'No error message available'}

**Error Code**: {run.error_code or 'N/A'}

**Run Logs** (last 2000 chars):
{logs[-2000:] if logs else 'No logs available'}

{rag_context}

Diagnose this failure and return a JSON response as specified. Be precise and actionable."""

    def _parse_response(self, raw_text: str) -> dict:
        """Extract JSON from Claude's response, handling markdown code blocks."""
        text = raw_text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}\nRaw: {raw_text[:500]}")
            return {
                "error_category": "unknown",
                "is_auto_fixable": False,
                "root_cause": "Claude response parsing failed",
                "recommended_action": "Investigate manually",
                "confidence_score": 0.0,
            }
