import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
    GROUP_ID    = int(os.getenv("GROUP_ID", "0"))
    ADMIN_IDS   = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)

    # Grup linkleri
    MAIN_GROUP_LINK     = "https://t.me/kriptodroptr"
    CHANNEL_LINK        = "https://t.me/kriptodropduyuru"
    MAIN_GROUP_USERNAME = "@kriptodroptr"
    CHANNEL_USERNAME    = "@kriptodropduyuru"

    # Moderasyon ayarları
    MAX_WARNS               = 3
    FLOOD_MAX_MESSAGES      = 5
    FLOOD_TIME_WINDOW       = 10        # saniye
    MUTE_DURATION_ON_FLOOD  = 3_600     # 1 saat (saniye)
    MUTE_DURATION_ON_2ND_WARN = 86_400  # 24 saat (saniye)

    # Günlük rapor saati (Türkiye)
    DAILY_REPORT_HOUR   = 20
    DAILY_REPORT_MINUTE = 0
    TIMEZONE            = "Europe/Istanbul"

    # Groq model sırası (kota bitince bir sonraki denenir)
    GROQ_MODELS = [
        "llama-3.3-70b-versatile",
        "llama3-70b-8192",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
    ]
