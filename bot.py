"""نقطة تشغيل البوت: python bot.py"""
import asyncio
import logging

from telegram.ext import Application

import config
import db
import handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit(
            "❌ BOT_TOKEN غير موجود! ضع توكن البوت في ملف .env أو متغيرات البيئة."
        )
    asyncio.run(db.init_db())
    app = Application.builder().token(config.BOT_TOKEN).build()
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
