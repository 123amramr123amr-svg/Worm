"""نقطة التشغيل الرئيسية للبوت: python main.py

بعض منصات الاستضافة تشغّل تلقائيًا `python main.py`،
لذلك هذا الملف يغلّف bot.py حتى يعمل البوت في كل الحالات.
"""
from bot import main

if __name__ == "__main__":
    main()
