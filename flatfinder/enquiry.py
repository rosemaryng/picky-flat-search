"""Draft (and optionally submit) an enquiry to register interest / request a viewing.

- draft_enquiry: LLM-written message (deterministic template fallback).
- submit_enquiry: Playwright automation stub. Disabled by default — auto-submitting
  to portals can breach their ToS and annoy agents. Keep it as 'draft -> human
  approves -> send' for the demo. Flip ALLOW_AUTO_SUBMIT to enable.
"""
import os

from .config import OPENAI_API_KEY, OPENAI_MODEL, has_openai
from .models import Brief, Listing, Match

ALLOW_AUTO_SUBMIT = os.environ.get("ALLOW_AUTO_SUBMIT", "") == "1"


def draft_enquiry(listing: Listing, brief: Brief) -> str:
    if has_openai():
        out = _llm_draft(listing, brief)
        if out:
            return out
    return _template_draft(listing, brief)


def _template_draft(listing: Listing, brief: Brief) -> str:
    return (
        f"Hi,\n\nI'm very interested in the {listing.beds or ''}-bed at "
        f"{listing.address} ({listing.url}) advertised at "
        f"£{listing.price} pcm. It looks like a great fit for what I'm after. "
        f"I'm a reliable tenant, ready to move and can provide references/proof of "
        f"funds. Could I arrange a viewing this week? I'm flexible on timing.\n\n"
        f"Best regards,\n{brief.contact_name}\n{brief.contact_email} | {brief.contact_phone}"
    )


def _llm_draft(listing: Listing, brief: Brief) -> str:
    try:
        from openai import OpenAI
    except Exception:
        return ""
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "Write a short, warm, professional enquiry to a UK letting agent to register "
        "interest and request a viewing. 90 words max. Mention 1-2 specifics of the "
        "property to show genuine interest. Sign off with the tenant's contact details.\n"
        f"PROPERTY: {listing.address}, £{listing.price} pcm, {listing.beds} bed. "
        f"Summary: {listing.summary[:200]}\n"
        f"TENANT: {brief.contact_name}, {brief.contact_email}, {brief.contact_phone}. "
        f"Looking for: {brief.text[:200]}"
    )
    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=220)
        return resp.choices[0].message.content.strip()
    except Exception:
        return ""


def submit_enquiry(match: Match) -> str:
    """Returns a status string. Real submission requires Playwright + per-portal
    form selectors; gated behind ALLOW_AUTO_SUBMIT to avoid ToS issues."""
    if not ALLOW_AUTO_SUBMIT:
        return "drafted (auto-submit disabled — approve to send)"
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return "playwright not installed"
    # Intentionally not implemented end-to-end: each portal has its own form,
    # anti-bot, and CAPTCHA. Implement per-portal selectors here when ready.
    return "auto-submit not yet implemented for this portal"
