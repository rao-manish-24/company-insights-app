import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import UpstreamError
from app.models.company import CompanyAnalysis

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class EmailServiceError(UpstreamError):
    default_detail = "Failed to send email"


def _list_block_html(title: str, items: list[Any], kind: str) -> str:
    if not items:
        return ""

    rows: list[str] = []
    for item in items:
        if kind == "theme" and isinstance(item, dict):
            rows.append(
                f"<li><strong>{escape(str(item.get('theme', '')))}</strong> — "
                f"{escape(str(item.get('insight', '')))}</li>"
            )
        elif kind == "opportunity" and isinstance(item, dict):
            rows.append(
                f"<li><strong>{escape(str(item.get('title', '')))}</strong> "
                f"[{escape(str(item.get('priority', '')))}] — "
                f"{escape(str(item.get('detail', '')))}</li>"
            )
        elif kind == "risk" and isinstance(item, dict):
            rows.append(
                f"<li><strong>{escape(str(item.get('title', '')))}</strong> "
                f"[{escape(str(item.get('severity', '')))}] — "
                f"{escape(str(item.get('detail', '')))}</li>"
            )
        elif kind == "recommendation" and isinstance(item, dict):
            rows.append(
                f"<li><strong>{escape(str(item.get('action', '')))}</strong><br/>"
                f"<span style='color:#5b7186'>{escape(str(item.get('rationale', '')))}</span></li>"
            )
        elif kind == "starter":
            rows.append(f"<li>{escape(str(item))}</li>")
        elif kind == "article" and isinstance(item, dict):
            title_text = escape(str(item.get("title", "Untitled")))
            source = escape(str(item.get("source") or "Source"))
            url = item.get("url")
            if url:
                rows.append(
                    f'<li><a href="{escape(str(url))}">{title_text}</a> — {source}</li>'
                )
            else:
                rows.append(f"<li>{title_text} — {source}</li>")

    if not rows:
        return ""

    return (
        f"<h2 style='font-family:Georgia,serif;color:#0b1f33;font-weight:400'>{escape(title)}</h2>"
        f"<ul style='line-height:1.55;color:#1c3348'>{''.join(rows)}</ul>"
    )


def _profile_html(profile: dict[str, Any]) -> str:
    if not profile:
        return ""
    rows = [
        ("Founded", profile.get("founded")),
        ("Headquarters", profile.get("headquarters")),
        ("Employees", profile.get("employees")),
        ("Parent company", profile.get("parent_company")),
        ("Revenue", profile.get("revenue")),
        ("Operating income", profile.get("operating_income")),
        ("Total assets", profile.get("total_assets")),
    ]
    facts = "".join(
        f"<li><strong>{escape(label)}</strong> — {escape(str(value))}</li>"
        for label, value in rows
        if value
    )
    market = profile.get("market") if isinstance(profile.get("market"), dict) else {}
    market_rows = [
        ("Ticker", market.get("ticker")),
        ("Price", market.get("price")),
        ("Change", market.get("change_percent")),
        ("Market cap", market.get("market_cap")),
        ("P/E", market.get("pe_ratio")),
        ("Sector", market.get("sector")),
        ("Industry", market.get("industry")),
    ]
    market_facts = "".join(
        f"<li><strong>{escape(label)}</strong> — {escape(str(value))}</li>"
        for label, value in market_rows
        if value
    )
    people_bits = []
    for person in profile.get("key_people") or []:
        if isinstance(person, dict) and person.get("name"):
            people_bits.append(
                f"<li><strong>{escape(str(person.get('role')))}</strong> — "
                f"{escape(str(person.get('name')))}</li>"
            )
    if not facts and not people_bits and not market_facts:
        return ""
    people_block = (
        f"<h3 style='font-family:Georgia,serif;color:#0b1f33;font-weight:400'>Key people</h3>"
        f"<ul style='line-height:1.55;color:#1c3348'>{''.join(people_bits)}</ul>"
        if people_bits
        else ""
    )
    market_block = (
        f"<h3 style='font-family:Georgia,serif;color:#0b1f33;font-weight:400'>Market snapshot</h3>"
        f"<ul style='line-height:1.55;color:#1c3348'>{market_facts}</ul>"
        if market_facts
        else ""
    )
    sources = []
    if profile.get("source_url") or profile.get("source"):
        sources.append(str(profile.get("source_url") or profile.get("source")))
    if market.get("source_url") or market.get("source"):
        sources.append(str(market.get("source_url") or market.get("source")))
    source_line = (
        f"<p style='color:#5b7186;font-size:12px'>Sources: {escape(' · '.join(sources))}</p>"
        if sources
        else ""
    )
    return (
        "<h2 style='font-family:Georgia,serif;color:#0b1f33;font-weight:400'>Company snapshot</h2>"
        f"<ul style='line-height:1.55;color:#1c3348'>{facts}</ul>"
        f"{market_block}{people_block}{source_line}"
    )


