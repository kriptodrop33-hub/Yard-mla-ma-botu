#!/usr/bin/env python3
"""
Airdrop Referans Yardımlaşma Grubu — Telegram Yönetim Botu
v3.0 — Yavaş Mod + Komut Menüsü + Tam Ayar Paneli
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
    BotCommand,
    MenuButtonCommands,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
)
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import Config
from database import Database
from groq_filter import GroqFilter

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#  AYAR YÖNETİCİSİ
# ═══════════════════════════════════════════════════════════════════════════════
SETTINGS_FILE = "settings.json"

class SettingsManager:
    """
    Tüm dinamik bot ayarlarını yönetir.
    Değerler settings.json dosyasına kaydedilir, bot yeniden başlasa bile korunur.
    """

    DEFS: dict = {
        # ── Yavaş Mod ─────────────────────────────────────────────
        "SLOW_MODE_ENABLED": {
            "type": "bool", "default": True,
            "label": "Yavaş Mod", "cat": "slow",
            "desc": "Üyeler arasına mesaj gönderme süresi koyar.",
        },
        "SLOW_MODE_MIN": {
            "type": "int", "default": 5, "min": 1, "max": 60, "step": 1,
            "label": "Yavaş Mod Süresi", "unit": " dk", "cat": "slow",
            "desc": "Üyeler kaç dakikada bir mesaj atabilir.",
        },
        # ── Moderasyon ────────────────────────────────────────────
        "MAX_WARNS": {
            "type": "int", "default": 3, "min": 1, "max": 10, "step": 1,
            "label": "Max Uyarı Sayısı", "unit": " uyarı", "cat": "mod",
            "desc": "Kaç uyarıdan sonra otomatik ban uygulanır.",
        },
        "MUTE_2ND_WARN_H": {
            "type": "int", "default": 24, "min": 1, "max": 168, "step": 1,
            "label": "2. Uyarı Mute Süresi", "unit": " saat", "cat": "mod",
            "desc": "2. uyarıda uygulanacak susturma süresi.",
        },
        "FLOOD_MAX_MSG": {
            "type": "int", "default": 8, "min": 3, "max": 30, "step": 1,
            "label": "Flood Mesaj Eşiği", "unit": " mesaj", "cat": "mod",
            "desc": "Kısa sürede bu kadar mesajı geçince flood sayılır.",
        },
        "FLOOD_WINDOW_S": {
            "type": "int", "default": 10, "min": 5, "max": 120, "step": 5,
            "label": "Flood Zaman Penceresi", "unit": " sn", "cat": "mod",
            "desc": "Flood sayımı için zaman aralığı (saniye).",
        },
        "FLOOD_MUTE_MIN": {
            "type": "int", "default": 60, "min": 5, "max": 1440, "step": 5,
            "label": "Flood Mute Süresi", "unit": " dk", "cat": "mod",
            "desc": "Flood tespitinde verilen susturma süresi.",
        },
        "NOTIF_DELETE_S": {
            "type": "int", "default": 30, "min": 5, "max": 120, "step": 5,
            "label": "Bildirim Silme Süresi", "unit": " sn", "cat": "mod",
            "desc": "Moderasyon bildirimlerinin kaç saniye sonra silineceği.",
        },
        # ── Filtreler ─────────────────────────────────────────────
        "AI_FILTER": {
            "type": "bool", "default": True,
            "label": "AI Küfür Filtresi", "cat": "fil",
            "desc": "Groq AI ile otomatik küfür/hakaret tespiti.",
        },
        "FLOOD_PROTECT": {
            "type": "bool", "default": True,
            "label": "Flood Koruması", "cat": "fil",
            "desc": "Hızlı mesaj gönderenleri otomatik sustur.",
        },
        "LINK_FILTER": {
            "type": "bool", "default": False,
            "label": "Link Filtresi", "cat": "fil",
            "desc": "Kapalı: Üyeler serbestçe link paylaşabilir (referans grubu için önerilen).",
        },
        "BOT_FILTER": {
            "type": "bool", "default": True,
            "label": "Bot Hesap Muafiyeti", "cat": "fil",
            "desc": "Bot hesaplarını moderasyondan muaf tut.",
        },
        # ── Günlük Rapor ──────────────────────────────────────────
        "REPORT_ENABLED": {
            "type": "bool", "default": True,
            "label": "Günlük Rapor", "cat": "rep",
            "desc": "Her gün otomatik istatistik raporu gönder.",
        },
        "REPORT_HOUR": {
            "type": "int", "default": 20, "min": 0, "max": 23, "step": 1,
            "label": "Rapor Saati", "unit": "", "cat": "rep",
            "desc": "Günlük raporun gönderileceği saat (0–23).",
        },
        "REPORT_MINUTE": {
            "type": "int", "default": 0, "min": 0, "max": 55, "step": 5,
            "label": "Rapor Dakikası", "unit": "", "cat": "rep",
            "desc": "Günlük raporun gönderileceği dakika (0, 5 … 55).",
        },
        "REPORT_LEADERBOARD": {
            "type": "bool", "default": True,
            "label": "Davet Liderleri", "cat": "rep",
            "desc": "Günlük raporda davet liderlik tablosunu göster.",
        },
        "REPORT_ACTIVE": {
            "type": "bool", "default": True,
            "label": "En Aktif Üyeler", "cat": "rep",
            "desc": "Günlük raporda en çok mesaj atanları göster.",
        },
        # ── Karşılama ─────────────────────────────────────────────
        "WELCOME_ENABLED": {
            "type": "bool", "default": True,
            "label": "Karşılama Mesajı", "cat": "wel",
            "desc": "Yeni üye katıldığında karşılama mesajı gönder.",
        },
        "WELCOME_RULES": {
            "type": "bool", "default": True,
            "label": "Karşılamada Kurallar", "cat": "wel",
            "desc": "Karşılama mesajında grup kurallarını göster.",
        },
        "WELCOME_BTNS": {
            "type": "bool", "default": True,
            "label": "Karşılamada Butonlar", "cat": "wel",
            "desc": "Karşılama mesajına kanal/grup butonları ekle.",
        },
        "WELCOME_MEMBER_COUNT": {
            "type": "bool", "default": True,
            "label": "Üye Sayısını Göster", "cat": "wel",
            "desc": "Karşılamada toplam üye sayısını belirt.",
        },
    }

    CATS = {
        "slow": {"icon": "🐢", "label": "Yavaş Mod"},
        "mod":  {"icon": "🚨", "label": "Moderasyon"},
        "fil":  {"icon": "🤖", "label": "Filtreler"},
        "rep":  {"icon": "📊", "label": "Günlük Rapor"},
        "wel":  {"icon": "👋", "label": "Karşılama"},
    }

    def __init__(self):
        self._data: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info(f"Ayarlar yüklendi ({len(self._data)} özel değer)")
            except Exception as e:
                logger.error(f"Ayar yükleme hatası: {e}")

    def _save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ayar kayıt hatası: {e}")

    def get(self, key: str):
        return self._data.get(key, self.DEFS[key]["default"])

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    def toggle(self, key: str) -> bool:
        new = not self.get(key)
        self.set(key, new)
        return new

    def increment(self, key: str, step: int) -> int:
        defn = self.DEFS[key]
        new  = max(defn["min"], min(defn["max"], self.get(key) + step))
        self.set(key, new)
        return new

    def reset_cat(self, cat: str):
        for k, d in self.DEFS.items():
            if d.get("cat") == cat:
                self._data.pop(k, None)
        self._save()


settings   = SettingsManager()
db         = Database()
groq       = GroqFilter()
TR         = pytz.timezone(Config.TIMEZONE)
BOT_START  = datetime.now(pytz.utc)
_scheduler: AsyncIOScheduler | None = None

# Son mesaj zamanı (yavaş mod): {user_id: timestamp}
slow_tracker: dict[int, float] = {}
# Flood takibi: {user_id: [timestamp, ...]}
flood_tracker: dict[int, list[float]] = defaultdict(list)

# ═══════════════════════════════════════════════════════════════════════════════
#  YARDIMCILAR
# ═══════════════════════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid in Config.ADMIN_IDS

def mention(user) -> str:
    return f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

def mid(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{name}</a>'

def _mute_perms():
    return ChatPermissions(
        can_send_messages=False, can_send_audios=False,
        can_send_documents=False, can_send_photos=False,
        can_send_videos=False, can_send_video_notes=False,
        can_send_voice_notes=False, can_send_polls=False,
        can_send_other_messages=False, can_add_web_page_previews=False,
    )

def _unmute_perms():
    return ChatPermissions(
        can_send_messages=True, can_send_audios=True,
        can_send_documents=True, can_send_photos=True,
        can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True,
        can_send_other_messages=True, can_add_web_page_previews=True,
    )

async def _del(msg, delay: int = None):
    await asyncio.sleep(delay if delay is not None else settings.get("NOTIF_DELETE_S"))
    try:
        await msg.delete()
    except Exception:
        pass

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.reply_to_message:
        return msg.reply_to_message.from_user, (" ".join(context.args) if context.args else None)
    if context.args:
        arg    = context.args[0].lstrip("@")
        reason = " ".join(context.args[1:]) or None
        try:
            uid = int(arg)
            cm  = await context.bot.get_chat_member(Config.GROUP_ID, uid)
            return cm.user, reason
        except ValueError:
            row = await db.get_user_by_username(arg)
            if row:
                cm = await context.bot.get_chat_member(Config.GROUP_ID, row["user_id"])
                return cm.user, reason
        except TelegramError:
            pass
    return None, None

def _uptime() -> str:
    d = datetime.now(pytz.utc) - BOT_START
    h, m = divmod(d.seconds, 3600)
    m //= 60
    if d.days:
        return f"{d.days}g {h}s {m}d"
    return f"{h}s {m}d" if h else f"{m}d"

# ═══════════════════════════════════════════════════════════════════════════════
#  UYARI ZİNCİRİ
# ═══════════════════════════════════════════════════════════════════════════════

async def apply_warn(ctx, user_id, fname, admin_id, reason) -> str:
    count     = await db.add_warn(user_id, admin_id, reason)
    m_        = mid(user_id, fname)
    max_warns = settings.get("MAX_WARNS")

    if count >= max_warns:
        try:
            await ctx.bot.ban_chat_member(Config.GROUP_ID, user_id)
            await db.set_banned(user_id, True)
        except TelegramError as e:
            logger.error(f"Otomatik ban: {e}")
        return f"🔨 {m_} <b>{count}. uyarısına ulaştı → BANLANDI!</b>\n📌 Sebep: {reason}"

    if count == 2:
        mh    = settings.get("MUTE_2ND_WARN_H")
        until = datetime.now(tz=pytz.utc) + timedelta(hours=mh)
        try:
            await ctx.bot.restrict_chat_member(Config.GROUP_ID, user_id, _mute_perms(), until_date=until)
            await db.set_mute(user_id, until)
        except TelegramError as e:
            logger.error(f"Otomatik mute: {e}")
        return (
            f"⚠️ {m_} <b>uyarıldı! ({count}/{max_warns})</b>\n"
            f"📌 Sebep: {reason}\n🔇 {mh} saat susturuldu!\n"
            f"❗ Bir sonraki uyarıda banlanacak!"
        )

    return (
        f"⚠️ {m_} <b>uyarıldı! ({count}/{max_warns})</b>\n"
        f"📌 Sebep: {reason}\n❗ {max_warns - count} uyarı hakkı kaldı!"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  AYARLAR PANELİ — KLAVYE & METİN ÜRETİCİLERİ
# ═══════════════════════════════════════════════════════════════════════════════

# ── Ortak yardımcılar ────────────────────────────────────────────────────────

def _bool_btn(key: str) -> InlineKeyboardButton:
    val   = settings.get(key)
    label = settings.DEFS[key]["label"]
    return InlineKeyboardButton(f"{'✅' if val else '❌'} {label}", callback_data=f"st:{key}")

def _int_row(key: str) -> list:
    d    = settings.DEFS[key]
    val  = settings.get(key)
    unit = d.get("unit", "")
    disp = f"{val:02d}" if key in ("REPORT_HOUR", "REPORT_MINUTE") else f"{val}{unit}"
    return [
        InlineKeyboardButton("◀",               callback_data=f"si:{key}:-{d['step']}"),
        InlineKeyboardButton(f"{d['label']}: {disp}", callback_data="noop"),
        InlineKeyboardButton("▶",               callback_data=f"si:{key}:{d['step']}"),
    ]

def _nav(reset_cat: str = None) -> list:
    row = []
    if reset_cat:
        row.append(InlineKeyboardButton("🔄 Sıfırla", callback_data=f"s_reset:{reset_cat}"))
    row += [
        InlineKeyboardButton("🔙 Ayarlar", callback_data="set_menu"),
        InlineKeyboardButton("🏠 Panel",   callback_data="p_back"),
    ]
    return row

# ── Ana Ayarlar Menüsü ────────────────────────────────────────────────────────

def _set_main_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🐢 Yavaş Mod",   callback_data="set_cat:slow"),
            InlineKeyboardButton("🚨 Moderasyon",   callback_data="set_cat:mod"),
        ],
        [
            InlineKeyboardButton("🤖 Filtreler",    callback_data="set_cat:fil"),
            InlineKeyboardButton("📊 Günlük Rapor", callback_data="set_cat:rep"),
        ],
        [
            InlineKeyboardButton("👋 Karşılama",    callback_data="set_cat:wel"),
            InlineKeyboardButton("📋 Değişen Ayarlar", callback_data="set_summary"),
        ],
        [InlineKeyboardButton("🔙 Ana Panel", callback_data="p_back")],
    ])

def _set_main_txt() -> str:
    now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")
    sm  = "✅ Açık" if settings.get("SLOW_MODE_ENABLED") else "❌ Kapalı"
    ai  = "✅ Açık" if settings.get("AI_FILTER")         else "❌ Kapalı"
    fl  = "✅ Açık" if settings.get("FLOOD_PROTECT")     else "❌ Kapalı"
    wl  = "✅ Açık" if settings.get("WELCOME_ENABLED")   else "❌ Kapalı"
    rep = "✅ Açık" if settings.get("REPORT_ENABLED")    else "❌ Kapalı"
    h, m_= settings.get("REPORT_HOUR"), settings.get("REPORT_MINUTE")
    return (
        f"⚙️ <b>AYARLAR</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📅 {now}\n\n"
        f"<b>Hızlı Durum:</b>\n"
        f"🐢 Yavaş Mod: <b>{sm}</b> ({settings.get('SLOW_MODE_MIN')} dk)\n"
        f"🤖 AI Filtre: <b>{ai}</b>  🌊 Flood: <b>{fl}</b>\n"
        f"👋 Karşılama: <b>{wl}</b>  📊 Rapor: <b>{rep}</b> {h:02d}:{m_:02d}\n\n"
        f"Düzenlemek istediğin kategoriyi seç:"
    )

# ── Yavaş Mod ────────────────────────────────────────────────────────────────

def _slow_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_bool_btn("SLOW_MODE_ENABLED")],
        _int_row("SLOW_MODE_MIN"),
        _nav("slow"),
    ])

def _slow_txt() -> str:
    enabled = settings.get("SLOW_MODE_ENABLED")
    mins    = settings.get("SLOW_MODE_MIN")
    return (
        f"🐢 <b>YAVAŞ MOD AYARLARI</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"Durum: <b>{'✅ Açık' if enabled else '❌ Kapalı'}</b>\n"
        f"Süre: <b>{mins} dakika</b>\n\n"
        f"<i>Yavaş mod açıkken üyeler yalnızca {mins} dakikada bir\n"
        f"mesaj gönderebilir. Kuralı ihlal eden mesajlar otomatik\n"
        f"silinerek kullanıcıya bildirim gönderilir.\n\n"
        f"Adminler ve bot hesapları bu kuraldan muaftır.</i>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"◀ ▶ ile süreyi dakika dakika ayarlayın."
    )

# ── Moderasyon ───────────────────────────────────────────────────────────────

def _mod_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _int_row("MAX_WARNS"),
        _int_row("MUTE_2ND_WARN_H"),
        _int_row("FLOOD_MAX_MSG"),
        _int_row("FLOOD_WINDOW_S"),
        _int_row("FLOOD_MUTE_MIN"),
        _int_row("NOTIF_DELETE_S"),
        _nav("mod"),
    ])

def _mod_txt() -> str:
    s = settings
    return (
        f"🚨 <b>MODERASYON AYARLARI</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"⚠️ Max Uyarı: <b>{s.get('MAX_WARNS')} uyarı</b>\n"
        f"   <i>Bu sayıdan sonra otomatik ban</i>\n\n"
        f"🔇 2. Uyarı Mute: <b>{s.get('MUTE_2ND_WARN_H')} saat</b>\n\n"
        f"🌊 Flood Eşiği: <b>{s.get('FLOOD_MAX_MSG')} mesaj / {s.get('FLOOD_WINDOW_S')} sn</b>\n\n"
        f"⏳ Flood Mute: <b>{s.get('FLOOD_MUTE_MIN')} dakika</b>\n\n"
        f"🗑 Bildirim Silme: <b>{s.get('NOTIF_DELETE_S')} saniye</b>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"◀ ▶ ile değerleri değiştir · 🔄 varsayılana döner."
    )

# ── Filtreler ─────────────────────────────────────────────────────────────────

def _fil_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_bool_btn("AI_FILTER")],
        [_bool_btn("FLOOD_PROTECT")],
        [_bool_btn("LINK_FILTER")],
        [_bool_btn("BOT_FILTER")],
        _nav("fil"),
    ])

def _fil_txt() -> str:
    def st(k): return "✅ Açık" if settings.get(k) else "❌ Kapalı"
    return (
        f"🤖 <b>FİLTRE AYARLARI</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"AI Küfür Filtresi: <b>{st('AI_FILTER')}</b>\n"
        f"   <i>Groq AI ile küfür/hakaret tespiti</i>\n\n"
        f"Flood Koruması: <b>{st('FLOOD_PROTECT')}</b>\n"
        f"   <i>Burst mesaj gönderimi engelle</i>\n\n"
        f"Link Filtresi: <b>{st('LINK_FILTER')}</b>\n"
        f"   <i>⚠️ Referans grubu için KAPALI önerilir</i>\n\n"
        f"Bot Muafiyeti: <b>{st('BOT_FILTER')}</b>\n"
        f"   <i>Bot hesaplarını moderasyondan muaf tut</i>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Butona tıklayarak Aç/Kapat yapabilirsin."
    )

# ── Günlük Rapor ─────────────────────────────────────────────────────────────

def _rep_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_bool_btn("REPORT_ENABLED")],
        _int_row("REPORT_HOUR"),
        _int_row("REPORT_MINUTE"),
        [_bool_btn("REPORT_LEADERBOARD")],
        [_bool_btn("REPORT_ACTIVE")],
        _nav("rep"),
    ])

def _rep_txt() -> str:
    def st(k): return "✅ Açık" if settings.get(k) else "❌ Kapalı"
    h, m_ = settings.get("REPORT_HOUR"), settings.get("REPORT_MINUTE")
    return (
        f"📊 <b>GÜNLÜK RAPOR AYARLARI</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"Günlük Rapor: <b>{st('REPORT_ENABLED')}</b>\n\n"
        f"⏰ Gönderim Saati: <b>{h:02d}:{m_:02d}</b>\n"
        f"   <i>Her gün bu saatte gruba gönderilir</i>\n\n"
        f"Davet Liderleri: <b>{st('REPORT_LEADERBOARD')}</b>\n"
        f"En Aktif Üyeler: <b>{st('REPORT_ACTIVE')}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Saat değişikliği sonraki raporu etkiler."
    )

# ── Karşılama ─────────────────────────────────────────────────────────────────

def _wel_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_bool_btn("WELCOME_ENABLED")],
        [_bool_btn("WELCOME_RULES")],
        [_bool_btn("WELCOME_BTNS")],
        [_bool_btn("WELCOME_MEMBER_COUNT")],
        _nav("wel"),
    ])

def _wel_txt() -> str:
    def st(k): return "✅ Açık" if settings.get(k) else "❌ Kapalı"
    return (
        f"👋 <b>KARŞILAMA AYARLARI</b>\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"Karşılama Mesajı: <b>{st('WELCOME_ENABLED')}</b>\n"
        f"   <i>Yeni üye katılınca mesaj gönder</i>\n\n"
        f"Kuralları Göster: <b>{st('WELCOME_RULES')}</b>\n"
        f"Butonları Göster: <b>{st('WELCOME_BTNS')}</b>\n"
        f"Üye Sayısını Göster: <b>{st('WELCOME_MEMBER_COUNT')}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"Butona tıklayarak Aç/Kapat yapabilirsin."
    )

# ── Değişen Ayarlar Özeti ─────────────────────────────────────────────────────

def _summary_txt() -> str:
    changed = []
    for key, defn in SettingsManager.DEFS.items():
        cur, default = settings.get(key), defn["default"]
        if cur != default:
            cat = SettingsManager.CATS.get(defn.get("cat", ""), {}).get("label", "")
            if defn["type"] == "bool":
                val_s = "✅ Açık" if cur else "❌ Kapalı"
            else:
                val_s = f"{cur}{defn.get('unit', '')}"
            changed.append(f"[{cat}] {defn['label']}: <b>{val_s}</b>")
    if not changed:
        body = "✅ Tüm ayarlar varsayılan değerlerde."
    else:
        body = f"Varsayılandan farklı <b>{len(changed)}</b> ayar:\n\n" + "\n".join(changed)
    return f"📋 <b>DEĞİŞEN AYARLAR</b>\n━━━━━━━━━━━━━━━━━\n\n{body}"

# ── Kategori helper ───────────────────────────────────────────────────────────

def _refresh_cat(cat: str, txt_fn, kbd_fn):
    return txt_fn(), kbd_fn()

CAT_MAP = {
    "slow": (_slow_txt, _slow_kbd),
    "mod":  (_mod_txt,  _mod_kbd),
    "fil":  (_fil_txt,  _fil_kbd),
    "rep":  (_rep_txt,  _rep_kbd),
    "wel":  (_wel_txt,  _wel_kbd),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  ANA PANEL
# ═══════════════════════════════════════════════════════════════════════════════

def _panel_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 İstatistikler",     callback_data="p_stats"),
            InlineKeyboardButton("🏆 Liderlik",          callback_data="p_top"),
        ],
        [
            InlineKeyboardButton("⚠️ Son Uyarılar",      callback_data="p_warns"),
            InlineKeyboardButton("🔇 Susturulanlar",      callback_data="p_muted"),
        ],
        [
            InlineKeyboardButton("🚫 Banlılar",          callback_data="p_banned"),
            InlineKeyboardButton("👤 Kullanıcı Sorgula", callback_data="p_user_prompt"),
        ],
        [
            InlineKeyboardButton("📢 Gruba Duyuru",      callback_data="p_announce"),
            InlineKeyboardButton("🤖 Bot Durumu",         callback_data="p_botstatus"),
        ],
        [
            InlineKeyboardButton("📋 Komut Listesi",     callback_data="p_commands"),
            InlineKeyboardButton("🔄 Günlük Rapor",       callback_data="p_report"),
        ],
        [
            InlineKeyboardButton("⚙️ Ayarlar",           callback_data="set_menu"),
        ],
    ])

def _back_kbd() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ana Panel", callback_data="p_back")]])

def _back_refresh(cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Yenile",    callback_data=cb),
        InlineKeyboardButton("🔙 Ana Panel", callback_data="p_back"),
    ]])

def _panel_txt(fname: str) -> str:
    now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")
    return (
        f"🎛️ <b>ADMİN PANELİ</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"👤 {fname} | 📅 {now}\n\n"
        f"Aşağıdan işlem seçin:"
    )

def _leaderboard(rows) -> str:
    if not rows:
        return "📊 Henüz davet verisi yok."
    medals = ["🥇","🥈","🥉"] + ["🔸"]*7
    lines  = ["🏆 <b>DAVET LİDERLİK TABLOSU</b>\n━━━━━━━━━━━━━━━━━\n"]
    for i, r in enumerate(rows):
        name  = r["first_name"] or "Kullanıcı"
        uname = f"@{r['username']}" if r["username"] else name
        lines.append(f"{medals[i]} {uname} — <b>{r['invite_count']} davet</b>")
    return "\n".join(lines)

async def _stats_txt(ctx) -> str:
    s = await db.get_group_stats()
    try:    cnt = await ctx.bot.get_chat_member_count(Config.GROUP_ID)
    except: cnt = s["total_users"]
    td  = s.get("today") or {}
    now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")
    return (
        f"📊 <b>GRUP İSTATİSTİKLERİ</b>\n━━━━━━━━━━━━━━━━━\n📅 {now}\n\n"
        f"👥 Toplam Üye: <b>{cnt}</b>\n"
        f"📈 Bugün Katılan: <b>+{td.get('new_members',0)}</b>\n"
        f"📉 Bugün Ayrılan: <b>-{td.get('left_members',0)}</b>\n"
        f"💬 Toplam Mesaj: <b>{s['total_messages']}</b>\n"
        f"💬 Bugün Mesaj: <b>{td.get('total_messages',0)}</b>\n"
        f"🔗 Toplam Davet: <b>{s['total_invites']}</b>\n"
        f"⚠️ Toplam Uyarı: <b>{s['total_warns']}</b>"
    )

async def _botstatus_txt(ctx) -> str:
    s = await db.get_group_stats()
    try:    mc = await ctx.bot.get_chat_member_count(Config.GROUP_ID)
    except: mc = "?"
    try:
        bi = await ctx.bot.get_me()
        bname = f"{bi.first_name} (@{bi.username})"
    except:
        bname = "Bot"
    muted  = await db.get_muted_users()
    banned = await db.get_banned_users() if hasattr(db, "get_banned_users") else []
    now    = datetime.now(TR).strftime("%d.%m.%Y %H:%M")
    h, m_  = settings.get("REPORT_HOUR"), settings.get("REPORT_MINUTE")
    def st(k): return "✅" if settings.get(k) else "❌"
    return (
        f"🤖 <b>BOT DURUM RAPORU</b>\n━━━━━━━━━━━━━━━━━\n"
        f"📛 {bname}\n⏱ Uptime: <b>{_uptime()}</b>\n📅 {now}\n\n"
        f"<b>📌 Grup</b>\n"
        f"├ 👥 Üye: <b>{mc}</b>  🔇 Susturulan: <b>{len(muted)}</b>  🚫 Banlı: <b>{len(banned)}</b>\n"
        f"├ ⚠️ Toplam Uyarı: <b>{s['total_warns']}</b>\n"
        f"└ 💬 Toplam Mesaj: <b>{s['total_messages']}</b>\n\n"
        f"<b>⚙️ Aktif Ayarlar</b>\n"
        f"├ 🐢 Yavaş Mod: {st('SLOW_MODE_ENABLED')} ({settings.get('SLOW_MODE_MIN')} dk)\n"
        f"├ 🤖 AI Filtre: {st('AI_FILTER')}  🌊 Flood: {st('FLOOD_PROTECT')}\n"
        f"├ 🔗 Link Filtre: {st('LINK_FILTER')}  👋 Karşılama: {st('WELCOME_ENABLED')}\n"
        f"├ ⚠️ Max Uyarı: <b>{settings.get('MAX_WARNS')}</b>\n"
        f"└ 📊 Rapor: {st('REPORT_ENABLED')} → <b>{h:02d}:{m_:02d}</b>"
    )

def _commands_txt() -> str:
    return (
        "📋 <b>ADMİN KOMUT REHBERİ</b>\n━━━━━━━━━━━━━━━━━\n\n"
        "🐢 <b>YAVAŞ MOD</b>\n"
        "└ <code>/ayarlar</code> → 🐢 Yavaş Mod ile yönet\n\n"
        "🚨 <b>MODERASYON</b>\n"
        "├ <code>/ban [@u|reply] [sebep]</code> — Banla\n"
        "├ <code>/unban [@u|reply]</code> — Ban kaldır\n"
        "├ <code>/kick [@u|reply] [sebep]</code> — At\n"
        "├ <code>/mute [@u|reply] [dk] [sebep]</code> — Sustur\n"
        "└ <code>/unmute [@u|reply]</code> — Susturmayı kaldır\n\n"
        "⚠️ <b>UYARI</b>\n"
        "├ <code>/warn [@u|reply] [sebep]</code>\n"
        "├ <code>/unwarn [@u|reply]</code>\n"
        "├ <code>/resetwarns [@u|reply]</code>\n"
        "└ <code>/warnings [@u|reply]</code>\n\n"
        "📢 <b>DUYURU</b>\n"
        "├ <code>/duyuru [metin]</code> — Biçimlendirilmiş\n"
        "└ <code>/broadcast [metin]</code> — Ham mesaj\n\n"
        "🔍 <b>SORGULAMA</b>\n"
        "├ <code>/userinfo [@u|reply]</code>\n"
        "├ <code>/banlist</code>\n"
        "├ <code>/stats</code>  ├ <code>/top</code>\n\n"
        "🛠️ <b>YÖNETİM</b>\n"
        "├ <code>/temizle [N]</code> — Son N mesajı sil\n"
        "├ <code>/purgefrom</code> — Reply'den sil\n"
        "├ <code>/davetlink</code> — Takipli davet linki\n"
        "├ <code>/rapor</code> — Raporu tetikle\n"
        "├ <code>/ayarlar</code> — Tüm bot ayarları\n"
        "├ <code>/rules</code>  ├ <code>/ping</code>\n"
        "└ <code>/panel</code>  — Ana panel"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  YENİ ÜYE KARŞILAMA
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = update.chat_member
    if res.chat.id != Config.GROUP_ID:
        return

    old, new = res.old_chat_member.status, res.new_chat_member.status

    if (old in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
            and new in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)):

        user = res.new_chat_member.user
        if user.is_bot and settings.get("BOT_FILTER"):
            return

        await db.upsert_user(user.id, user.username, user.first_name)
        await db.update_daily_new_member()

        if res.invite_link:
            owner = await db.get_invite_link_owner(res.invite_link.invite_link)
            if owner and owner != user.id:
                await db.add_invite(owner, user.id)

        if not settings.get("WELCOME_ENABLED"):
            return

        count_str = ""
        if settings.get("WELCOME_MEMBER_COUNT"):
            try:
                cnt = await context.bot.get_chat_member_count(Config.GROUP_ID)
                count_str = f"👥 Artık <b>{cnt}</b>. üyesiniz!\n\n"
            except Exception:
                pass

        rules_str = ""
        if settings.get("WELCOME_RULES"):
            mw = settings.get("MAX_WARNS")
            rules_str = (
                f"📌 <b>Grup Kuralları:</b>\n"
                f"├ ✅ Airdrop referans ve link paylaşımı serbesttir\n"
                f"├ ✅ Saygılı ve yardımsever olun\n"
                f"├ ❌ Spam / flood yasaktır\n"
                f"├ ❌ Küfür ve hakaret → anında ban\n"
                f"└ ❌ Konu dışı reklam → ban\n\n"
                f"⚠️ <b>{mw} uyarı = kalıcı ban!</b>\n"
            )

        slow_str = ""
        if settings.get("SLOW_MODE_ENABLED"):
            slow_str = (
                f"🐢 <b>Yavaş Mod:</b> {settings.get('SLOW_MODE_MIN')} dakikada bir mesaj\n"
            )

        text = (
            f"🎉 <b>Hoş Geldin, {mention(user)}!</b>\n\n"
            f"🤝 <b>Airdrop Referans Yardımlaşma Grubu</b>'na katıldın!\n"
            f"{count_str}{rules_str}{slow_str}"
            f"━━━━━━━━━━━━━━━━━"
        )

        kbd = None
        if settings.get("WELCOME_BTNS"):
            kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📢 Duyuru Kanalı", url=Config.CHANNEL_LINK),
                    InlineKeyboardButton("👥 Ana Grup",       url=Config.MAIN_GROUP_LINK),
                ],
                [
                    InlineKeyboardButton("📋 Grup Kuralları",   callback_data="cb_rules"),
                    InlineKeyboardButton("🏆 Liderlik Tablosu", callback_data="cb_top"),
                ],
            ])

        try:
            await context.bot.send_message(
                Config.GROUP_ID, text, parse_mode=ParseMode.HTML, reply_markup=kbd
            )
        except TelegramError as e:
            logger.error(f"Karşılama hatası: {e}")

    elif (old in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)
              and new in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)):
        await db.update_daily_left_member()

# ═══════════════════════════════════════════════════════════════════════════════
#  MESAJ MODERASYOnu
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return
    if msg.chat.id != Config.GROUP_ID:
        return

    # Admin → sadece say
    if is_admin(user.id):
        await db.increment_message_count(user.id)
        return

    await db.upsert_user(user.id, user.username, user.first_name)

    # ── Yavaş Mod ────────────────────────────────────────────────────────
    if settings.get("SLOW_MODE_ENABLED"):
        cooldown = settings.get("SLOW_MODE_MIN") * 60
        now      = time.time()
        last     = slow_tracker.get(user.id, 0)
        elapsed  = now - last

        if elapsed < cooldown:
            remaining  = int(cooldown - elapsed)
            rm, rs     = divmod(remaining, 60)
            time_str   = f"{rm}:{rs:02d}" if rm else f"{rs} saniye"

            try:
                await msg.delete()
            except Exception:
                pass

            try:
                notif = await context.bot.send_message(
                    Config.GROUP_ID,
                    f"🐢 {mention(user)} yavaş mod aktif!\n"
                    f"⏳ <b>{time_str}</b> sonra tekrar yazabilirsin.",
                    parse_mode=ParseMode.HTML,
                )
                asyncio.create_task(_del(notif, 8))
            except TelegramError:
                pass
            return

        slow_tracker[user.id] = now

    # ── Flood Koruması ────────────────────────────────────────────────────
    if settings.get("FLOOD_PROTECT"):
        now = time.time()
        ts  = [t for t in flood_tracker[user.id]
               if now - t < settings.get("FLOOD_WINDOW_S")]
        ts.append(now)
        flood_tracker[user.id] = ts

        if len(ts) > settings.get("FLOOD_MAX_MSG"):
            flood_tracker[user.id] = []
            fm    = settings.get("FLOOD_MUTE_MIN")
            until = datetime.now(tz=pytz.utc) + timedelta(minutes=fm)
            try:
                await context.bot.restrict_chat_member(
                    Config.GROUP_ID, user.id, _mute_perms(), until_date=until
                )
                await db.set_mute(user.id, until)
                notif = await msg.reply_text(
                    f"🚫 {mention(user)} <b>flood yaptığı için {fm} dakika susturuldu!</b>",
                    parse_mode=ParseMode.HTML,
                )
                asyncio.create_task(_del(notif, 15))
            except TelegramError as e:
                logger.error(f"Flood mute: {e}")
            return

    # ── Link Filtresi (sadece açıksa) ────────────────────────────────────
    if settings.get("LINK_FILTER"):
        raw = msg.text or msg.caption or ""
        if any(x in raw for x in ("http://", "https://", "t.me/")):
            try:
                await msg.delete()
                notif = await context.bot.send_message(
                    Config.GROUP_ID,
                    f"🔗 {mention(user)} bu grupta link paylaşımı kısıtlıdır.",
                    parse_mode=ParseMode.HTML,
                )
                asyncio.create_task(_del(notif, 8))
            except TelegramError:
                pass
            return

    # ── AI Küfür Filtresi ─────────────────────────────────────────────────
    if settings.get("AI_FILTER"):
        text = msg.text or msg.caption or ""
        if text and len(text) >= 3:
            try:
                if await groq.is_profanity(text):
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    result = await apply_warn(
                        context, user.id, user.first_name, 0, "Küfür / hakaret"
                    )
                    notif = await context.bot.send_message(
                        Config.GROUP_ID, result, parse_mode=ParseMode.HTML
                    )
                    asyncio.create_task(_del(notif, 40))
                    return
            except Exception as e:
                logger.error(f"Profanity check: {e}")

    await db.increment_message_count(user.id)

# ═══════════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()

    # ── Herkese açık ──────────────────────────────────────────────────────
    if data == "cb_rules":
        mw = settings.get("MAX_WARNS")
        sm = f"\n🐢 Yavaş Mod: {settings.get('SLOW_MODE_MIN')} dk" if settings.get("SLOW_MODE_ENABLED") else ""
        await q.message.reply_text(
            f"📋 <b>GRUP KURALLARI</b>\n━━━━━━━━━━━━━━━━━\n\n"
            f"1️⃣ Airdrop referans ve link paylaşımı <b>serbesttir</b>\n"
            f"2️⃣ Başkasının referans linkini <b>değiştirmeyin</b>\n"
            f"3️⃣ Saygılı ve yardımsever olun\n"
            f"4️⃣ Spam / flood → <b>susturma</b>\n"
            f"5️⃣ Küfür / hakaret → <b>anında ban</b>\n"
            f"6️⃣ Konu dışı reklam → <b>ban</b>{sm}\n\n"
            f"⚠️ <b>{mw} uyarı = kalıcı ban!</b>\n\n"
            f"📢 {Config.CHANNEL_USERNAME} | 👥 {Config.MAIN_GROUP_USERNAME}",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "cb_top":
        rows = await db.get_invite_leaderboard(10)
        await q.message.reply_text(_leaderboard(rows), parse_mode=ParseMode.HTML)
        return

    if data == "noop":
        return

    # ── Admin kontrolü ────────────────────────────────────────────────────
    if not is_admin(uid):
        await q.answer("❌ Yalnızca adminler kullanabilir!", show_alert=True)
        return

    # ════════════════════════════════════════════════════════════════
    #  AYARLAR CALLBACK'LERİ
    # ════════════════════════════════════════════════════════════════

    if data == "set_menu":
        try:
            await q.message.edit_text(
                _set_main_txt(), parse_mode=ParseMode.HTML, reply_markup=_set_main_kbd()
            )
        except Exception: pass
        return

    if data == "set_summary":
        try:
            await q.message.edit_text(
                _summary_txt(), parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Ayarlar", callback_data="set_menu")
                ]]),
            )
        except Exception: pass
        return

    if data.startswith("set_cat:"):
        cat = data.split(":")[1]
        if cat in CAT_MAP:
            txt_fn, kbd_fn = CAT_MAP[cat]
            try:
                await q.message.edit_text(
                    txt_fn(), parse_mode=ParseMode.HTML, reply_markup=kbd_fn()
                )
            except Exception: pass
        return

    # Sayısal artır/azalt   si:KEY:STEP
    if data.startswith("si:"):
        _, key, step_s = data.split(":")
        step = int(step_s)
        if key in settings.DEFS and settings.DEFS[key]["type"] == "int":
            new_val = settings.increment(key, step)
            unit    = settings.DEFS[key].get("unit","")
            await q.answer(f"✅ {settings.DEFS[key]['label']}: {new_val}{unit}")
            cat = settings.DEFS[key].get("cat","")
            if cat in CAT_MAP:
                txt_fn, kbd_fn = CAT_MAP[cat]
                try:
                    await q.message.edit_text(
                        txt_fn(), parse_mode=ParseMode.HTML, reply_markup=kbd_fn()
                    )
                except Exception: pass
        return

    # Bool toggle   st:KEY
    if data.startswith("st:"):
        key = data[3:]
        if key in settings.DEFS and settings.DEFS[key]["type"] == "bool":
            new_val = settings.toggle(key)
            label   = settings.DEFS[key]["label"]
            await q.answer(f"{'✅ Açıldı' if new_val else '❌ Kapatıldı'}: {label}")
            cat = settings.DEFS[key].get("cat","")
            if cat in CAT_MAP:
                txt_fn, kbd_fn = CAT_MAP[cat]
                try:
                    await q.message.edit_text(
                        txt_fn(), parse_mode=ParseMode.HTML, reply_markup=kbd_fn()
                    )
                except Exception: pass
        return

    # Kategori sıfırla   s_reset:CAT
    if data.startswith("s_reset:"):
        cat = data.split(":")[1]
        settings.reset_cat(cat)
        cat_label = SettingsManager.CATS.get(cat,{}).get("label","Kategori")
        await q.answer(f"🔄 {cat_label} varsayılana döndürüldü!", show_alert=True)
        if cat in CAT_MAP:
            txt_fn, kbd_fn = CAT_MAP[cat]
            try:
                await q.message.edit_text(
                    txt_fn(), parse_mode=ParseMode.HTML, reply_markup=kbd_fn()
                )
            except Exception: pass
        return

    # ════════════════════════════════════════════════════════════════
    #  ANA PANEL CALLBACK'LERİ
    # ════════════════════════════════════════════════════════════════

    if data == "p_back":
        try:
            await q.message.edit_text(
                _panel_txt(q.from_user.first_name),
                parse_mode=ParseMode.HTML, reply_markup=_panel_kbd()
            )
        except Exception: pass
        return

    if data == "p_stats":
        text = await _stats_txt(context)
        try:
            await q.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=_back_refresh("p_stats")
            )
        except Exception: pass
        return

    if data == "p_top":
        rows = await db.get_invite_leaderboard(10)
        try:
            await q.message.edit_text(
                _leaderboard(rows), parse_mode=ParseMode.HTML,
                reply_markup=_back_refresh("p_top")
            )
        except Exception: pass
        return

    if data == "p_warns":
        rows = await db.get_recent_warnings(10)
        if not rows:
            text = "⚠️ Kayıtlı uyarı yok."
        else:
            lines = ["⚠️ <b>SON 10 UYARI</b>\n━━━━━━━━━━━━━━━━━\n"]
            for r in rows:
                dt   = r["created_at"].strftime("%d.%m %H:%M")
                name = r["first_name"] or "Kullanıcı"
                lines.append(f"• {mid(r['user_id'], name)} — {r['reason']} [{dt}]")
            text = "\n".join(lines)
        try:
            await q.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=_back_refresh("p_warns")
            )
        except Exception: pass
        return

    if data == "p_muted":
        rows = await db.get_muted_users()
        if not rows:
            text = "🔇 Susturulmuş kullanıcı yok."
        else:
            lines = ["🔇 <b>SUSTURULANLAR</b>\n━━━━━━━━━━━━━━━━━\n"]
            for r in rows:
                until = r["mute_until"].strftime("%d.%m %H:%M") if r["mute_until"] else "Süresiz"
                name  = r["first_name"] or "Kullanıcı"
                lines.append(f"• {mid(r['user_id'], name)} → {until}")
            text = "\n".join(lines)
        try:
            await q.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=_back_refresh("p_muted")
            )
        except Exception: pass
        return

    if data == "p_banned":
        try:    rows = await db.get_banned_users()
        except: rows = []
        if not rows:
            text = "🚫 Banlı kullanıcı kaydı yok."
        else:
            lines = [f"🚫 <b>BANLI KULLANICILAR</b> ({len(rows)} kişi)\n━━━━━━━━━━━━━━━━━\n"]
            for r in rows[:20]:
                name  = r.get("first_name") or "Kullanıcı"
                uname = f" @{r['username']}" if r.get("username") else ""
                lines.append(f"• {mid(r['user_id'], name)}{uname}")
            if len(rows) > 20:
                lines.append(f"\n<i>+{len(rows)-20} kişi daha</i>")
            text = "\n".join(lines)
        try:
            await q.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=_back_refresh("p_banned")
            )
        except Exception: pass
        return

    if data == "p_user_prompt":
        try:
            await q.message.edit_text(
                "👤 <b>KULLANICI SORGULA</b>\n━━━━━━━━━━━━━━━━━\n\n"
                "DM'e dönün ve kullanın:\n\n"
                "<code>/userinfo @kullanıcı_adı</code>\n"
                "veya\n"
                "<code>/userinfo kullanıcı_id</code>\n\n"
                "<i>Grupta mesajına reply yaparak da kullanılabilir.</i>",
                parse_mode=ParseMode.HTML, reply_markup=_back_kbd()
            )
        except Exception: pass
        return

    if data == "p_announce":
        try:
            await q.message.edit_text(
                "📢 <b>GRUBA DUYURU GÖNDER</b>\n━━━━━━━━━━━━━━━━━\n\n"
                "DM'e dönün ve kullanın:\n\n"
                "<code>/duyuru [mesajınız]</code>\n\n"
                "Duyuru admin imzasıyla otomatik biçimlendirilir.",
                parse_mode=ParseMode.HTML, reply_markup=_back_kbd()
            )
        except Exception: pass
        return

    if data == "p_botstatus":
        text = await _botstatus_txt(context)
        try:
            await q.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=_back_refresh("p_botstatus")
            )
        except Exception: pass
        return

    if data == "p_commands":
        try:
            await q.message.edit_text(
                _commands_txt(), parse_mode=ParseMode.HTML, reply_markup=_back_kbd()
            )
        except Exception: pass
        return

    if data == "p_report":
        await q.answer("⏳ Rapor gönderiliyor...", show_alert=False)
        try:
            await send_daily_report(context.application)
            await q.message.edit_text(
                "✅ <b>Günlük rapor gruba gönderildi!</b>",
                parse_mode=ParseMode.HTML, reply_markup=_back_kbd()
            )
        except Exception as e:
            await q.message.edit_text(
                f"❌ Rapor gönderilemedi: {e}",
                parse_mode=ParseMode.HTML, reply_markup=_back_kbd()
            )
        return

# ═══════════════════════════════════════════════════════════════════════════════
#  KOMUTLAR
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type != "private":
        return

    if not is_admin(user.id):
        await update.effective_message.reply_text(
            "👋 <b>Merhaba!</b>\n\n"
            "Ben <b>Airdrop Referans Yardımlaşma Grubu</b> botuyum.\n"
            "Gruba katılmak için aşağıdaki butona tıklayabilirsin!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Gruba Katıl",     url=Config.MAIN_GROUP_LINK)],
                [InlineKeyboardButton("📢 Kanalı Takip Et", url=Config.CHANNEL_LINK)],
            ]),
        )
        return

    s = await db.get_group_stats()
    try:    mc = await context.bot.get_chat_member_count(Config.GROUP_ID)
    except: mc = s.get("total_users","?")
    td  = s.get("today") or {}
    now = datetime.now(TR).strftime("%d.%m.%Y %H:%M")

    await update.effective_message.reply_text(
        f"🎛️ <b>ADMİN PANELİ</b>\n━━━━━━━━━━━━━━━━━\n"
        f"👤 Hoş geldin, <b>{user.first_name}</b>!\n"
        f"📅 {now} | ⏱ Uptime: <b>{_uptime()}</b>\n\n"
        f"<b>📌 Hızlı Durum</b>\n"
        f"├ 👥 Toplam Üye: <b>{mc}</b>\n"
        f"├ 📈 Bugün Katılan: <b>+{td.get('new_members',0)}</b>\n"
        f"├ 💬 Bugün Mesaj: <b>{td.get('total_messages',0)}</b>\n"
        f"└ ⚠️ Toplam Uyarı: <b>{s['total_warns']}</b>\n"
        f"━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎛️ Admin Paneli", callback_data="p_back"),
                InlineKeyboardButton("⚙️ Ayarlar",      callback_data="set_menu"),
            ],
            [
                InlineKeyboardButton("📊 İstatistikler", callback_data="p_stats"),
                InlineKeyboardButton("📋 Komutlar",       callback_data="p_commands"),
            ],
            [
                InlineKeyboardButton("📢 Kanal",  url=Config.CHANNEL_LINK),
                InlineKeyboardButton("👥 Grup",   url=Config.MAIN_GROUP_LINK),
            ],
        ]),
    )

async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.effective_message.reply_text(
        _panel_txt(update.effective_user.first_name),
        parse_mode=ParseMode.HTML, reply_markup=_panel_kbd()
    )

async def cmd_ayarlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.effective_message.reply_text(
        _set_main_txt(), parse_mode=ParseMode.HTML, reply_markup=_set_main_kbd()
    )

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin! (reply veya @kullanıcı)")
        return
    reason = reason or "Belirtilmedi"
    try:
        await context.bot.ban_chat_member(Config.GROUP_ID, target.id)
        await db.set_banned(target.id, True)
        notif = await update.effective_message.reply_text(
            f"🔨 {mention(target)} <b>gruptan banlandı!</b>\n📌 Sebep: {reason}",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_del(notif))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Ban başarısız: {e}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    try:
        await context.bot.unban_chat_member(Config.GROUP_ID, target.id, only_if_banned=True)
        await db.set_banned(target.id, False)
        notif = await update.effective_message.reply_text(
            f"✅ {mention(target)} <b>banı kaldırıldı!</b>", parse_mode=ParseMode.HTML
        )
        asyncio.create_task(_del(notif))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Unban başarısız: {e}")

async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    reason = reason or "Belirtilmedi"
    try:
        await context.bot.ban_chat_member(Config.GROUP_ID, target.id)
        await asyncio.sleep(1)
        await context.bot.unban_chat_member(Config.GROUP_ID, target.id)
        notif = await update.effective_message.reply_text(
            f"👢 {mention(target)} <b>gruptan atıldı!</b>\n📌 Sebep: {reason}",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_del(notif))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Kick başarısız: {e}")

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    duration = 60
    if context.args:
        try:
            duration = int(context.args[0])
            reason   = " ".join(context.args[1:]) or reason or "Belirtilmedi"
        except (ValueError, IndexError):
            reason = reason or "Belirtilmedi"
    until = datetime.now(tz=pytz.utc) + timedelta(minutes=duration)
    try:
        await context.bot.restrict_chat_member(
            Config.GROUP_ID, target.id, _mute_perms(), until_date=until
        )
        await db.set_mute(target.id, until)
        notif = await update.effective_message.reply_text(
            f"🔇 {mention(target)} <b>{duration} dakika susturuldu!</b>\n📌 Sebep: {reason or 'Belirtilmedi'}",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_del(notif))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Mute başarısız: {e}")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    try:
        await context.bot.restrict_chat_member(Config.GROUP_ID, target.id, _unmute_perms())
        await db.set_mute(target.id, None)
        notif = await update.effective_message.reply_text(
            f"🔊 {mention(target)} <b>susturması kaldırıldı!</b>", parse_mode=ParseMode.HTML
        )
        asyncio.create_task(_del(notif))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Unmute başarısız: {e}")

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    if is_admin(target.id):
        await update.effective_message.reply_text("❌ Admin uyarılamaz!")
        return
    await db.upsert_user(target.id, target.username, target.first_name)
    result = await apply_warn(
        context, target.id, target.first_name,
        update.effective_user.id, reason or "Belirtilmedi"
    )
    notif = await update.effective_message.reply_text(result, parse_mode=ParseMode.HTML)
    asyncio.create_task(_del(notif, 60))

async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    await db.remove_warn(target.id)
    count = await db.get_warn_count(target.id)
    notif = await update.effective_message.reply_text(
        f"✅ {mention(target)} son uyarısı kaldırıldı. Kalan: <b>{count}/{settings.get('MAX_WARNS')}</b>",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_del(notif))

async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    await db.reset_warns(target.id)
    notif = await update.effective_message.reply_text(
        f"✅ {mention(target)} <b>tüm uyarıları sıfırlandı!</b>", parse_mode=ParseMode.HTML
    )
    asyncio.create_task(_del(notif))

async def cmd_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    warns = await db.get_warnings(target.id)
    if not warns:
        text = f"✅ {mention(target)} hiç uyarısı yok."
    else:
        lines = [f"⚠️ {mention(target)} uyarıları ({len(warns)}/{settings.get('MAX_WARNS')}):\n"]
        for w in warns:
            dt = w["created_at"].strftime("%d.%m.%Y %H:%M")
            lines.append(f"• {w['reason']} [{dt}]")
        text = "\n".join(lines)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text(
            "❌ Kullanıcı belirtin!\n<code>/userinfo @kullanıcı</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    row   = await db.get_user_by_id(target.id) if hasattr(db, "get_user_by_id") else None
    warns = await db.get_warnings(target.id)
    try:
        cm = await context.bot.get_chat_member(Config.GROUP_ID, target.id)
        status_map = {
            "member":"✅ Üye","administrator":"👑 Admin","creator":"👑 Kurucu",
            "restricted":"🔇 Kısıtlı","left":"🚪 Ayrılmış","kicked":"🚫 Banlı",
        }
        status = status_map.get(cm.status, cm.status)
    except TelegramError:
        status = "❓ Bilinmiyor"

    mc = (row.get("message_count",0) if row else 0)
    ic = (row.get("invite_count",0) if row else 0)
    wc = len(warns) if warns else 0
    un = f"@{target.username}" if target.username else "—"

    lines = [
        f"👤 <b>KULLANICI BİLGİSİ</b>", f"━━━━━━━━━━━━━━━━━",
        f"📛 Ad: <b>{target.full_name or target.first_name}</b>",
        f"🔗 Kullanıcı: <b>{un}</b>",
        f"🆔 ID: <code>{target.id}</code>",
        f"📊 Durum: <b>{status}</b>", f"",
        f"<b>📈 İstatistikler</b>",
        f"├ 💬 Mesaj: <b>{mc}</b>",
        f"├ 🔗 Davet: <b>{ic}</b>",
        f"└ ⚠️ Uyarı: <b>{wc}/{settings.get('MAX_WARNS')}</b>",
    ]
    if warns:
        lines += ["", "<b>⚠️ Son Uyarılar:</b>"]
        for w in warns[-5:]:
            dt = w["created_at"].strftime("%d.%m.%Y %H:%M")
            lines.append(f"  • {w['reason']} <i>[{dt}]</i>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def cmd_banlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:    rows = await db.get_banned_users()
    except: rows = []
    if not rows:
        await update.effective_message.reply_text("🚫 Banlı kullanıcı kaydı yok.")
        return
    lines = [f"🚫 <b>BANLI KULLANICILAR</b> ({len(rows)} kişi)\n━━━━━━━━━━━━━━━━━\n"]
    for r in rows[:30]:
        name  = r.get("first_name") or "Kullanıcı"
        uname = f" (@{r['username']})" if r.get("username") else ""
        lines.append(f"• {mid(r['user_id'], name)}{uname}")
    if len(rows) > 30:
        lines.append(f"\n<i>+{len(rows)-30} kişi daha</i>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def cmd_duyuru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Kullanım: <code>/duyuru [metin]</code>", parse_mode=ParseMode.HTML
        )
        return
    admin   = update.effective_user
    mesaj   = " ".join(context.args)
    now_str = datetime.now(TR).strftime("%d.%m.%Y %H:%M")
    asign   = f"@{admin.username}" if admin.username else admin.first_name
    try:
        await context.bot.send_message(
            Config.GROUP_ID,
            f"📢 <b>DUYURU</b>\n━━━━━━━━━━━━━━━━━\n\n"
            f"{mesaj}\n\n━━━━━━━━━━━━━━━━━\n"
            f"👤 <i>{asign}</i> | 📅 {now_str}\n\n"
            f"📢 {Config.CHANNEL_USERNAME} | 👥 {Config.MAIN_GROUP_USERNAME}",
            parse_mode=ParseMode.HTML,
        )
        await update.effective_message.reply_text("✅ Duyuru gruba gönderildi!")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Gönderilemedi: {e}")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Kullanım: <code>/broadcast [metin]</code>", parse_mode=ParseMode.HTML
        )
        return
    try:
        await context.bot.send_message(Config.GROUP_ID, " ".join(context.args))
        await update.effective_message.reply_text("✅ Mesaj gruba gönderildi!")
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Başarısız: {e}")

async def cmd_temizle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    n = 10
    if context.args:
        try:
            n = max(1, min(100, int(context.args[0])))
        except ValueError:
            await update.effective_message.reply_text(
                "❌ Kullanım: <code>/temizle [1-100]</code>", parse_mode=ParseMode.HTML
            )
            return
    msg     = update.effective_message
    chat_id = msg.chat.id
    msg_id  = msg.message_id
    info    = await msg.reply_text(
        f"🗑️ Son <b>{n}</b> mesaj siliniyor...", parse_mode=ParseMode.HTML
    )
    deleted = 0
    for m_ in list(range(msg_id - n, msg_id + 1)) + [info.message_id]:
        if m_ <= 0: continue
        try:
            await context.bot.delete_message(chat_id, m_)
            deleted += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            pass
    result = await context.bot.send_message(
        chat_id, f"✅ <b>{deleted}</b> mesaj silindi.", parse_mode=ParseMode.HTML
    )
    asyncio.create_task(_del(result, 10))

async def cmd_purgefrom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_text("❌ Silmeye başlanacak mesajı reply yapın!")
        return
    start_id = msg.reply_to_message.message_id
    end_id   = msg.message_id
    chat_id  = msg.chat.id
    if end_id - start_id > 200:
        await msg.reply_text("❌ Tek seferde en fazla 200 mesaj silinebilir!")
        return
    info = await msg.reply_text(
        f"🗑️ <b>{end_id - start_id + 1}</b> mesaj siliniyor...", parse_mode=ParseMode.HTML
    )
    deleted = 0
    for m_ in range(start_id, end_id + 1):
        try:
            await context.bot.delete_message(chat_id, m_)
            deleted += 1
            await asyncio.sleep(0.05)
        except TelegramError:
            pass
    try:    await info.delete()
    except: pass
    result = await context.bot.send_message(
        chat_id, f"✅ <b>{deleted}</b> mesaj silindi.", parse_mode=ParseMode.HTML
    )
    asyncio.create_task(_del(result, 10))

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.effective_message.reply_text(
        await _stats_txt(context), parse_mode=ParseMode.HTML
    )

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    rows = await db.get_invite_leaderboard(10)
    await update.effective_message.reply_text(_leaderboard(rows), parse_mode=ParseMode.HTML)

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    mw = settings.get("MAX_WARNS")
    sm = f"\n🐢 Yavaş Mod: <b>{settings.get('SLOW_MODE_MIN')} dk</b>" if settings.get("SLOW_MODE_ENABLED") else ""
    await update.effective_message.reply_text(
        f"📋 <b>GRUP KURALLARI</b>\n━━━━━━━━━━━━━━━━━\n\n"
        f"1️⃣ Airdrop referans ve link paylaşımı serbesttir\n"
        f"2️⃣ Başkasının referans linkini değiştirmeyin\n"
        f"3️⃣ Saygılı ve yardımsever olun\n"
        f"4️⃣ Spam / flood → susturma\n"
        f"5️⃣ Küfür / hakaret → anında ban\n"
        f"6️⃣ Konu dışı reklam → ban{sm}\n\n"
        f"⚠️ <b>{mw} uyarı = kalıcı ban!</b>",
        parse_mode=ParseMode.HTML,
    )

async def cmd_davetlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    user = update.effective_user
    try:
        link = await context.bot.create_chat_invite_link(
            Config.GROUP_ID, name=f"Admin Davet — {user.first_name}"
        )
        await db.store_invite_link(link.invite_link, user.id)
        await update.effective_message.reply_text(
            f"🔗 <b>Davet Linkin Oluşturuldu:</b>\n\n"
            f"<code>{link.invite_link}</code>\n\n"
            f"📊 Bu link üzerinden katılanlar liderlik tablosunda sana sayılır!",
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Davet linki oluşturulamadı: {e}")

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    t0  = time.time()
    msg = await update.effective_message.reply_text("🏓 Pong...")
    ms  = int((time.time() - t0) * 1000)
    await msg.edit_text(
        f"🏓 <b>Pong!</b> <code>{ms}ms</code>\n⏱ Uptime: <b>{_uptime()}</b>",
        parse_mode=ParseMode.HTML,
    )

async def cmd_rapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    notif = await update.effective_message.reply_text("⏳ Rapor hazırlanıyor...")
    try:
        await send_daily_report(context.application)
        await notif.edit_text("✅ Günlük rapor gruba gönderildi!")
    except Exception as e:
        await notif.edit_text(f"❌ Rapor gönderilemedi: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  GÜNLÜK RAPOR
# ═══════════════════════════════════════════════════════════════════════════════

async def send_daily_report(app: Application):
    if not settings.get("REPORT_ENABLED"):
        return
    s = await db.get_group_stats()
    try:    cnt = await app.bot.get_chat_member_count(Config.GROUP_ID)
    except: cnt = s["total_users"]
    td      = s.get("today") or {}
    h, m_   = settings.get("REPORT_HOUR"), settings.get("REPORT_MINUTE")
    now_str = datetime.now(TR).strftime("%d.%m.%Y")
    medals  = ["🥇","🥈","🥉"]

    lines = [
        f"📊 <b>GÜNLÜK İSTATİSTİK RAPORU</b>",
        f"📅 {now_str} — {h:02d}:{m_:02d}\n",
        f"👥 Toplam Üye: <b>{cnt}</b>",
        f"📈 Bugün Katılan: <b>+{td.get('new_members',0)}</b>",
        f"📉 Bugün Ayrılan: <b>-{td.get('left_members',0)}</b>",
        f"💬 Bugün Mesaj: <b>{td.get('total_messages',0)}</b>",
        f"⚠️ Toplam Uyarı: <b>{s['total_warns']}</b>",
    ]

    if settings.get("REPORT_LEADERBOARD"):
        top = await db.get_invite_leaderboard(3)
        if top:
            lines.append("\n🏆 <b>Davet Liderleri:</b>")
            for i, r in enumerate(top):
                u = f"@{r['username']}" if r["username"] else (r["first_name"] or "?")
                lines.append(f"{medals[i]} {u} — {r['invite_count']} davet")

    if settings.get("REPORT_ACTIVE"):
        top2 = await db.get_top_active_today(3)
        if top2:
            lines.append("\n💬 <b>Bugünün En Aktifi:</b>")
            for i, r in enumerate(top2, 1):
                u = f"@{r['username']}" if r.get("username") else (r["first_name"] or "?")
                lines.append(f"{i}. {u} — {r['message_count']} mesaj")

    lines += [
        f"\n━━━━━━━━━━━━━━━━━",
        f"📢 {Config.CHANNEL_USERNAME} | 👥 {Config.MAIN_GROUP_USERNAME}",
    ]
    try:
        await app.bot.send_message(
            Config.GROUP_ID, "\n".join(lines), parse_mode=ParseMode.HTML
        )
        logger.info("Günlük rapor gönderildi.")
    except TelegramError as e:
        logger.error(f"Günlük rapor hatası: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  KOMUT MENÜSÜ KAYIT (BotFather'a otomatik bildirir)
# ═══════════════════════════════════════════════════════════════════════════════

async def register_commands(app: Application):
    """Telegram'ın '/' komut menüsüne tüm komutları kaydeder."""

    # ── Private DM — Admin komut listesi ────────────────────────────────
    admin_cmds = [
        BotCommand("start",       "🎛️ Admin panelini aç"),
        BotCommand("panel",       "🎛️ Admin panelini aç"),
        BotCommand("ayarlar",     "⚙️ Bot ayarlarını düzenle"),
        BotCommand("stats",       "📊 Grup istatistikleri"),
        BotCommand("top",         "🏆 Davet liderlik tablosu"),
        BotCommand("userinfo",    "👤 Kullanıcı bilgisi sorgula"),
        BotCommand("banlist",     "🚫 Banlı kullanıcı listesi"),
        BotCommand("duyuru",      "📢 Gruba biçimlendirilmiş duyuru"),
        BotCommand("broadcast",   "📡 Gruba ham mesaj gönder"),
        BotCommand("warn",        "⚠️ Kullanıcıya uyarı ver"),
        BotCommand("unwarn",      "↩️ Son uyarıyı sil"),
        BotCommand("resetwarns",  "🔄 Tüm uyarıları sıfırla"),
        BotCommand("warnings",    "📋 Uyarı geçmişini göster"),
        BotCommand("ban",         "🔨 Kullanıcıyı gruptan banla"),
        BotCommand("unban",       "✅ Kullanıcının banını kaldır"),
        BotCommand("kick",        "👢 Kullanıcıyı gruptan at"),
        BotCommand("mute",        "🔇 Kullanıcıyı sustur"),
        BotCommand("unmute",      "🔊 Susturmayı kaldır"),
        BotCommand("temizle",     "🗑️ Son N mesajı sil"),
        BotCommand("purgefrom",   "🗑️ Reply'den itibaren toplu sil"),
        BotCommand("davetlink",   "🔗 Takipli davet linki oluştur"),
        BotCommand("rapor",       "📊 Günlük raporu şimdi gönder"),
        BotCommand("rules",       "📋 Grup kuralları"),
        BotCommand("ping",        "🏓 Bot gecikme testi"),
    ]

    # ── Grupta admin komutları ──────────────────────────────────────────
    group_admin_cmds = [
        BotCommand("ban",        "🔨 Banla"),
        BotCommand("unban",      "✅ Ban kaldır"),
        BotCommand("kick",       "👢 At"),
        BotCommand("mute",       "🔇 Sustur"),
        BotCommand("unmute",     "🔊 Susturmayı kaldır"),
        BotCommand("warn",       "⚠️ Uyarı ver"),
        BotCommand("unwarn",     "↩️ Son uyarıyı sil"),
        BotCommand("resetwarns", "🔄 Uyarıları sıfırla"),
        BotCommand("warnings",   "📋 Uyarı geçmişi"),
        BotCommand("userinfo",   "👤 Kullanıcı sorgula"),
        BotCommand("duyuru",     "📢 Duyuru gönder"),
        BotCommand("temizle",    "🗑️ Mesajları sil"),
        BotCommand("purgefrom",  "🗑️ Reply'den itibaren sil"),
        BotCommand("stats",      "📊 İstatistikler"),
        BotCommand("panel",      "🎛️ Admin paneli"),
        BotCommand("ayarlar",    "⚙️ Ayarlar"),
    ]

    try:
        # DM'de tüm admin komutları görünsün
        await app.bot.set_my_commands(
            admin_cmds,
            scope=BotCommandScopeAllPrivateChats(),
        )
        # Grupta sadece admin komutları (grup yöneticilerine)
        await app.bot.set_my_commands(
            group_admin_cmds,
            scope=BotCommandScopeChatAdministrators(chat_id=Config.GROUP_ID),
        )
        # Grupta sıradan üyelere komut gösterme (boş liste)
        await app.bot.set_my_commands(
            [],
            scope=BotCommandScopeChat(chat_id=Config.GROUP_ID),
        )
        # DM'de menü butonu = komut listesi
        await app.bot.set_chat_menu_button(
            menu_button=MenuButtonCommands()
        )
        logger.info("Komut menüleri Telegram'a kaydedildi.")
    except TelegramError as e:
        logger.warning(f"Komut menüsü kaydedilemedi: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
#  UYGULAMA BAŞLATMA
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(app: Application):
    global _scheduler
    await db.connect()
    await register_commands(app)

    h, m_ = settings.get("REPORT_HOUR"), settings.get("REPORT_MINUTE")
    _scheduler = AsyncIOScheduler(timezone=TR)
    _scheduler.add_job(
        send_daily_report,
        trigger="cron",
        hour=h, minute=m_,
        args=[app],
        id="daily_report",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Scheduler başlatıldı — rapor: {h:02d}:{m_:02d} TR")


def main():
    app = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        ChatMemberHandler(handle_member_update, ChatMemberHandler.CHAT_MEMBER)
    )

    for cmd, fn in [
        ("start",       cmd_start),
        ("panel",       cmd_panel),
        ("ayarlar",     cmd_ayarlar),
        ("ban",         cmd_ban),
        ("unban",       cmd_unban),
        ("kick",        cmd_kick),
        ("mute",        cmd_mute),
        ("unmute",      cmd_unmute),
        ("warn",        cmd_warn),
        ("unwarn",      cmd_unwarn),
        ("resetwarns",  cmd_resetwarns),
        ("warnings",    cmd_warnings),
        ("userinfo",    cmd_userinfo),
        ("banlist",     cmd_banlist),
        ("stats",       cmd_stats),
        ("top",         cmd_top),
        ("rules",       cmd_rules),
        ("davetlink",   cmd_davetlink),
        ("duyuru",      cmd_duyuru),
        ("broadcast",   cmd_broadcast),
        ("temizle",     cmd_temizle),
        ("purgefrom",   cmd_purgefrom),
        ("rapor",       cmd_rapor),
        ("ping",        cmd_ping),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("🚀 Referans Bot v3.0 başlatıldı!")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
