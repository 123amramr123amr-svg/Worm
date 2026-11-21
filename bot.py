"""نقطة تشغيل البوت: python main.py (أو python bot.py)"""
import logging
import warnings

from telegram.ext import Application
from telegram.warnings import PTBUserWarning

# نُكتم تحذير per_message تحديدًا: هو تحذير معلوماتي يظهر لأننا نستخدم
# MessageHandler (لازم لاستقبال النصوص) مع CallbackQueryHandler (لازم للأزرار)
# داخل نفس ConversationHandler — وهو تركيب مدعوم ويعمل بشكل صحيح.
warnings.filterwarnings(
    "ignore",
    message=r".*per_message.*",
    category=PTBUserWarning,
)

import config
import db
import handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def _post_init(app: Application) -> None:
    """تُستدعى داخل حلقة أحداث البوت عند بدء التشغيل لتهيئة قاعدة البيانات."""
    await db.init_db()
    log.info("تم تهيئة قاعدة البيانات")


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit(
            "❌ BOT_TOKEN غير موجود! ضع توكن البوت في ملف .env أو متغيرات البيئة."
        )
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )
    handlers.register(app)
    if config.USE_WEBHOOK:
        if not config.WEBHOOK_URL:
            raise SystemExit(
                "❌ WEBHOOK_URL مطلوب عند تفعيل Webhook (USE_WEBHOOK=true)."
            )
        log.info("تشغيل البوت عبر Webhook على المنفذ %s", config.PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=config.BOT_TOKEN,
            webhook_url=f"{config.WEBHOOK_URL}/{config.BOT_TOKEN}",
            secret_token=config.WEBHOOK_SECRET or None,
        )
    else:
        log.info("تشغيل البوت عبر Polling")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
