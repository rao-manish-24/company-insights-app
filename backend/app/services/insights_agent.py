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


def _extract_usage(usage: Any) -> dict[str, int]:
    """Normalize OpenAI / xAI / gateway usage payloads into token counts."""
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if isinstance(usage, dict):
        raw = usage
    elif hasattr(usage, "model_dump"):
        raw = usage.model_dump()
    elif hasattr(usage, "dict"):
        raw = usage.dict()
    else:
        raw = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }

    prompt_tokens = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
    completion_tokens = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
    total_tokens = int(raw.get("total_tokens") or 0)
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


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
    market = profile.get("market") if isinstance(profile.get("market"), dict) else {}
    market_lines = [
        f"Ticker: {market.get('ticker') or 'unknown'}",
        f"Price: {market.get('price') or 'unknown'} ({market.get('change_percent') or 'n/a'})",
        f"Market cap: {market.get('market_cap') or 'unknown'}",
        f"Trailing P/E: {market.get('pe_ratio') or 'unknown'}",
        f"Sector / industry: {market.get('sector') or 'unknown'} / {market.get('industry') or 'unknown'}",
        f"52-week range: {market.get('fifty_two_week_low') or '?'} – {market.get('fifty_two_week_high') or '?'}",
    ]
    return "\n".join(
        [
            f"Founded: {profile.get('founded') or 'unknown'}",
            f"Headquarters: {profile.get('headquarters') or 'unknown'}",
            f"Employees: {profile.get('employees') or 'unknown'}",
            f"Parent company: {profile.get('parent_company') or 'unknown'}",
            f"Revenue: {profile.get('revenue') or 'unknown'}",
            f"Operating income: {profile.get('operating_income') or 'unknown'}",
            f"Total assets: {profile.get('total_assets') or 'unknown'}",
            "Market snapshot (Yahoo Finance):",
            *[f"- {line}" for line in market_lines],
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

Structured company profile (Wikidata + Yahoo Finance market data; treat as factual baseline):
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
    {{"title": "opportunity label", "detail": "why it matters for a client conversation", "priority": "high|medium|low", "sources": ["[1] article title or source cue"]}}
  ],
  "risks": [
    {{"title": "risk label", "detail": "why it matters", "severity": "high|medium|low", "sources": ["[2] article title or source cue"]}}
  ],
  "recommendations": [
    {{"action": "what the partner should do/prepare", "rationale": "why this helps the conversation", "sources": ["[1] article title or source cue"]}}
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
- For every opportunity, risk, and recommendation, include 1-3 `sources` that cite the news corpus using article numbers/titles from above.
- For leadership_fill: ONLY fill names you are confident are current; otherwise use null. Do not invent.
"""

EXPAND_SYSTEM_PROMPT = """You are Company Insights Dig-Deeper Agent, a specialist subagent that \
expands one selected insight for a management consulting partner.

Rules:
- Ground every claim in the provided news corpus and the selected item. Do not invent facts.
- If evidence is thin, say so explicitly.
- Write for a busy partner who liked this item and wants more usable depth.
- Output ONLY valid JSON. No markdown fences.
"""

DEEP_EXPAND_SYSTEM_PROMPT = """You are Company Insights Deep-Dive Agent, a second-pass specialist \
subagent. Your job is to re-explain a selected insight more slowly, more verbosely, and more \
clearly for a partner who still does not fully understand the story.

Rules:
- Ground every claim in the provided news corpus and prior analysis. Do not invent facts.
- Be explicit, concrete, and educational — unpack jargon and cause/effect.
- Call out the most important facts that must not be missed.
- Output ONLY valid JSON. No markdown fences.
"""


def _articles_prompt_block(articles: list[NewsArticle]) -> str:
    blocks = []
    for idx, article in enumerate(articles, start=1):
        blocks.append(
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
    return "\n\n".join(blocks) if blocks else "No articles available."


def match_item_sources(
    item: dict[str, Any],
    articles: list[NewsArticle],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Match source cues on an insight item to articles in the brief corpus."""
    cues: list[str] = []
    for key in ("sources", "evidence"):
        raw = item.get(key) or []
        if isinstance(raw, list):
            cues.extend(str(cue) for cue in raw if cue)

    heading = str(item.get("title") or item.get("action") or "")
    detail = str(item.get("detail") or item.get("rationale") or "")
    search_blob = f"{heading} {detail}".lower()

    scored: list[tuple[int, dict[str, Any]]] = []
    for idx, article in enumerate(articles, start=1):
        title = article.title or ""
        title_l = title.lower()
        source_l = (article.source or "").lower()
        score = 0

        for cue in cues:
            cue_l = cue.lower()
            # Accept "[1] Title..." style citations
            if f"[{idx}]" in cue_l or cue_l.strip() == str(idx):
                score += 8
            if title_l and (title_l in cue_l or cue_l in title_l):
                score += 6
            if source_l and source_l in cue_l:
                score += 2

        # Soft keyword overlap for older briefs without sources[]
        title_tokens = [tok for tok in re.findall(r"[a-z0-9]{4,}", title_l) if tok not in {"with", "from", "that", "this"}]
        overlap = sum(1 for tok in title_tokens if tok in search_blob)
        if overlap >= 2:
            score += overlap

        if score > 0:
            scored.append(
                (
                    score,
                    {
                        "title": article.title,
                        "source": article.source,
                        "url": article.url,
                        "published_at": article.published_at,
                        "description": article.description,
                    },
                )
            )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    matched = [payload for _, payload in scored[:limit]]
    if matched:
        return matched

    # Last resort: top articles from the brief so the UI still has somewhere to look
    return [
        {
            "title": article.title,
            "source": article.source,
            "url": article.url,
            "published_at": article.published_at,
            "description": article.description,
        }
        for article in articles[: min(2, len(articles))]
    ]



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

    def expand_item(
        self,
        *,
        company_name: str,
        kind: str,
        item: dict[str, Any],
        articles: list[NewsArticle],
        depth: str = "standard",
        prior_analysis: str | None = None,
    ) -> dict[str, Any]:
        sources = match_item_sources(item, articles)
        heading = str(item.get("title") or item.get("action") or "Selected insight")
        detail = str(item.get("detail") or item.get("rationale") or "")
        is_deep = depth == "deep"

        if not self._client:
            return self._fallback_expand(
                company_name=company_name,
                kind=kind,
                heading=heading,
                detail=detail,
                sources=sources,
                depth=depth,
                prior_analysis=prior_analysis,
            )

        if is_deep:
            prior_block = prior_analysis.strip() if prior_analysis else "No prior dig-deeper analysis provided."
            user_prompt = f"""Company: {company_name}
Selected item type: {kind}
Selected heading: {heading}
Selected detail: {detail}
Priority/severity: {item.get("priority") or item.get("severity") or "n/a"}
Cited source cues: {item.get("sources") or item.get("evidence") or []}

Prior dig-deeper analysis (the partner still does not fully understand — go deeper):
{prior_block}

News corpus:
{_articles_prompt_block(articles)}

Return JSON with this exact shape:
{{
  "detailed_narrative": "8-14 sentences. Slow, verbose, plain-English explanation of the story: what happened, why it matters, how the pieces connect, and what a partner should take away.",
  "spotlight_points": [
    {{
      "point": "short high-signal fact or phrase that must stand out",
      "explanation": "1-2 sentences explaining why this point matters"
    }}
  ],
  "source_cues": ["article titles or [n] refs from the corpus that support this deep dive"]
}}

Constraints:
- Be more detailed and more verbose than a normal brief.
- Assume the reader is smart but missing context; unpack the story step by step.
- Include 4-7 spotlight_points that capture the most important facts/claims.
- Prefer evidence from the corpus over general knowledge.
- If the corpus is thin, say so and keep claims conservative.
"""
            system_prompt = DEEP_EXPAND_SYSTEM_PROMPT
            temperature = 0.3
        else:
            user_prompt = f"""Company: {company_name}
Selected item type: {kind}
Selected heading: {heading}
Selected detail: {detail}
Priority/severity: {item.get("priority") or item.get("severity") or "n/a"}
Cited source cues: {item.get("sources") or item.get("evidence") or []}

News corpus:
{_articles_prompt_block(articles)}

Return JSON with this exact shape:
{{
  "deeper_analysis": "4-7 sentences expanding the selected item with more nuance, evidence, and commercial implication",
  "why_it_matters": "2-3 sentences on why a partner should care in the client conversation",
  "questions_to_ask": ["2-4 sharp questions to ask the client about this item"],
  "suggested_moves": ["2-4 concrete next moves or prep actions tied to this item"],
  "source_cues": ["article titles or [n] refs from the corpus that support this expansion"]
}}

Constraints:
- Stay tightly focused on the selected item.
- Prefer evidence from the corpus over general knowledge.
- If the corpus is thin for this item, say so and keep claims conservative.
"""
            system_prompt = EXPAND_SYSTEM_PROMPT
            temperature = 0.25

        try:
            response = self._client.chat.completions.create(
                model=self.settings.llm_model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
            if not content:
                raise InsightsAgentError("Empty expand LLM response")
            data = self._parse_expand_json(content)
            expanded_sources = match_item_sources(
                {"sources": data.get("source_cues") or [], "title": heading, "detail": detail},
                articles,
            )
            if is_deep:
                spotlight_raw = data.get("spotlight_points") or []
                spotlight_points = []
                for point in spotlight_raw:
                    if not isinstance(point, dict):
                        continue
                    label = str(point.get("point") or "").strip()
                    explanation = str(point.get("explanation") or "").strip()
                    if label and explanation:
                        spotlight_points.append({"point": label, "explanation": explanation})
                narrative = str(data.get("detailed_narrative") or "").strip()
                return {
                    "heading": heading,
                    "deeper_analysis": narrative,
                    "why_it_matters": "",
                    "questions_to_ask": [],
                    "suggested_moves": [],
                    "detailed_narrative": narrative,
                    "spotlight_points": spotlight_points,
                    "sources": expanded_sources or sources,
                    "fallback": False,
                }

            return {
                "heading": heading,
                "deeper_analysis": data.get("deeper_analysis") or "",
                "why_it_matters": data.get("why_it_matters") or "",
                "questions_to_ask": data.get("questions_to_ask") or [],
                "suggested_moves": data.get("suggested_moves") or [],
                "detailed_narrative": None,
                "spotlight_points": [],
                "sources": expanded_sources or sources,
                "fallback": False,
            }
        except Exception:
            logger.exception(
                "Expand subagent failed company=%r kind=%s depth=%s",
                company_name,
                kind,
                depth,
            )
            result = self._fallback_expand(
                company_name=company_name,
                kind=kind,
                heading=heading,
                detail=detail,
                sources=sources,
                depth=depth,
                prior_analysis=prior_analysis,
            )
            result["fallback"] = True
            return result

    def _fallback_expand(
        self,
        *,
        company_name: str,
        kind: str,
        heading: str,
        detail: str,
        sources: list[dict[str, Any]],
        depth: str = "standard",
        prior_analysis: str | None = None,
    ) -> dict[str, Any]:
        source_titles = [str(item.get("title")) for item in sources if item.get("title")]
        evidence_line = (
            f"Supporting coverage includes: {'; '.join(source_titles[:3])}."
            if source_titles
            else f"Recent public coverage for {company_name} is limited for this item."
        )
        if depth == "deep":
            prior = (prior_analysis or "").strip()
            narrative = (
                f"Here is a slower read of '{heading}' for {company_name}. "
                f"In plain terms: {detail} {evidence_line} "
                "Think of this as a chain: public signal → commercial implication → client question. "
                "If the first dig-deeper pass felt dense, focus first on what changed, then who is affected, "
                "then what a partner should ask next. "
                + (f"Building from the earlier brief: {prior[:500]}" if prior else "")
            )
            return {
                "heading": heading,
                "deeper_analysis": narrative,
                "why_it_matters": "",
                "questions_to_ask": [],
                "suggested_moves": [],
                "detailed_narrative": narrative,
                "spotlight_points": [
                    {
                        "point": heading,
                        "explanation": "This is the core storyline the partner selected; keep it as the anchor.",
                    },
                    {
                        "point": "Confirm materiality with the client",
                        "explanation": (
                            "Public news can lag internal decisions, so verify whether this issue is live "
                            f"on the {company_name} agenda before over-investing."
                        ),
                    },
                    {
                        "point": "Use one source as proof",
                        "explanation": evidence_line,
                    },
                ],
                "sources": sources,
                "fallback": True,
            }

        return {
            "heading": heading,
            "deeper_analysis": (
                f"{heading} — {detail} {evidence_line} "
                "Treat this as a working hypothesis: confirm with the client what is current internally "
                "and which commercial implication matters most for the next 90 days."
            ),
            "why_it_matters": (
                f"This {kind} is useful because it gives the partner a concrete storyline to pressure-test "
                f"in the {company_name} conversation instead of staying at headline level."
            ),
            "questions_to_ask": [
                f"How material is '{heading}' to the current {company_name} agenda?",
                "What would change your view if this signal turned out to be overstated?",
                "Where should we prioritize follow-up evidence before the next discussion?",
            ],
            "suggested_moves": [
                "Open with a 30-second restatement of the item and ask the client to correct it.",
                "Bring one source article and one commercial implication into the room.",
                "Propose a short follow-up workstream only if the client confirms the issue is live.",
            ],
            "detailed_narrative": None,
            "spotlight_points": [],
            "sources": sources,
            "fallback": True,
        }

    @staticmethod
    def _parse_expand_json(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise InsightsAgentError("Expand LLM returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise InsightsAgentError("Expand LLM returned non-object JSON")
        return data

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
            usage_counts = _extract_usage(getattr(response, "usage", None))
            prompt_tokens = usage_counts["prompt_tokens"]
            completion_tokens = usage_counts["completion_tokens"]
            total_tokens = usage_counts["total_tokens"]

            # Some gateways omit usage; estimate so the UI still has a useful signal.
            if total_tokens <= 0:
                system_chars = len(SYSTEM_PROMPT)
                user_chars = len(_build_user_prompt(company_name, articles, profile=profile))
                prompt_tokens = max(1, (system_chars + user_chars) // 4)
                completion_tokens = max(1, len(content) // 4)
                total_tokens = prompt_tokens + completion_tokens
                logger.info(
                    "LLM call complete company=%r elapsed_ms=%.1f tokens_estimated=%s "
                    "(prompt≈%s completion≈%s)",
                    company_name,
                    elapsed_ms,
                    total_tokens,
                    prompt_tokens,
                    completion_tokens,
                )
            else:
                logger.info(
                    "LLM call complete company=%r elapsed_ms=%.1f prompt_tokens=%s completion_tokens=%s",
                    company_name,
                    elapsed_ms,
                    prompt_tokens,
                    completion_tokens,
                )

            data = self._parse_json(content)
            data["_usage"] = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "llm_elapsed_ms": round(elapsed_ms, 1),
            }
            return data

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
                    "sources": titles[:2],
                },
                {
                    "title": "Proof points",
                    "detail": "Bring one external benchmark or peer case for each major theme.",
                    "priority": "medium",
                    "sources": titles[:1],
                },
            ],
            "risks": [
                {
                    "title": "Stale narrative",
                    "detail": "News can lag internal decisions; confirm with the client what is current.",
                    "severity": "medium",
                    "sources": titles[:1],
                },
                {
                    "title": "Over-generalization",
                    "detail": "Avoid treating headlines as strategy; ask for confirmation of priorities.",
                    "severity": "high",
                    "sources": titles[:2],
                },
            ],
            "recommendations": [
                {
                    "action": f"Open with a 60-second {company_name} insights brief",
                    "rationale": "Signals preparation and invites the client to correct or deepen the narrative.",
                    "sources": titles[:2],
                },
                {
                    "action": "Pick two themes and attach a commercial implication to each",
                    "rationale": "Keeps the meeting outcome-oriented rather than news-recap oriented.",
                    "sources": titles[:1],
                },
                {
                    "action": "Close with one prioritized next-step hypothesis",
                    "rationale": "Creates a natural path to follow-on work.",
                    "sources": titles[:1],
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
