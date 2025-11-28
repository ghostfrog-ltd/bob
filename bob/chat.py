from __future__ import annotations

from typing import Dict

from .config import get_openai_client, get_model_name


def bob_simple_chat(user_text: str) -> str:
    """
    Simple Q&A mode for Bob when no file is involved.
    """
    client = get_openai_client()
    if client is None:
        return (
            "You asked: {!r}. I can't call OpenAI because OPENAI_API_KEY is "
            "not configured, but normally I'd answer this directly here."
        ).format(user_text)

    base_prompt = (
        "You are Bob, a helpful AI assistant for a developer working on the "
        "GhostFrog project.\n"
        "The user is asking a general question (no specific file needed, no live tools).\n"
        "Answer directly and concisely in plain language. Do NOT talk about "
        "plans, JSON, or tools – just reply like a normal chat assistant."
    )

    try:
        resp = client.responses.create(
            model=get_model_name(),
            input=[
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or "I couldn't generate a detailed answer."
    except Exception as e:  # noqa: BLE001
        return f"I tried to answer but hit an OpenAI error: {e!r}"


def bob_answer_with_context(user_text: str, plan: Dict, snippet: str) -> str:
    """
    Bob answers about a specific file snippet (analysis mode).
    """
    client = get_openai_client()
    if client is None:
        return "I’d like to review the file, but there is no OPENAI_API_KEY configured."

    if not snippet:
        base_prompt = (
            "The user asked you about code, but Chad could not provide the file contents.\n"
            "Answer as best you can in general terms."
        )
    else:
        base_prompt = (
            "You are Bob, reviewing code that Chad read from disk.\n"
            "The user asked a question about this file.\n\n"
            "Respond with a friendly, practical review:\n"
            "- Explain what the file appears to do.\n"
            "- Suggest concrete improvements (readability, structure, errors, etc.).\n"
            "- Keep it focused and in plain language.\n"
        )

    try:
        resp = client.responses.create(
            model=get_model_name(),
            input=[
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": f"User request:\n{user_text}"},
                {"role": "user", "content": f"File contents snippet:\n\n{snippet}"},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or "I looked at the file but couldn't generate a detailed review."
    except Exception as e:  # noqa: BLE001
        return f"I tried to review the file but hit an OpenAI error: {e!r}"
