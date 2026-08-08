import json
import logging
import re
import time
from typing import Any

from openai import OpenAI, RateLimitError as OpenAIRateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings, get_settings
from app.models.schemas import NewsArticle

logger = logging.getLogger(__name__)


class InsightsAgentError(Exception):
    pass


class LlmRateLimitError(InsightsAgentError):
    pass


SYSTEM_PROMPT = """You are Company Insights Agent, a senior strategy analyst supporting \
management consulting partners preparing for client conversations.

Your job: turn recent company news into sharp, actionable client-ready insights.

Rules:
- Ground every insight in the provided news. Do not invent facts, numbers, or events.
- If evidence is thin, say so explicitly and keep claims conservative.
- Write for busy partners: clear, precise, commercially relevant.
- Prefer implications and "so what" over restating headlines.
- Avoid buzzwords and generic consulting filler.
- Output ONLY valid JSON matching the schema. No markdown fences.
"""


def _profile_block(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "No structured company profile available."
    people = profile.get("key_people") or []
    people_lines = []
    for person in people:
        if isinstance(person, dict):
            people_lines.append(f"- {person.get('role')}: {person.get('name') or 'unknown'}")
    return "\n".join(
        [
            f"Founded: {profile.get('founded') or 'unknown'}",
            f"Headquarters: {profile.get('headquarters') or 'unknown'}",
            f"Employees: {profile.get('employees') or 'unknown'}",
            f"Parent company: {profile.get('parent_company') or 'unknown'}",
            f"Revenue: {profile.get('revenue') or 'unknown'}",
            f"Operating income: {profile.get('operating_income') or 'unknown'}",
            f"Total assets: {profile.get('total_assets') or 'unknown'}",
            "Key people:",
            *(people_lines or ["- none listed"]),
            f"Source: {profile.get('source') or 'n/a'} {profile.get('source_url') or ''}".strip(),
        ]
    )


def _build_user_prompt(
    company_name: str,
    articles: list[NewsArticle],
    profile: dict[str, Any] | None = None,
) -> str:
    article_blocks = []
    for idx, article in enumerate(articles, start=1):
        article_blocks.append(
            "\n".join(
                [
                    f"[{idx}] Title: {article.title}",
                    f"    Source: {article.source or 'Unknown'}",
                    f"    Published: {article.published_at or 'Unknown'}",
                    f"    Description: {article.description or 'N/A'}",
                    f"    URL: {article.url or 'N/A'}",
                ]
            )
        )

    articles_text = "\n\n".join(article_blocks) if article_blocks else "No articles available."

    return f"""Company to analyze: {company_name}

Structured company profile (from Wikidata; treat as factual baseline):
{_profile_block(profile)}

Recent news corpus:
{articles_text}

Return JSON with this exact shape:
{{
  "executive_summary": "3-5 sentence briefing on what matters now for this company",
  "key_themes": [
    {{"theme": "short label", "insight": "1-2 sentence evidence-based insight", "evidence": ["article title or source cue"]}}
  ],
  "opportunities": [
    {{"title": "opportunity label", "detail": "why it matters for a client conversation", "priority": "high|medium|low"}}
  ],
  "risks": [
    {{"title": "risk label", "detail": "why it matters", "severity": "high|medium|low"}}
  ],
  "recommendations": [
    {{"action": "what the partner should do/prepare", "rationale": "why this helps the conversation"}}
  ],
  "conversation_starters": [
    "sharp question or talking point a partner can use in the first 10 minutes"
  ],
  "leadership_fill": {{
    "CFO": "current CFO full name or null if uncertain",
    "CBO": "current chief business officer full name or null if uncertain",
    "Vice President": "a notable current VP relevant to clients, or null if uncertain"
  }}
}}

Constraints:
- Include 3-5 key_themes, 2-4 opportunities, 2-4 risks, 3-5 recommendations, 3-5 conversation_starters.
- Be specific to {company_name}.
- For leadership_fill: ONLY fill names you are confident are current; otherwise use null. Do not invent.
"""


class InsightsAgent:
    """LLM agent that synthesizes news into partner-ready company insights."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = None
        if self.settings.llm_api_key:
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
            )

    def analyze(
        self,
        company_name: str,
        articles: list[NewsArticle],
        profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._client:
            logger.warning("LLM_API_KEY missing — using deterministic heuristic insights")
            result = self._fallback_insights(company_name, articles)
            result["_fallback"] = True
            return result

        logger.info(
            "Calling LLM company=%r model=%s base_url=%s article_count=%s",
            company_name,
            self.settings.llm_model,
            self.settings.llm_base_url,
            len(articles),
        )
        try:
            result = self._call_llm(company_name, articles, profile=profile)
            result["_fallback"] = False
            logger.info("LLM response parsed successfully company=%r", company_name)
            return result
        except Exception:
            logger.exception("LLM insight generation failed company=%r; using fallback", company_name)
            # Keep partner-facing summary clean; details stay in logs
            fallback = self._fallback_insights(company_name, articles)
            fallback["executive_summary"] = (
                f"[Fallback mode — live model unavailable] {fallback['executive_summary']}"
            )
            fallback["_fallback"] = True
            return fallback

    def _call_llm(
        self,
        company_name: str,
        articles: list[NewsArticle],
        profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        @retry(
            retry=retry_if_exception_type((OpenAIRateLimitError, LlmRateLimitError)),
            wait=wait_exponential_jitter(initial=2, max=45),
            stop=stop_after_attempt(self.settings.llm_max_retries),
            reraise=True,
        )
        def _invoke() -> dict[str, Any]:
            assert self._client is not None
            started = time.perf_counter()
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.llm_model,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": _build_user_prompt(company_name, articles, profile=profile),
                        },
                    ],
                )
            except OpenAIRateLimitError:
                logger.warning("LLM rate limited company=%r — backing off and retrying", company_name)
                raise
            except Exception as exc:
                # Some gateways surface 429 as generic APIStatusError
                status = getattr(exc, "status_code", None)
                if status == 429:
                    logger.warning("LLM HTTP 429 company=%r — backing off and retrying", company_name)
                    raise LlmRateLimitError(str(exc)) from exc
                raise

            content = response.choices[0].message.content
            if not content:
                raise InsightsAgentError("Empty LLM response")

            elapsed_ms = (time.perf_counter() - started) * 1000
            usage = getattr(response, "usage", None)
            if usage:
                logger.info(
                    "LLM call complete company=%r elapsed_ms=%.1f prompt_tokens=%s completion_tokens=%s",
                    company_name,
                    elapsed_ms,
                    getattr(usage, "prompt_tokens", "?"),
                    getattr(usage, "completion_tokens", "?"),
                )
            else:
                logger.info("LLM call complete company=%r elapsed_ms=%.1f", company_name, elapsed_ms)

            return self._parse_json(content)

        return _invoke()

    def _parse_json(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise InsightsAgentError("LLM returned invalid JSON") from exc

        required = [
            "executive_summary",
            "key_themes",
            "opportunities",
            "risks",
            "recommendations",
            "conversation_starters",
        ]
        for key in required:
            if key not in data:
                raise InsightsAgentError(f"Missing required field: {key}")

        return data

    def _fallback_insights(self, company_name: str, articles: list[NewsArticle]) -> dict[str, Any]:
        titles = [a.title for a in articles[:5]]
        themes = []
        for title in titles[:3]:
            themes.append(
                {
                    "theme": self._theme_from_title(title),
                    "insight": f"Coverage highlights: {title}",
                    "evidence": [title],
                }
            )
        if not themes:
            themes = [
                {
                    "theme": "Limited coverage",
                    "insight": f"Insufficient recent public news was available for {company_name}.",
                    "evidence": [],
                }
            ]

        return {
            "executive_summary": (
                f"{company_name} is currently in the news across {len(articles)} recent articles. "
                "Key signals point to strategic movement around growth, competitive pressure, and "
                "operational priorities. Partners should validate which themes map to the client's "
                "stated agenda before the meeting and prepare one crisp implication for each."
            ),
            "key_themes": themes,
            "opportunities": [
                {
                    "title": "Agenda mapping",
                    "detail": (
                        f"Use the latest {company_name} themes to align the conversation with "
                        "initiatives leadership is already publicly signaling."
                    ),
                    "priority": "high",
                },
                {
                    "title": "Proof points",
                    "detail": "Bring one external benchmark or peer case for each major theme.",
                    "priority": "medium",
                },
            ],
            "risks": [
                {
                    "title": "Stale narrative",
                    "detail": "News can lag internal decisions; confirm with the client what is current.",
                    "severity": "medium",
                },
                {
                    "title": "Over-generalization",
                    "detail": "Avoid treating headlines as strategy; ask for confirmation of priorities.",
                    "severity": "high",
                },
            ],
            "recommendations": [
                {
                    "action": f"Open with a 60-second {company_name} insights brief",
                    "rationale": "Signals preparation and invites the client to correct or deepen the narrative.",
                },
                {
                    "action": "Pick two themes and attach a commercial implication to each",
                    "rationale": "Keeps the meeting outcome-oriented rather than news-recap oriented.",
                },
                {
                    "action": "Close with one prioritized next-step hypothesis",
                    "rationale": "Creates a natural path to follow-on work.",
                },
            ],
            "conversation_starters": [
                f"Which of the recent public themes around {company_name} feels most accurate internally?",
                "Where is competitive pressure showing up first — growth, cost, or talent?",
                "If we had 90 days, which of these risks would you want a sharper plan against?",
            ],
        }

    @staticmethod
    def _theme_from_title(title: str) -> str:
        lowered = title.lower()
        if any(word in lowered for word in ("ai", "digital", "cloud", "technology")):
            return "Digital & technology"
        if any(word in lowered for word in ("margin", "cost", "pricing", "earnings")):
            return "Financial performance"
        if any(word in lowered for word in ("leadership", "ceo", "appoint")):
            return "Leadership & organization"
        if any(word in lowered for word in ("esg", "sustainab", "climate")):
            return "Sustainability"
        if any(word in lowered for word in ("m&a", "acquisit", "merger", "deal")):
            return "M&A and portfolio"
        return "Strategic developments"
