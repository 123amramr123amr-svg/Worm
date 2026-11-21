"""معالجات تيليجرام: أوامر، أزرار، محادثة، أدوات، إعدادات."""
import asyncio
import base64
import logging
import re
import warnings

from telegram import Update
from telegram.constants import ChatAction
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
import db
import files as filetools
import keyboards as kb
import memory
import pdfgen
from ai_client import AIClient, AIError

log = logging.getLogger(__name__)

# PTBUserWarning المتعلق بـ per_message: تحذير معلوماتي فقط لأننا نستخدم
# MessageHandler داخل الحالات (لازم لاستقبال النصوص) مع CallbackQueryHandler
# في نفس الوقت — وهو سلوك مدعوم ويعمل بشكل صحيح. نكتم التحذير تحديدًا.
warnings.filterwarnings(
    "ignore",
    message=r".*per_message.*",
    category=PTBUserWarning,
)

# حالات محادثة الإعدادات
(
    SET_BASE_URL,
    SET_API_KEY,
    SET_MODEL,
    SET_SYSTEM_PROMPT,
    SET_MEMORY_SIZE,
    SET_WELCOME,
    SET_PROVIDER_URL,
    SET_PROVIDER_KEY,
) = range(8)

MODEL_KIND_LABELS = {
    "chat": "💬 نموذج المحادثة",
    "image": "🖼️ نموذج الصور",
    "video": "🎬 نموذج الفيديو",
}
MODEL_SETTING_KEYS = {
    "chat": "chat_model",
    "image": "image_model",
    "video": "video_model",
}
MODE_TEXT = {
    "chat": "💬 وضع المحادثة: اكتب رسالتك وسأرد عليك مع تذكّر السياق.",
    "image": "🖼️ وضع إنشاء الصور: اكتب وصف الصورة التي تريدها.",
    "video": "🎬 وضع إنشاء الفيديو: اكتب وصف الفيديو الذي تريده.",
    "pdf": "📕 وضع إنشاء PDF: أرسل النص (يدعم # للعناوين و**عريض** و- للقوائم) وسأحوّله إلى PDF.",
    "file": "📄 وضع إنشاء ملف: أرسل محتوى الملف ثم اختر نوعه.",
}
CODE_EXT = {
    "py": "py", "python": "py", "html": "html", "js": "js", "javascript": "js",
    "ts": "ts", "typescript": "ts", "css": "css", "json": "json",
    "md": "md", "markdown": "md", "sh": "sh", "bash": "sh", "sql": "sql",
    "java": "java", "c": "c", "cpp": "cpp", "go": "go", "php": "php",
    "rb": "rb", "txt": "txt", "xml": "xml", "yaml": "yaml", "yml": "yml",
}

_locks: dict = {}


def _lock(user_id: int) -> asyncio.Lock:
    lock = _locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock
    return lock


async def _settings() -> dict:
    settings = dict(config.DEFAULT_SETTINGS)
    settings.update(await db.get_all_settings())
    return settings


def _mask_key(key: str) -> str:
    if not key:
        return "غير مضاف ❌"
    if len(key) <= 8:
        return "••••"
    return key[:4] + "••••" + key[-2:]


def _split(text: str, limit: int = 3500) -> list:
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


async def _send(message, text: str, **kwargs) -> None:
    for chunk in _split(text):
        await message.reply_text(chunk, **kwargs)


async def _warn_no_key(message) -> None:
    await message.reply_text(
        "⚠️ لم يتم ضبط مفتاح API بعد.\n"
        "اذهب إلى ⚙️ الإعدادات وأضف رابط API والمفتاح، "
        "ثم اختر نموذجًا من 🤖 النماذج.",
        reply_markup=kb.settings_menu(),
    )


# ================= شاشات القوائم =================

async def _show_main(message) -> None:
    await message.reply_text(
        "🏠 القائمة الرئيسية — اختر:", reply_markup=kb.main_menu()
    )


