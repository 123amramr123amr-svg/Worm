"""إعدادات البوت — تُقرأ من متغيرات البيئة (ملف .env أو الاستضافة)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
DB_PATH = DATA_DIR / "bot.db"
FONTS_DIR = BASE_DIR / "fonts"

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "false").lower() in ("1", "true", "yes")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "8080"))

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB — حد حجم الملفات المرفوعة
MAX_TEXT_CHARS = 12000  # أقصى نص مستخرج من ملف يُرسل للنموذج
AI_TIMEOUT = 180  # مهلة طلبات الذكاء الاصطناعي (ثانية)

DEFAULT_SETTINGS = {
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "chat_model": "gpt-4o-mini",
    "image_model": "dall-e-3",
    "video_model": "sora-2",
    "system_prompt": (
        "أنت مساعد ذكي وودود. أجب باللغة العربية ما لم يطلب المستخدم لغة أخرى. "
        "كن واضحًا ومختصرًا قدر الإمكان، واستخدم تنسيقًا بسيطًا (عناوين وقوائم) عند الحاجة."
    ),
    "welcome_text": (
        "🤖 أهلًا بك في بوت الذكاء الاصطناعي!\n\n"
        "أستطيع مساعدتك في:\n"
        "💬 المحادثة مع النماذج الذكية\n"
        "🧠 تذكّر سياق المحادثة (ذاكرة)\n"
        "🖼️ إنشاء الصور\n"
        "🎬 إنشاء الفيديوهات\n"
        "📕 إنشاء ملفات PDF\n"
        "📄 إنشاء ملفات برمجية (Python, HTML...)\n"
        "📥 قراءة الملفات والصور التي ترسلها\n\n"
        "⚙️ قبل البدء: أضف رابط API ومفتاحك من زر الإعدادات بالأسفل."
    ),
    "memory_enabled": "1",
    "memory_size": "20",
    "auto_delete": "0",
}
