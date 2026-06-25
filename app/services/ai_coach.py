"""AI coach service.

Provider-abstracted text generation for the FitFutures accountability coach.
OpenAI is the live provider for MVP; Anthropic + Gemini are scaffolded in the
fallback chain (OpenAI → Anthropic → Gemini) but raise until wired, matching
the Business Hero multi-provider direction.

Phase 4 uses the auto-message mode only: on every weekly KPI submission we
analyse actuals vs that week's fixed targets plus cumulative pace and return a
≤4-sentence message. Chat mode lands in Phase 7.
"""
from typing import Optional

from app.core.config import settings

# Auto-message system prompt (brief §6). `{route}/{week_number}/{planned_weeks}`
# are filled per submission.
AUTO_MESSAGE_SYSTEM_PROMPT = """You are the FitFutures accountability coach, powered by UKFI. Read the learner's
weekly KPI data and give a direct, honest, practical response.

Rules:
- Never sycophantic. Do not congratulate low effort.
- If numbers are behind, say so directly and suggest ONE specific action.
- If on track, acknowledge briefly and push for the next step.
- Reference the actual numbers.
- Max 4 sentences. Plain English. No bullet points.
- No medical, legal, or financial advice.
- Where the learner is near qualifying, prompt them on a business start-up step.
- Tone: direct mentor, not cheerleader.

Route: {route} | Week {week_number} of {planned_weeks}"""

_ROUTE_LABELS = {"route_a": "Route A", "route_b": "Route B"}


class CoachUnavailableError(RuntimeError):
    """Raised when no provider could produce a response."""


def build_auto_message_messages(context: dict) -> list[dict]:
    """Build the OpenAI-style messages for a weekly auto-message.

    `context` carries: route, week_number, planned_weeks, week_lines
    (per-metric this-week actual/target), total_lines (cumulative actual/target),
    hours_remaining, reflection, key_issue.
    """
    system = AUTO_MESSAGE_SYSTEM_PROMPT.format(
        route=_ROUTE_LABELS.get(context.get("route"), context.get("route")),
        week_number=context.get("week_number"),
        planned_weeks=context.get("planned_weeks"),
    )

    week_block = "\n".join(
        f"- {line['label']}: {line['actual']} / {line['target']} (this week)"
        for line in context.get("week_lines", [])
    )
    total_block = "\n".join(
        f"- {line['label']}: {line['actual']} / {line['target']} (cumulative)"
        for line in context.get("total_lines", [])
    )

    parts = [
        f"Week {context.get('week_number')} of {context.get('planned_weeks')}.",
        "",
        "This week's actuals vs fixed weekly targets:",
        week_block or "- (no data)",
        "",
        "Cumulative actuals vs placement targets:",
        total_block or "- (no data)",
        "",
        f"Placement hours remaining to target: {context.get('hours_remaining')}.",
    ]
    if context.get("reflection"):
        parts += ["", f"Learner reflection: {context['reflection']}"]
    if context.get("key_issue"):
        parts += [f"Key issue raised: {context['key_issue']}"]

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(parts)},
    ]


def generate_coach_response(messages: list[dict], context: Optional[dict] = None) -> str:
    """Generate a coach reply, trying providers in order until one succeeds.

    OpenAI is live; Anthropic and Gemini are scaffolded and skipped (they raise
    NotImplementedError) until wired in a later iteration.
    """
    providers = (_call_openai, _call_anthropic, _call_gemini)
    last_error: Optional[Exception] = None
    for provider in providers:
        try:
            return provider(messages)
        except NotImplementedError:
            continue  # scaffold-only provider
        except Exception as exc:  # noqa: BLE001 — fall through to next provider
            last_error = exc
            continue
    raise CoachUnavailableError(
        f"No AI provider could generate a response: {last_error}"
    )


def _call_openai(messages: list[dict]) -> str:
    """Primary provider. Pinned model from env; timeout=30, max_retries=1."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=30, max_retries=1)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=0.5,
        # GPT-5.x rejects `max_tokens`; use `max_completion_tokens`.
        max_completion_tokens=220,
    )
    content = resp.choices[0].message.content or ""
    return content.strip()


def _call_anthropic(messages: list[dict]) -> str:
    """Fallback provider — scaffolded only (not wired for MVP)."""
    raise NotImplementedError("Anthropic fallback is scaffolded but not wired.")


def _call_gemini(messages: list[dict]) -> str:
    """Fallback provider — scaffolded only (not wired for MVP)."""
    raise NotImplementedError("Gemini fallback is scaffolded but not wired.")