async def _show_settings(message) -> None:
    s = await _settings()
    prompt = s["system_prompt"]
    if len(prompt) > 60:
        prompt = prompt[:60] + "..."
    active = s.get("active_profile") or "—"
    text = (
        "⚙️ الإعدادات الحالية:\n\n"
        f"🌐 المزوّد النشط: {active}\n"
        f"🔗 رابط API: {s['base_url']}\n"
        f"🔑 المفتاح: {_mask_key(s['api_key'])}\n"
        f"💬 نموذج المحادثة: {s['chat_model']}\n"
        f"🖼️ نموذج الصور: {s['image_model']}\n"
        f"🎬 نموذج الفيديو: {s['video_model']}\n"
        f"🧠 الذاكرة: {'مفعّلة ✅' if s['memory_enabled'] == '1' else 'معطّلة ❌'} "
        f"(حجم: {s['memory_size']} رسالة)\n"
        f"📝 التعليمات: {prompt}"
    )
    await message.reply_text(text, reply_markup=kb.settings_menu())


async def _show_models(message, context) -> None:
    s = await _settings()
    await message.reply_text("⏳ جارٍ جلب النماذج من الخادم...")
    client = AIClient(s["base_url"], s["api_key"])
    try:
        models = await client.list_models()
    except AIError as exc:
        await message.reply_text(
            f"❌ تعذّر جلب النماذج:\n{exc}\n\nتحقق من الرابط والمفتاح في الإعدادات.",
            reply_markup=kb.settings_menu(),
        )
        return
    if not models:
        await message.reply_text(
            "⚠️ الخادم لم يرجع أي نماذج.", reply_markup=kb.settings_menu()
        )
        return
    models = models[:40]
    context.user_data["models"] = models
    lines = "\n".join(f"• {m}" for m in models)
    await message.reply_text(
        f"🤖 النماذج المتاحة ({len(models)}):\n\n{lines}\n\n"
        "اختر نموذجًا لتعيينه (محادثة / صور / فيديو):",
        reply_markup=kb.models_keyboard(models),
    )


async def _show_memory(message) -> None:
    s = await _settings()
    state = "مفعّلة ✅" if s["memory_enabled"] == "1" else "معطّلة ❌"
    text = (
        f"🧠 إعدادات الذاكرة:\n\n"
        f"الحالة: {state}\n"
        f"حجم الذاكرة: {s['memory_size']} رسالة أخيرة\n\n"
        "عند تفعيل الذاكرة، يتذكّر البوت سياق المحادثة ويلخّص الرسائل "
        "القديمة تلقائيًا حتى لا ينسى ما قيل."
    )
    await message.reply_text(text, reply_markup=kb.memory_menu())


async def _show_tools(message) -> None:
    await message.reply_text(
        "🛠️ الأدوات — اختر الأداة ثم أرسل طلبك:\n\n"
        "💬 محادثة مع النموذج\n"
        "🖼️ إنشاء صورة من وصف\n"
        "🎬 إنشاء فيديو من وصف\n"
        "📕 تحويل نص إلى ملف PDF\n"
        "📄 إنشاء ملف برمجي/نصي من محتوى ترسله",
        reply_markup=kb.tools_menu(),
    )


async def _show_help(message) -> None:
    text = (
        "❓ المساعدة\n\n"
        "الأوامر:\n"
        "/start — بدء البوت\n"
        "/new — محادثة جديدة\n"
        "/models — عرض النماذج المتاحة\n"
        "/settings — الإعدادات\n"
        "/chat — وضع المحادثة\n"
        "/help — هذه القائمة\n\n"
        "الأزرار:\n"
        "⚙️ الإعدادات: إضافة رابط API والمفتاح واختيار النماذج\n"
        "🌐 المزوّدون: حفظ عدة مزوّدات والتنقل بينها (OpenRouter، Groq، Pollinations...)\n"
        "🤖 النماذج: جلب النماذج المرتبطة بمفتاحك واختيارها\n"
        "🧠 الذاكرة: تفعيل/تعطيل ذاكرة المحادثة وحجمها\n"
        "📁 المحادثات: إدارة محادثاتك السابقة\n"
        "🛠️ الأدوات: إنشاء صور وفيديوهات وملفات PDF وملفات برمجية\n\n"
        "يمكنك أيضًا إرسال أي ملف (PDF، صورة، Word، Excel، ملف نصي...) "
        "وسأقرأه وأجيب عن أسئلتك حوله."
    )
    await message.reply_text(text, reply_markup=kb.main_menu())


