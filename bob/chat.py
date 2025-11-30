from __future__ import annotations

from typing import Dict

from helpers.prompts import get_prompt
from .config import get_openai_client, get_model_name


def bob_simple_chat(user_text: str) -> str:
    client = get_openai_client()
    if client is None:
        return (
            f"You asked: {user_text!r}. I can't call OpenAI because "
            f"OPENAI_API_KEY is not configured."
        )

    system_prompt = get_prompt("bob_simple_chat_system")

    try:
        resp = client.responses.create(
            model=get_model_name(),
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        return (resp.output_text or "").strip() or "I couldn't generate a detailed answer."
    except Exception as e:
        return f"I tried to answer but hit an OpenAI error: {e!r}"


def bob_answer_with_context(user_text: str, plan: Dict, snippet: str) -> str:
    client = get_openai_client()
    if client is None:
        return "I’d like to review the file, but OPENAI_API_KEY is not configured."

    if not snippet:
        system_prompt = get_prompt("bob_answer_no_snippet")
    else:
        system_prompt = get_prompt("bob_answer_with_snippet")

    try:
        resp = client.responses.create(
            model=get_model_name(),
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User request:\n{user_text}"},
                {"role": "user", "content": f"File contents snippet:\n\n{snippet}"},
            ],
        )
        return (resp.output_text or "").strip() or "I couldn't generate a detailed review."
    except Exception as e:
        return f"I tried to review the file but hit an OpenAI error: {e!r}"
