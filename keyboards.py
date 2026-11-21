"""لوحات الأزرار التفاعلية للبوت."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _btn(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=callback)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn("⚙️ الإعدادات", "menu:settings"), _btn("🤖 النماذج", "menu:models")],
            [_btn("🧠 الذاكرة", "menu:memory"), _btn("📁 المحادثات", "menu:convs")],
            [_btn("🛠️ الأدوات", "menu:tools"), _btn("❓ مساعدة", "menu:help")],
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn("🔗 رابط API", "set:base_url"), _btn("🔑 المفتاح", "set:api_key")],
            [_btn("💬 نموذج المحادثة", "set:model:chat"), _btn("🖼️ نموذج الصور", "set:model:image")],
            [_btn("🎬 نموذج الفيديو", "set:model:video"), _btn("📝 التعليمات", "set:system_prompt")],
            [_btn("🧠 حجم الذاكرة", "set:memory_size"), _btn("👋 رسالة الترحيب", "set:welcome")],
            [_btn("🔄 تشغيل/إيقاف الذاكرة", "set:memory_toggle")],
            [_btn("🗑️ مسح ذاكرة المحادثة", "set:clear_memory")],
            [_btn("↩️ القائمة الرئيسية", "menu:main")],
        ]
    )


def memory_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn("🔄 تشغيل/إيقاف الذاكرة", "set:memory_toggle")],
            [_btn("🧠 حجم الذاكرة", "set:memory_size")],
            [_btn("🗑️ مسح ذاكرة المحادثة الحالية", "set:clear_memory")],
            [_btn("↩️ رجوع", "menu:settings")],
        ]
    )


def tools_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [_btn("💬 محادثة", "mode:chat"), _btn("🖼️ إنشاء صورة", "mode:image")],
            [_btn("🎬 إنشاء فيديو", "mode:video"), _btn("📕 إنشاء PDF", "mode:pdf")],
            [_btn("📄 إنشاء ملف", "mode:file")],
            [_btn("↩️ القائمة الرئيسية", "menu:main")],
        ]
    )


def models_keyboard(models: list) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(models), 2):
        row = [_btn(models[i][:40], f"model:pick:{i}")]
        if i + 1 < len(models):
            row.append(_btn(models[i + 1][:40], f"model:pick:{i + 1}"))
        rows.append(row)
    rows.append([_btn("🔄 تحديث القائمة", "menu:models"), _btn("✖️ إلغاء", "cancel")])
    return InlineKeyboardMarkup(rows)


def assign_keyboard(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                _btn("💬 محادثة", f"model:assign:chat:{index}"),
                _btn("🖼️ صور", f"model:assign:image:{index}"),
            ],
            [_btn("🎬 فيديو", f"model:assign:video:{index}"), _btn("✖️ إلغاء", "cancel")],
        ]
    )


def conversations_keyboard(conversations: list, current_id) -> InlineKeyboardMarkup:
    rows = [[_btn("➕ محادثة جديدة", "conv:new")]]
    for conv in conversations:
        title = (conv.get("title") or "محادثة")[:24]
        mark = "✅ " if conv["id"] == current_id else ""
        rows.append(
            [
                _btn(f"{mark}{title}", f"conv:open:{conv['id']}"),
                _btn("🗑️", f"conv:del:{conv['id']}"),
            ]
        )
    rows.append([_btn("↩️ القائمة الرئيسية", "menu:main")])
    return InlineKeyboardMarkup(rows)


def filetype_keyboard() -> InlineKeyboardMarkup:
    types = [
        ("نصي .txt", "txt"),
        ("بايثون .py", "py"),
        ("HTML", "html"),
        ("JSON", "json"),
        ("Markdown", "md"),
        ("CSV", "csv"),
        ("JavaScript", "js"),
        ("CSS", "css"),
    ]
    rows = []
    for i in range(0, len(types), 2):
        row = [_btn(types[i][0], f"ft:{types[i][1]}")]
        if i + 1 < len(types):
            row.append(_btn(types[i + 1][0], f"ft:{types[i + 1][1]}"))
        rows.append(row)
    rows.append([_btn("✖️ إلغاء", "cancel")])
    return InlineKeyboardMarkup(rows)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("✖️ إلغاء", "cancel")]])