def build_brief_html(analysis: CompanyAnalysis) -> str:
    company = escape(analysis.company_name)
    summary = escape(analysis.executive_summary)
    created = analysis.created_at.isoformat() if analysis.created_at else ""
    model = escape(analysis.llm_model)

    body = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f3f7fb;font-family:Segoe UI,Arial,sans-serif;">
  <div style="max-width:680px;margin:24px auto;background:#ffffff;border:1px solid #d7e2ec;border-radius:12px;padding:28px;">
    <div style="color:#e11d48;font-size:13px;letter-spacing:0.04em;text-transform:uppercase;margin-bottom:8px;">Company Insights</div>
    <h1 style="margin:0 0 8px;font-family:Georgia,serif;font-weight:400;color:#0b1f33;">{company} — partner brief</h1>
    <p style="margin:0 0 20px;color:#5b7186;font-size:13px;">{escape(created)} · model {model}</p>
    <p style="color:#1c3348;line-height:1.65;font-size:15px;">{summary}</p>
    {_profile_html(getattr(analysis, "company_profile", None) or {})}
    {_list_block_html("Key themes", analysis.key_themes or [], "theme")}
    {_list_block_html("Opportunities", analysis.opportunities or [], "opportunity")}
    {_list_block_html("Risks", analysis.risks or [], "risk")}
    {_list_block_html("Recommendations", analysis.recommendations or [], "recommendation")}
    {_list_block_html("Conversation starters", analysis.conversation_starters or [], "starter")}
    {_list_block_html("Source news", (analysis.articles or [])[:8], "article")}
    <p style="margin-top:28px;color:#5b7186;font-size:12px;">
      Generated by Company Insights for partner client preparation.
    </p>
  </div>
