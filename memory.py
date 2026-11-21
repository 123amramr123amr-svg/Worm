"""ذاكرة المحادثة: إرسال الرسائل الأخيرة + تلخيص القديم تلقائيًا."""
import logging

import db
from ai_client import AIClient, AIError

log = logging.getLogger(__name__)

SUMMARY_PROMPT = (
    "لخّص المحادثة التالية في نقاط موجزة بالعربية (5-8 أسطر كحد أقصى) "
    "مع الاحتفاظ بالمعلومات المهمة: الأسماء، الأرقام، القرارات، والتفضيلات."
)


async def build_messages(conversation_id: int, settings: dict) -> list:
    """يبني قائمة الرسائل المُرسلة للنموذج: تعليمات + ملخص + آخر N رسالة."""
    messages = []
    system_prompt = (settings.get("system_prompt") or "").strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    history = await db.get_messages(conversation_id)
    if not history:
        return messages

    if settings.get("memory_enabled") != "1":
        # الذاكرة معطّلة: أرسل آخر رسالة فقط
        last = history[-1]
        messages.append({"role": last["role"], "content": last["content"]})
        return messages

    try:
        size = max(2, int(settings.get("memory_size", "20")))
    except ValueError:
        size = 20

    if len(history) > size:
        overflow = history[:-size]
        recent = history[-size:]
        summary = await _maybe_summarize(conversation_id, overflow, settings)
        if summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"ملخص لما سبق في هذه المحادثة:\n{summary}",
                }
            )
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in recent
        )
    else:
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in history
        )
    return messages


async def _maybe_summarize(conversation_id: int, overflow: list, settings: dict):
    """يلخّص الرسائل القديمة التي لم تُختصر بعد، ويحفظ الملخص."""
    conversation = await db.get_conversation(conversation_id)
    if not conversation:
        return None
    up_to = conversation.get("summarized_up_to") or 0
    new_messages = [m for m in overflow if m["id"] > up_to]
    if len(new_messages) < 4:
        return conversation.get("summary") or None

    client = AIClient(settings.get("base_url", ""), settings.get("api_key", ""))
    text = "\n".join(f"{m['role']}: {m['content']}" for m in new_messages)
    try:
        summary = await client.chat(
            settings.get("chat_model", ""),
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": text[:8000]},
            ],
        )
    except AIError:
        log.warning("فشل تلخيص الذاكرة للمحادثة %s", conversation_id)
        return conversation.get("summary") or None

    await db.set_summary(conversation_id, summary, new_messages[-1]["id"])
    return summary