async def _show_conversations(message, context) -> None:
    user_id = message.from_user.id
    conversations = await db.list_conversations(user_id)
    current = await db.get_current_conversation_id(user_id)
    if not conversations:
        await message.reply_text(
            "📁 لا توجد محادثات بعد.", reply_markup=kb.conversations_keyboard([], None)
        )
        return
    lines = []
    for conv in conversations[:15]:
        title = conv.get("title") or "محادثة جديدة"
        lines.append(f"• {title} — {conv.get('message_count', 0)} رسالة")
    await message.reply_text(
        "📁 محادثاتك:\n\n" + "\n".join(lines),
        reply_markup=kb.conversations_keyboard(conversations[:15], current),
    )


# ================= المزوّدون =================

async def _show_providers(message) -> None:
    profiles = await db.get_profiles()
    s = await _settings()
    active = s.get("active_profile") or ""
    if not profiles:
        text = (
            "🌐 لا توجد مزوّدات محفوظة بعد.\n\n"
            "يمكنك حفظ عدة مزوّدات (OpenRouter، Groq، Pollinations...) "
            "والتنقل بينها بضغطة واحدة."
        )
    else:
        lines = []
        for profile in profiles:
            mark = "✅ " if profile.get("name") == active else "•"
            lines.append(f"{mark} {profile.get('name')} — {profile.get('base_url')}")
        text = "🌐 المزوّدات المحفوظة:\n\n" + "\n".join(lines)
    await message.reply_text(text, reply_markup=kb.profiles_keyboard(profiles, active))


async def _test_connection(message) -> None:
    s = await _settings()
    await message.reply_text("🔌 جارٍ اختبار الاتصال...")
    client = AIClient(s["base_url"], s["api_key"])
    try:
        models = await client.list_models()
    except AIError as exc:
        await message.reply_text(
            f"❌ فشل الاتصال:\n{exc}\n\nتحقق من الرابط والمفتاح في ⚙️ الإعدادات.",
            reply_markup=kb.settings_menu(),
        )
        return
    await message.reply_text(
        f"✅ الاتصال ناجح! الخادم يرجع {len(models)} نموذجًا.\n"
        f"الرابط: {s['base_url']}",
        reply_markup=kb.settings_menu(),
    )


async def _activate_profile(message, index: int) -> None:
    profiles = await db.get_profiles()
    if index < 0 or index >= len(profiles):
        return
    profile = profiles[index]
    await db.set_setting("base_url", profile.get("base_url", ""))
    await db.set_setting("api_key", profile.get("api_key", ""))
    await db.set_setting("active_profile", profile.get("name", ""))
    await message.reply_text(
        f"✅ تم تفعيل المزوّد «{profile.get('name')}».\n"
        "الآن اضغط 🤖 النماذج لجلب النماذج المتاحة.",
        reply_markup=kb.settings_menu(),
    )


async def _delete_profile(message, index: int) -> None:
    profiles = await db.get_profiles()
    if index < 0 or index >= len(profiles):
        return
    removed = profiles.pop(index)
    await db.save_profiles(profiles)
    s = await _settings()
    if s.get("active_profile") == removed.get("name"):
        await db.set_setting("active_profile", "")
    await message.reply_text(
        f"🗑️ تم حذف المزوّد «{removed.get('name')}».",
        reply_markup=kb.profiles_keyboard(profiles, s.get("active_profile") or ""),
    )


async def _save_profile(context, name: str, base_url: str, api_key: str) -> None:
    profiles = await db.get_profiles()
    existing = {p.get("name") for p in profiles}
    final_name = name
    counter = 2
    while final_name in existing:
        final_name = f"{name} {counter}"
        counter += 1
    profiles.append({"name": final_name, "base_url": base_url, "api_key": api_key})
    await db.save_profiles(profiles)
    await db.set_setting("base_url", base_url)
    await db.set_setting("api_key", api_key)
    await db.set_setting("active_profile", final_name)


