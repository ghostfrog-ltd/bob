# helpers/chat_flow.py
from __future__ import annotations
from typing import List, Dict

def handle_chat(message: str, tools_enabled: bool = True) -> List[Dict[str, str]]:
    """
    Temporary stub version of the chat orchestrator.
    Keeps the web.chat blueprint functional.
    Replace with Bob→Chad→Bob logic after refactor.
    """
    prefix = "(tools OFF)" if not tools_enabled else "(tools ON)"
    return [
        {"role": "bob", "text": f"[stub] handle_chat {prefix}: {message}"}
    ]