</body>
</html>
"""
    return body


def build_brief_text(analysis: CompanyAnalysis) -> str:
    lines = [
        f"Company Insights — {analysis.company_name}",
        "",
        analysis.executive_summary,
        "",
        "Company snapshot:",
    ]
    profile = getattr(analysis, "company_profile", None) or {}
    for label, key in [
        ("Founded", "founded"),
        ("Headquarters", "headquarters"),
        ("Employees", "employees"),
        ("Parent company", "parent_company"),
        ("Revenue", "revenue"),
        ("Operating income", "operating_income"),
        ("Total assets", "total_assets"),
    ]:
        value = profile.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    market = profile.get("market") if isinstance(profile.get("market"), dict) else {}
    if market.get("ticker"):
        lines.append("")
        lines.append("Market snapshot:")
        for label, key in [
            ("Ticker", "ticker"),
            ("Price", "price"),
            ("Change", "change_percent"),
            ("Market cap", "market_cap"),
            ("P/E", "pe_ratio"),
            ("Sector", "sector"),
            ("Industry", "industry"),
        ]:
            value = market.get(key)
            if value:
                lines.append(f"- {label}: {value}")
    for person in profile.get("key_people") or []:
        if isinstance(person, dict) and person.get("name"):
            lines.append(f"- {person.get('role')}: {person.get('name')}")
    lines.extend(["", "Key themes:"])
    for item in analysis.key_themes or []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('theme')}: {item.get('insight')}")

    lines.append("")
    lines.append("Recommendations:")
    for item in analysis.recommendations or []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('action')}: {item.get('rationale')}")

    lines.append("")
    lines.append("Conversation starters:")
    for starter in analysis.conversation_starters or []:
        lines.append(f"- {starter}")

    return "\n".join(lines)


class EmailService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def resend_configured(self) -> bool:
        return bool(self.settings.resend_api_key.strip())

    @property
    def smtp_configured(self) -> bool:
        return bool(
            self.settings.smtp_host
            and self.settings.smtp_user
            and self.settings.smtp_password
            and (self.settings.smtp_from or self.settings.smtp_user)
        )

    @property
    def is_configured(self) -> bool:
        # Prefer Resend on cloud (HTTPS). SMTP still works locally.
        return self.resend_configured or self.smtp_configured

    async def send_analysis_async(self, analysis: CompanyAnalysis, to_email: str | None = None) -> str:
        import asyncio

        return await asyncio.to_thread(self.send_analysis, analysis, to_email)

    def send_analysis(self, analysis: CompanyAnalysis, to_email: str | None = None) -> str:
        recipient = (to_email or self.settings.email_to or "").strip()
        if not recipient:
            raise EmailServiceError(
                "No recipient email. Set EMAIL_TO in .env or pass 'to' in the request."
            )
        if not self.is_configured:
            raise EmailServiceError(
                "Email is not configured. Set RESEND_API_KEY (recommended for Render) "
                "or SMTP_HOST/SMTP_USER/SMTP_PASSWORD for local Gmail SMTP."
            )

        subject = f"Company Insights: {analysis.company_name} partner brief"
        html = build_brief_html(analysis)
        text = build_brief_text(analysis)

        if self.resend_configured:
            return self._send_via_resend(analysis, recipient, subject, html, text)
        return self._send_via_smtp(analysis, recipient, subject, html, text)

    def _send_via_resend(
        self,
        analysis: CompanyAnalysis,
        recipient: str,
        subject: str,
        html: str,
        text: str,
    ) -> str:
        sender = (
            self.settings.resend_from.strip()
            or self.settings.smtp_from.strip()
            or "Company Insights <onboarding@resend.dev>"
        )
        logger.info(
            "Sending brief email via Resend company=%r analysis_id=%s to=%s from=%s",
            analysis.company_name,
            analysis.id,
            recipient,
            sender,
        )
        try:
            response = httpx.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.resend_api_key.strip()}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": sender,
                    "to": [recipient],
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
                timeout=30.0,
            )
            if response.status_code >= 400:
                detail = response.text
                try:
                    detail = response.json().get("message") or detail
                except Exception:
                    pass
                raise EmailServiceError(f"Resend API error ({response.status_code}): {detail}")
        except EmailServiceError:
            raise
        except Exception as exc:
            logger.exception("Failed to send email via Resend to=%s", recipient)
            raise EmailServiceError(f"Failed to send email via Resend: {exc}") from exc

        logger.info("Email sent via Resend to=%s company=%r", recipient, analysis.company_name)
        return recipient

    def _send_via_smtp(
        self,
        analysis: CompanyAnalysis,
        recipient: str,
        subject: str,
        html: str,
        text: str,
    ) -> str:
        sender = self.settings.smtp_from or self.settings.smtp_user
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = recipient
        message.attach(MIMEText(text, "plain", "utf-8"))
        message.attach(MIMEText(html, "html", "utf-8"))

        logger.info(
            "Sending brief email via SMTP company=%r analysis_id=%s to=%s via=%s:%s",
            analysis.company_name,
            analysis.id,
            recipient,
            self.settings.smtp_host,
            self.settings.smtp_port,
        )

        try:
            if self.settings.smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    context=context,
                    timeout=30,
                ) as server:
                    server.login(self.settings.smtp_user, self.settings.smtp_password)
                    server.sendmail(sender, [recipient], message.as_string())
            else:
                with smtplib.SMTP(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=30,
                ) as server:
                    server.ehlo()
                    if self.settings.smtp_use_tls:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                        server.ehlo()
                    server.login(self.settings.smtp_user, self.settings.smtp_password)
                    server.sendmail(sender, [recipient], message.as_string())
        except Exception as exc:
            logger.exception("Failed to send email via SMTP to=%s", recipient)
            raise EmailServiceError(f"Failed to send email: {exc}") from exc

        logger.info("Email sent via SMTP to=%s company=%r", recipient, analysis.company_name)
        return recipient