# ================= الأوامر =================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await db.upsert_user(
        user.id, update.effective_chat.id, user.username, user.first_name
    )
    s = await _settings()
    await update.message.reply_text(
        s.get("welcome_text") or config.DEFAULT_SETTINGS["welcome_text"],
        reply_markup=kb.main_menu(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_help(update.message)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await db.create_conversation(user_id)
    await update.message.reply_text(
        "➕ بدأت محادثة جديدة. اكتب رسالتك!",
        reply_markup=kb.main_menu(),
    )


async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_models(update.message, context)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show_settings(update.message)


async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "chat"
    await update.message.reply_text(
        MODE_TEXT["chat"], reply_markup=kb.main_menu()
    )


# ================= أزرار عامة =================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    message = query.message

    if data == "menu:main":
        await _show_main(message)
    elif data == "menu:settings":
        await _show_settings(message)
    elif data == "menu:models":
        await _show_models(message, context)
    elif data == "menu:memory":
        await _show_memory(message)
    elif data == "menu:tools":
        await _show_tools(message)
    elif data == "menu:help":
        await _show_help(message)
    elif data == "menu:convs":
        await _show_conversations(message, context)
    elif data.startswith("mode:"):
        mode = data.split(":", 1)[1]
        context.user_data["mode"] = mode
        await message.reply_text(
            MODE_TEXT.get(mode, MODE_TEXT["chat"]),
            reply_markup=kb.cancel_keyboard(),
        )
    elif data.startswith("conv:"):
        await _conversation_action(message, context, data)
    elif data.startswith("ft:"):
        await _filetype_action(update, context, data.split(":", 1)[1])
    elif data.startswith("model:pick:"):
        await _pick_model(update, context)
    elif data.startswith("model:assign:"):
        await _assign_model(update, context)
    elif data == "set:providers":
        await _show_providers(message)
    elif data == "set:test":
        await _test_connection(message)
    elif data == "prov:add":
        await message.reply_text(
            "🌐 اختر المزوّد (أو «مخصص» لإدخال الرابط يدويًا):",
            reply_markup=kb.presets_keyboard(),
        )
    elif data.startswith("prov:use:"):
        await _activate_profile(message, int(data.split(":")[2]))
    elif data.startswith("prov:del:"):
        await _delete_profile(message, int(data.split(":")[2]))
    elif data == "set:memory_toggle":
        s = await _settings()
        new_value = "0" if s["memory_enabled"] == "1" else "1"
        await db.set_setting("memory_enabled", new_value)
        state = "مفعّلة ✅" if new_value == "1" else "معطّلة ❌"
        await message.reply_text(
            f"🧠 الذاكرة الآن: {state}", reply_markup=kb.settings_menu()
        )
    elif data == "set:clear_memory":
        user_id = message.from_user.id
        conv_id = await db.get_current_conversation_id(user_id)
        if conv_id:
            await db.clear_conversation_messages(conv_id)
        await message.reply_text(
            "🗑️ تم مسح ذاكرة المحادثة الحالية.", reply_markup=kb.settings_menu()
        )
    elif data == "cancel":
        context.user_data["mode"] = "chat"
        await message.reply_text(
            "تم الإلغاء. أنت الآن في وضع المحادثة 💬",
            reply_markup=kb.main_menu(),
        )


async def _conversation_action(message, context, data: str) -> None:
    parts = data.split(":")
    user_id = message.from_user.id
    if parts[1] == "new":
        await db.create_conversation(user_id)
        await message.reply_text(
            "➕ بدأت محادثة جديدة. ذاكرة المحادثات السابقة محفوظة "
            "ويمكنك الرجوع إليها من 📁 المحادثات."
        )
    elif parts[1] == "open":
        await db.set_current_conversation(user_id, int(parts[2]))
        await message.reply_text("✅ تم التبديل إلى المحادثة المحددة.")
    elif parts[1] == "del":
        await db.delete_conversation(int(parts[2]))
        await message.reply_text("🗑️ تم حذف المحادثة.")
    await _show_conversations(message, context)


async def _filetype_action(update: Update, context, ext: str) -> None:
    text = context.user_data.pop("pending_file_text", None)
    if not text:
        await update.callback_query.message.reply_text(
            "⚠️ لا يوجد محتوى معلّق. أرسل المحتوى أولًا في وضع إنشاء ملف."
        )
        return
    user_id = update.effective_user.id
    path = filetools.write_output(user_id, f"file.{ext}", text)
    context.user_data["mode"] = "chat"
    await update.callback_query.message.reply_document(
        document=str(path),
        filename=path.name,
        caption=f"📄 تم إنشاء الملف ({ext})",
    )


# ================= اختيار النماذج =================

async def _pick_model(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    try:
        index = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        return
    models = context.user_data.get("models", [])
    if index >= len(models):
        return
    await query.message.reply_text(
        f"اخترت: {models[index]}\nعيّنه كـ:",
        reply_markup=kb.assign_keyboard(index),
    )


async def _assign_model(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 4:
        return
    kind, index = parts[2], int(parts[3])
    models = context.user_data.get("models", [])
    if index >= len(models) or kind not in MODEL_SETTING_KEYS:
        return
    await db.set_setting(MODEL_SETTING_KEYS[kind], models[index])
    await query.message.reply_text(
        f"✅ تم تعيين «{models[index]}» كـ {MODEL_KIND_LABELS[kind]}.",
        reply_markup=kb.settings_menu(),
    )


async def _assign_model_end(update: Update, context):
    await _assign_model(update, context)
    return ConversationHandler.END


# ================= محادثة الإعدادات =================

async def entry_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    action = parts[1]
    if action == "base_url":
        await query.message.reply_text(
            "🔗 أرسل رابط API (مثال: https://api.openai.com/v1):",
            reply_markup=kb.cancel_keyboard(),
        )
        return SET_BASE_URL
    if action == "api_key":
        await query.message.reply_text(
            "🔑 أرسل مفتاح API:", reply_markup=kb.cancel_keyboard()
        )
        return SET_API_KEY
    if action == "model":
        context.user_data["model_kind"] = parts[2] if len(parts) > 2 else "chat"
        return await _start_model_pick(update, context)
    if action == "system_prompt":
        await query.message.reply_text(
            "📝 أرسل التعليمات (System Prompt) التي تريد أن يتبعها النموذج:",
            reply_markup=kb.cancel_keyboard(),
        )
        return SET_SYSTEM_PROMPT
    if action == "memory_size":
        await query.message.reply_text(
            "🧠 أرسل عدد الرسائل الأخيرة التي يتذكّرها البوت (مثال: 20):",
            reply_markup=kb.cancel_keyboard(),
        )
        return SET_MEMORY_SIZE
    if action == "welcome":
        await query.message.reply_text(
            "👋 أرسل رسالة الترحيب الجديدة:", reply_markup=kb.cancel_keyboard()
        )
        return SET_WELCOME
    return ConversationHandler.END


async def entry_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        index = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        return ConversationHandler.END
    if index < 0 or index >= len(kb.PROVIDER_PRESETS):
        return ConversationHandler.END
    name, url, needs_key = kb.PROVIDER_PRESETS[index]
    context.user_data["pending_profile"] = {"name": name, "base_url": url}
    if not url:
        await query.message.reply_text(
            "🔗 أرسل رابط API للمزوّد المخصص (مثال: https://example.com/v1):",
            reply_markup=kb.cancel_keyboard(),
        )
        return SET_PROVIDER_URL
    if not needs_key:
        await _save_profile(context, name, url, "")
        await query.message.reply_text(
            f"✅ تم حفظ وتفعيل المزوّد «{name}» (بدون مفتاح).\n"
            "اضغط 🤖 النماذج لجلب النماذج المتاحة.",
            reply_markup=kb.settings_menu(),
        )
        return ConversationHandler.END
    await query.message.reply_text(
        f"🔑 أرسل مفتاح API الخاص بـ {name}:",
        reply_markup=kb.cancel_keyboard(),
    )
    return SET_PROVIDER_KEY


async def got_provider_url(update: Update, context):
    pending = context.user_data.get("pending_profile", {})
    pending["base_url"] = update.message.text.strip()
    context.user_data["pending_profile"] = pending
    await update.message.reply_text(
        "🔑 أرسل مفتاح API (أو اكتب «بدون» إذا لم يكن مطلوبًا):",
        reply_markup=kb.cancel_keyboard(),
    )
    return SET_PROVIDER_KEY


async def got_provider_key(update: Update, context):
    pending = context.user_data.pop("pending_profile", {})
    key = update.message.text.strip()
    if key.lower() in ("بدون", "none", "skip", "-"):
        key = ""
    await _save_profile(
        context,
        pending.get("name", "مخصص"),
        pending.get("base_url", ""),
        key,
    )
    await update.message.reply_text(
        "✅ تم حفظ وتفعيل المزوّد.\nاضغط 🤖 النماذج لجلب النماذج المتاحة.",
        reply_markup=kb.settings_menu(),
    )
    return ConversationHandler.END


async def _start_model_pick(update: Update, context):
    kind = context.user_data.get("model_kind", "chat")
    label = MODEL_KIND_LABELS.get(kind, "النموذج")
    s = await _settings()
    await update.callback_query.message.reply_text("⏳ جارٍ جلب النماذج...")
    client = AIClient(s["base_url"], s["api_key"])
    try:
        models = await client.list_models()
    except AIError as exc:
        await update.callback_query.message.reply_text(
            f"❌ {exc}\nاكتب اسم {label} يدويًا:",
            reply_markup=kb.cancel_keyboard(),
        )
        return SET_MODEL
    if not models:
        await update.callback_query.message.reply_text(
            f"⚠️ لا نماذج متاحة. اكتب اسم {label} يدويًا:",
            reply_markup=kb.cancel_keyboard(),
        )
        return SET_MODEL
    models = models[:40]
    context.user_data["models"] = models
    await update.callback_query.message.reply_text(
        f"اختر {label} من القائمة أو اكتبه يدويًا:",
        reply_markup=kb.models_keyboard(models),
    )
    return SET_MODEL


async def got_base_url(update: Update, context):
    await db.set_setting("base_url", update.message.text.strip())
    await db.set_setting("active_profile", "")
    await update.message.reply_text(
        "✅ تم حفظ الرابط.", reply_markup=kb.settings_menu()
    )
    return ConversationHandler.END


async def got_api_key(update: Update, context):
    await db.set_setting("api_key", update.message.text.strip())
    await db.set_setting("active_profile", "")
    await update.message.reply_text(
        "✅ تم حفظ المفتاح.", reply_markup=kb.settings_menu()
    )
    return ConversationHandler.END


async def got_model(update: Update, context):
    kind = context.user_data.get("model_kind", "chat")
    await db.set_setting(
        MODEL_SETTING_KEYS.get(kind, "chat_model"), update.message.text.strip()
    )
    await update.message.reply_text(
        f"✅ تم تعيين {MODEL_KIND_LABELS.get(kind, 'النموذج')}.",
        reply_markup=kb.settings_menu(),
    )
    return ConversationHandler.END


async def got_system_prompt(update: Update, context):
    await db.set_setting("system_prompt", update.message.text.strip())
    await update.message.reply_text(
        "✅ تم حفظ التعليمات.", reply_markup=kb.settings_menu()
    )
    return ConversationHandler.END


async def got_memory_size(update: Update, context):
    try:
        size = int(update.message.text.strip())
        if not 2 <= size <= 200:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ أرسل رقمًا بين 2 و 200:", reply_markup=kb.cancel_keyboard()
        )
        return SET_MEMORY_SIZE
    await db.set_setting("memory_size", str(size))
    await update.message.reply_text(
        "✅ تم حفظ حجم الذاكرة.", reply_markup=kb.settings_menu()
    )
    return ConversationHandler.END


async def got_welcome(update: Update, context):
    await db.set_setting("welcome_text", update.message.text.strip())
    await update.message.reply_text(
        "✅ تم حفظ رسالة الترحيب.", reply_markup=kb.settings_menu()
    )
    return ConversationHandler.END


async def cancel(update: Update, context):
    context.user_data["mode"] = "chat"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "تم الإلغاء.", reply_markup=kb.main_menu()
        )
    else:
        await update.message.reply_text(
            "تم الإلغاء.", reply_markup=kb.main_menu()
        )
    return ConversationHandler.END


# ================= الرسائل النصية =================

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await db.upsert_user(
        user.id, update.effective_chat.id, user.username, user.first_name
    )
    text = update.message.text or ""
    mode = context.user_data.get("mode", "chat")
    async with _lock(user.id):
        if mode == "image":
            await _do_image(update, context, text)
        elif mode == "video":
            await _do_video(update, context, text)
        elif mode == "pdf":
            await _do_pdf(update, context, text)
        elif mode == "file":
            context.user_data["pending_file_text"] = text
            await update.message.reply_text(
                "اختر نوع الملف:", reply_markup=kb.filetype_keyboard()
            )
        else:
            await _do_chat(update, context, text)


async def _do_chat(update: Update, context, text: str, extra_content: str = None) -> None:
    user_id = update.effective_user.id
    s = await _settings()
    if not s["api_key"]:
        await _warn_no_key(update.message)
        return
    conv_id = await db.get_or_create_conversation(user_id)
    content = extra_content or text
    await db.add_message(conv_id, user_id, "user", content)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    messages = await memory.build_messages(conv_id, s)
    client = AIClient(s["base_url"], s["api_key"])
    try:
        reply = await client.chat(s["chat_model"], messages)
    except AIError as exc:
        await update.message.reply_text(f"❌ حدث خطأ:\n{exc}")
        return
    await db.add_message(conv_id, user_id, "assistant", reply)
    await _send(update.message, reply)
    await _maybe_autofile(update, reply)


async def _maybe_autofile(update: Update, reply: str) -> None:
    """إذا ردّ النموذج بكتلة كود، ينشئ ملفًا ويرسله تلقائيًا."""
    match = re.search(r"```(\w*)\s*\n(.*?)```", reply, re.DOTALL)
    if not match:
        return
    ext = CODE_EXT.get((match.group(1) or "txt").lower())
    code = match.group(2).strip()
    if not ext or not code:
        return
    path = filetools.write_output(update.effective_user.id, f"code.{ext}", code)
    try:
        await update.message.reply_document(
            document=str(path),
            filename=path.name,
            caption="📄 تم إنشاء الملف تلقائيًا من الكود",
        )
    except Exception:
        log.exception("فشل إرسال الملف التلقائي")


async def _do_image(update: Update, context, prompt: str) -> None:
    user_id = update.effective_user.id
    s = await _settings()
    if not s["api_key"]:
        await _warn_no_key(update.message)
        return
    await update.message.reply_text("🖼️ جارٍ إنشاء الصورة، انتظر قليلًا...")
    await context.bot.send_chat_action(
        update.effective_chat.id, ChatAction.UPLOAD_PHOTO
    )
    client = AIClient(s["base_url"], s["api_key"])
    try:
        data = await client.generate_image(s["image_model"], prompt)
    except AIError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    path = filetools.write_output_bytes(user_id, "image.png", data)
    await update.message.reply_photo(
        photo=str(path), caption="🖼️ صورتك جاهزة!"
    )


async def _do_video(update: Update, context, prompt: str) -> None:
    user_id = update.effective_user.id
    s = await _settings()
    if not s["api_key"]:
        await _warn_no_key(update.message)
        return
    await update.message.reply_text(
        "🎬 جارٍ إنشاء الفيديو... قد يستغرق ذلك عدة دقائق، سأرسله فور اكتماله."
    )
    await context.bot.send_chat_action(
        update.effective_chat.id, ChatAction.UPLOAD_VIDEO
    )
    client = AIClient(s["base_url"], s["api_key"])
    try:
        data = await client.generate_video(s["video_model"], prompt)
    except AIError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    path = filetools.write_output_bytes(user_id, "video.mp4", data)
    await update.message.reply_video(
        video=str(path), caption="🎬 الفيديو جاهز!"
    )


async def _do_pdf(update: Update, context, text: str) -> None:
    user_id = update.effective_user.id
    out_path = filetools.output_path(user_id, "document.pdf")
    try:
        pdfgen.generate_pdf(text, out_path, title="مستند")
    except Exception as exc:
        log.exception("فشل إنشاء PDF")
        await update.message.reply_text(f"❌ تعذّر إنشاء PDF: {exc}")
        return
    await update.message.reply_document(
        document=str(out_path),
        filename="document.pdf",
        caption="📕 ملف PDF جاهز!",
    )


# ================= الصور والمستندات =================

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    data = await tg_file.download_as_bytearray()
    caption = update.message.caption or (
        "صف هذه الصورة بالتفصيل: اذكر كل العناصر والألوان والنصوص الموجودة فيها."
    )
    await _vision_chat(update, context, bytes(data), "image/jpeg", caption)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    user_id = update.effective_user.id
    if doc.file_size and doc.file_size > config.MAX_FILE_SIZE:
        await update.message.reply_text(
            "⚠️ الملف كبير جدًا (الحد الأقصى 20MB)."
        )
        return
    tg_file = await doc.get_file()
    path = await filetools.save_upload(
        user_id, doc.file_name or "file", tg_file
    )
    await db.add_file(
        user_id, path.name, str(path), doc.mime_type or "", path.stat().st_size
    )
    ext = path.suffix.lower()
    mime = doc.mime_type or ""
    if mime.startswith("image/") or ext in filetools.IMAGE_EXTS:
        caption = update.message.caption or (
            "اقرأ هذه الصورة واشرح محتواها بالتفصيل."
        )
        await _vision_chat(update, context, path.read_bytes(), mime or "image/jpeg", caption)
        return
    text = filetools.extract_text(path)
    if text:
        text = text[: config.MAX_TEXT_CHARS]
        content = (
            f"📎 قرأت الملف «{path.name}» ومحتواه كالتالي:\n\n"
            f"{text}\n\n---\n"
            f"{update.message.caption or 'لخّص هذا الملف واشرح محتواه الرئيسي.'}"
        )
        await _do_chat(update, context, "", extra_content=content)
    else:
        await update.message.reply_text(
            f"📥 تم حفظ الملف «{path.name}».\n"
            f"لكن لا أستطيع قراءة هذا النوع ({ext or 'غير معروف'}). "
            "الأنواع المدعومة: PDF, TXT, DOCX, XLSX, صور, وملفات نصية/برمجية."
        )


async def _vision_chat(update: Update, context, data: bytes, mime: str, prompt: str) -> None:
    user_id = update.effective_user.id
    s = await _settings()
    if not s["api_key"]:
        await _warn_no_key(update.message)
        return
    conv_id = await db.get_or_create_conversation(user_id)
    await db.add_message(conv_id, user_id, "user", f"[صورة] {prompt}")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    messages = await memory.build_messages(conv_id, s)
    b64 = base64.b64encode(data).decode()
    messages[-1] = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            },
        ],
    }
    client = AIClient(s["base_url"], s["api_key"])
    try:
        reply = await client.chat(s["chat_model"], messages)
    except AIError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await db.add_message(conv_id, user_id, "assistant", reply)
    await _send(update.message, reply)


# ================= التسجيل =================

def register(app: Application) -> None:
    settings_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                entry_set,
                pattern=r"^set:(base_url|api_key|model|system_prompt|memory_size|welcome)(:\w+)?$",
            ),
            CallbackQueryHandler(entry_preset, pattern=r"^preset:\d+$"),
        ],
        states={
            SET_BASE_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_base_url)
            ],
            SET_API_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_api_key)
            ],
            SET_MODEL: [
                CallbackQueryHandler(_pick_model, pattern=r"^model:pick:"),
                CallbackQueryHandler(_assign_model_end, pattern=r"^model:assign:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_model),
            ],
            SET_SYSTEM_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_system_prompt)
            ],
            SET_MEMORY_SIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_memory_size)
            ],
            SET_WELCOME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_welcome)
            ],
            SET_PROVIDER_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_provider_url)
            ],
            SET_PROVIDER_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_provider_key)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            CallbackQueryHandler(cancel, pattern=r"^menu:main$"),
        ],
        allow_reentry=True,
    )
    app.add_handler(settings_conversation)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("models", cmd_models))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CallbackQueryHandler(on_callback, pattern="^"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
