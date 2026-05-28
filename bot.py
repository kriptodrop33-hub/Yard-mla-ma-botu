#!/usr/bin/env python3
"""
Airdrop Referans Yardımlaşma Grubu — Telegram Yönetim Botu
Tüm komutlar yalnızca ADMIN_IDS listesindeki kullanıcılara açıktır.
"""

import asyncio
import logging
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
#  GLOBALS
# ═══════════════════════════════════════════════════════════════════════════════
db   = Database()
groq = GroqFilter()
TR   = pytz.timezone(Config.TIMEZONE)

# Flood tracker: {user_id: [timestamp, ...]}
flood_tracker: dict[int, list[float]] = defaultdict(list)

# ═══════════════════════════════════════════════════════════════════════════════
#  YARDIMCILAR
# ═══════════════════════════════════════════════════════════════════════════════

def is_admin(user_id: int) -> bool:
    return user_id in Config.ADMIN_IDS

def mention(user) -> str:
    return f'<a href="tg://user?id={user.id}">{user.first_name}</a>'

def mention_id(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{name}</a>'

def _mute_perms() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False, can_send_audios=False, can_send_documents=False,
        can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
        can_send_voice_notes=False, can_send_polls=False,
        can_send_other_messages=False, can_add_web_page_previews=False,
    )

def _unmute_perms() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True, can_send_audios=True, can_send_documents=True,
        can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
        can_send_voice_notes=True, can_send_polls=True,
        can_send_other_messages=True, can_add_web_page_previews=True,
    )

async def _delete_later(msg, delay: int = 30):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply veya argümandan hedef kullanıcı + sebep döner."""
    msg = update.effective_message

    if msg.reply_to_message:
        user   = msg.reply_to_message.from_user
        reason = " ".join(context.args) if context.args else None
        return user, reason

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

# ═══════════════════════════════════════════════════════════════════════════════
#  UYARI ZİNCİRİ (ortak logic: warn → mute → ban)
# ═══════════════════════════════════════════════════════════════════════════════

async def apply_warn(context: ContextTypes.DEFAULT_TYPE,
                     user_id: int, first_name: str,
                     admin_id: int, reason: str) -> str:
    warn_count = await db.add_warn(user_id, admin_id, reason)
    m          = mention_id(user_id, first_name)

    if warn_count >= Config.MAX_WARNS:
        try:
            await context.bot.ban_chat_member(Config.GROUP_ID, user_id)
            await db.set_banned(user_id, True)
        except TelegramError as e:
            logger.error(f"Otomatik ban hatası: {e}")
        return (
            f"🔨 {m} <b>{warn_count}. uyarısına ulaştı → BANLANDI!</b>\n"
            f"📌 Sebep: {reason}"
        )

    if warn_count == 2:
        until = datetime.now(tz=pytz.utc) + timedelta(seconds=Config.MUTE_DURATION_ON_2ND_WARN)
        try:
            await context.bot.restrict_chat_member(
                Config.GROUP_ID, user_id, _mute_perms(), until_date=until
            )
            await db.set_mute(user_id, until)
        except TelegramError as e:
            logger.error(f"Otomatik mute hatası: {e}")
        return (
            f"⚠️ {m} <b>uyarıldı! ({warn_count}/{Config.MAX_WARNS})</b>\n"
            f"📌 Sebep: {reason}\n"
            f"🔇 24 saat susturuldu!\n"
            f"❗ Bir sonraki uyarıda banlanacak!"
        )

    return (
        f"⚠️ {m} <b>uyarıldı! ({warn_count}/{Config.MAX_WARNS})</b>\n"
        f"📌 Sebep: {reason}\n"
        f"❗ {Config.MAX_WARNS - warn_count} uyarı hakkı kaldı!"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMİN PANELİ (inline keyboard)
# ═══════════════════════════════════════════════════════════════════════════════

def _panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 İstatistikler",  callback_data="p_stats"),
            InlineKeyboardButton("🏆 Liderlik",        callback_data="p_top"),
        ],
        [
            InlineKeyboardButton("⚠️ Son Uyarılar",   callback_data="p_warns"),
            InlineKeyboardButton("🔇 Susturulanlar",   callback_data="p_muted"),
        ],
    ])

def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Geri", callback_data="p_back")]])

def _fmt_leaderboard(rows) -> str:
    if not rows:
        return "📊 Henüz davet verisi yok."
    medals = ["🥇", "🥈", "🥉"] + ["🔸"] * 7
    lines  = ["🏆 <b>DAVET LİDERLİK TABLOSU</b>\n━━━━━━━━━━━━━━━━━\n"]
    for i, r in enumerate(rows):
        name  = r["first_name"] or "Kullanıcı"
        uname = f"@{r['username']}" if r["username"] else name
        lines.append(f"{medals[i]} {uname} — <b>{r['invite_count']} davet</b>")
    return "\n".join(lines)

async def _stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    s = await db.get_group_stats()
    try:
        count = await context.bot.get_chat_member_count(Config.GROUP_ID)
    except Exception:
        count = s["total_users"]
    td   = s.get("today") or {}
    now  = datetime.now(TR).strftime("%d.%m.%Y %H:%M")
    return (
        f"📊 <b>GRUP İSTATİSTİKLERİ</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📅 {now}\n\n"
        f"👥 Toplam Üye: <b>{count}</b>\n"
        f"📈 Bugün Katılan: <b>+{td.get('new_members', 0)}</b>\n"
        f"📉 Bugün Ayrılan: <b>-{td.get('left_members', 0)}</b>\n"
        f"💬 Toplam Mesaj: <b>{s['total_messages']}</b>\n"
        f"💬 Bugün Mesaj: <b>{td.get('total_messages', 0)}</b>\n"
        f"🔗 Toplam Davet: <b>{s['total_invites']}</b>\n"
        f"⚠️ Toplam Uyarı: <b>{s['total_warns']}</b>"
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  YENİ ÜYE KARŞILAMA
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if result.chat.id != Config.GROUP_ID:
        return

    old = result.old_chat_member.status
    new = result.new_chat_member.status

    # ── Yeni üye katıldı ──────────────────────────────────────────────────
    if (old in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
            and new in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)):

        user = result.new_chat_member.user
        if user.is_bot:
            return

        await db.upsert_user(user.id, user.username, user.first_name)
        await db.update_daily_new_member()

        # Davet takibi
        if result.invite_link:
            owner = await db.get_invite_link_owner(result.invite_link.invite_link)
            if owner and owner != user.id:
                await db.add_invite(owner, user.id)

        try:
            count = await context.bot.get_chat_member_count(Config.GROUP_ID)
        except Exception:
            count = "?"

        text = (
            f"🎉 <b>Hoş Geldin, {mention(user)}!</b>\n\n"
            f"🤝 <b>Airdrop Referans Yardımlaşma Grubu</b>'na katıldın!\n"
            f"👥 Artık <b>{count}</b>. üyesiniz!\n\n"
            f"📌 <b>Grup Kuralları:</b>\n"
            f"├ ✅ Sadece airdrop referans paylaşımı yapın\n"
            f"├ ✅ Saygılı ve yardımsever olun\n"
            f"├ ❌ Spam / flood kesinlikle yasaktır\n"
            f"├ ❌ Küfür ve hakaret → anında ban\n"
            f"└ ❌ Reklam / tanıtım → ban\n\n"
            f"⚠️ <b>3 uyarı = kalıcı ban!</b>\n"
            f"━━━━━━━━━━━━━━━━━"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 Duyuru Kanalı", url=Config.CHANNEL_LINK),
                InlineKeyboardButton("👥 Ana Grup",       url=Config.MAIN_GROUP_LINK),
            ],
            [
                InlineKeyboardButton("📋 Grup Kuralları",     callback_data="cb_rules"),
                InlineKeyboardButton("🏆 Liderlik Tablosu",   callback_data="cb_top"),
            ],
        ])
        try:
            await context.bot.send_message(
                Config.GROUP_ID, text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except TelegramError as e:
            logger.error(f"Karşılama mesajı hatası: {e}")

    # ── Üye ayrıldı / banlandı ────────────────────────────────────────────
    elif (old in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)
              and new in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)):
        await db.update_daily_left_member()

# ═══════════════════════════════════════════════════════════════════════════════
#  MESAJ MODERASYONU (flood + küfür)
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    user = update.effective_user
    if not msg or not user or user.is_bot:
        return
    if msg.chat.id != Config.GROUP_ID:
        return

    # Adminler sadece sayılır, moderasyona tabi değil
    if is_admin(user.id):
        await db.increment_message_count(user.id)
        return

    await db.upsert_user(user.id, user.username, user.first_name)

    # ── Flood kontrolü ────────────────────────────────────────────────────
    now = time.time()
    ts  = [t for t in flood_tracker[user.id] if now - t < Config.FLOOD_TIME_WINDOW]
    ts.append(now)
    flood_tracker[user.id] = ts

    if len(ts) > Config.FLOOD_MAX_MESSAGES:
        flood_tracker[user.id] = []
        until = datetime.now(tz=pytz.utc) + timedelta(seconds=Config.MUTE_DURATION_ON_FLOOD)
        try:
            await context.bot.restrict_chat_member(
                Config.GROUP_ID, user.id, _mute_perms(), until_date=until
            )
            await db.set_mute(user.id, until)
            notif = await msg.reply_text(
                f"🚫 {mention(user)} <b>flood yaptığı için 1 saat susturuldu!</b>",
                parse_mode=ParseMode.HTML,
            )
            asyncio.create_task(_delete_later(notif, 15))
        except TelegramError as e:
            logger.error(f"Flood mute hatası: {e}")
        return

    # ── Küfür filtresi (Groq AI) ──────────────────────────────────────────
    text = msg.text or msg.caption or ""
    if text and len(text) >= 3:
        try:
            if await groq.is_profanity(text):
                try:
                    await msg.delete()
                except Exception:
                    pass
                result_text = await apply_warn(
                    context, user.id, user.first_name, 0, "Küfür / hakaret"
                )
                notif = await context.bot.send_message(
                    Config.GROUP_ID, result_text, parse_mode=ParseMode.HTML
                )
                asyncio.create_task(_delete_later(notif, 40))
                return
        except Exception as e:
            logger.error(f"Profanity check hatası: {e}")

    await db.increment_message_count(user.id)

# ═══════════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLER (inline butonlar)
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()

    # ── Herkese açık butonlar (karşılama mesajından) ──────────────────────
    if data == "cb_rules":
        text = (
            "📋 <b>GRUP KURALLARI</b>\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Sadece <b>airdrop referans linkleri</b> paylaşın\n"
            "2️⃣ Başkasına ait referans linkini <b>değiştirmeyin</b>\n"
            "3️⃣ Saygılı ve yardımsever olun\n"
            "4️⃣ Spam / flood → <b>susturma</b>\n"
            "5️⃣ Küfür / hakaret → <b>anında ban</b>\n"
            "6️⃣ Reklam / tanıtım → <b>ban</b>\n"
            "7️⃣ Konu dışı içerik → <b>uyarı</b>\n\n"
            "⚠️ <b>3 uyarı = kalıcı ban!</b>\n\n"
            f"📢 {Config.CHANNEL_USERNAME} | 👥 {Config.MAIN_GROUP_USERNAME}"
        )
        await q.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    if data == "cb_top":
        rows = await db.get_invite_leaderboard(10)
        await q.message.reply_text(_fmt_leaderboard(rows), parse_mode=ParseMode.HTML)
        return

    # ── Admin paneli butonları ────────────────────────────────────────────
    if not is_admin(uid):
        await q.answer("❌ Yalnızca adminler kullanabilir!", show_alert=True)
        return

    if data == "p_back":
        try:
            await q.message.edit_text(
                "🎛️ <b>ADMİN PANELİ</b>\n━━━━━━━━━━━━━━━━━\nAşağıdan işlem seçin:",
                parse_mode=ParseMode.HTML,
                reply_markup=_panel_keyboard(),
            )
        except Exception:
            pass
        return

    if data == "p_stats":
        text = await _stats_text(context)
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_back_keyboard())
        except Exception:
            pass
        return

    if data == "p_top":
        rows = await db.get_invite_leaderboard(10)
        try:
            await q.message.edit_text(
                _fmt_leaderboard(rows), parse_mode=ParseMode.HTML, reply_markup=_back_keyboard()
            )
        except Exception:
            pass
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
                lines.append(f"• {mention_id(r['user_id'], name)} — {r['reason']} [{dt}]")
            text = "\n".join(lines)
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_back_keyboard())
        except Exception:
            pass
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
                lines.append(f"• {mention_id(r['user_id'], name)} → {until}")
            text = "\n".join(lines)
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=_back_keyboard())
        except Exception:
            pass
        return

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMİN KOMUTLARI  (tamamı admin-only — sessizce reddedilir)
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    uid  = update.effective_user.id

    if chat.type != "private":
        return  # Grupta /start yok

    if not is_admin(uid):
        await update.effective_message.reply_text(
            "👋 Merhaba!\n\n"
            "Ben <b>Airdrop Referans Yardımlaşma Grubu</b> botuyum.\n"
            "Gruba katılmak için aşağıdaki butona tıklayabilirsin!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Gruba Katıl",      url=Config.MAIN_GROUP_LINK)],
                [InlineKeyboardButton("📢 Kanalı Takip Et",  url=Config.CHANNEL_LINK)],
            ]),
        )
        return

    # Admin: panel aç
    await update.effective_message.reply_text(
        "🎛️ <b>ADMİN PANELİ</b>\n━━━━━━━━━━━━━━━━━\nAşağıdan işlem seçin:",
        parse_mode=ParseMode.HTML,
        reply_markup=_panel_keyboard(),
    )

async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_message.reply_text(
        "🎛️ <b>ADMİN PANELİ</b>\n━━━━━━━━━━━━━━━━━\nAşağıdan işlem seçin:",
        parse_mode=ParseMode.HTML,
        reply_markup=_panel_keyboard(),
    )

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin! (Reply veya @kullanıcı)")
        return
    reason = reason or "Belirtilmedi"
    try:
        await context.bot.ban_chat_member(Config.GROUP_ID, target.id)
        await db.set_banned(target.id, True)
        notif = await update.effective_message.reply_text(
            f"🔨 {mention(target)} <b>gruptan banlandı!</b>\n📌 Sebep: {reason}",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_delete_later(notif, 30))
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
            f"✅ {mention(target)} <b>banı kaldırıldı!</b>",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_delete_later(notif, 30))
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
        asyncio.create_task(_delete_later(notif, 30))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Kick başarısız: {e}")

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return

    # Süre ayırma: /mute @user 60 sebep   → 60 dakika
    duration = 60
    extra_args = context.args if not update.effective_message.reply_to_message else context.args
    if extra_args:
        try:
            duration = int(extra_args[0] if not update.effective_message.reply_to_message else extra_args[0])
            reason   = " ".join(extra_args[1:]) or reason or "Belirtilmedi"
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
        asyncio.create_task(_delete_later(notif, 30))
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
            f"🔊 {mention(target)} <b>susturması kaldırıldı!</b>",
            parse_mode=ParseMode.HTML,
        )
        asyncio.create_task(_delete_later(notif, 30))
    except TelegramError as e:
        await update.effective_message.reply_text(f"❌ Unmute başarısız: {e}")

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, reason = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    if is_admin(target.id):
        await update.effective_message.reply_text("❌ Admin uyarılamazı!")
        return
    await db.upsert_user(target.id, target.username, target.first_name)
    result_text = await apply_warn(
        context, target.id, target.first_name,
        update.effective_user.id, reason or "Belirtilmedi"
    )
    notif = await update.effective_message.reply_text(result_text, parse_mode=ParseMode.HTML)
    asyncio.create_task(_delete_later(notif, 60))

async def cmd_unwarn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    await db.remove_warn(target.id)
    count = await db.get_warn_count(target.id)
    notif = await update.effective_message.reply_text(
        f"✅ {mention(target)} son uyarısı kaldırıldı. Kalan: <b>{count}/{Config.MAX_WARNS}</b>",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_delete_later(notif, 30))

async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    target, _ = await get_target(update, context)
    if not target:
        await update.effective_message.reply_text("❌ Kullanıcı belirtin!")
        return
    await db.reset_warns(target.id)
    notif = await update.effective_message.reply_text(
        f"✅ {mention(target)} <b>tüm uyarıları sıfırlandı!</b>",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_delete_later(notif, 30))

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
        lines = [f"⚠️ {mention(target)} uyarıları ({len(warns)}/{Config.MAX_WARNS}):\n"]
        for w in warns:
            dt = w["created_at"].strftime("%d.%m.%Y %H:%M")
            lines.append(f"• {w['reason']} [{dt}]")
        text = "\n".join(lines)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    text = await _stats_text(context)
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    rows = await db.get_invite_leaderboard(10)
    await update.effective_message.reply_text(_fmt_leaderboard(rows), parse_mode=ParseMode.HTML)

async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    text = (
        "📋 <b>GRUP KURALLARI</b>\n━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Sadece airdrop referans linkleri paylaşın\n"
        "2️⃣ Başkasına ait referans linkini değiştirmeyin\n"
        "3️⃣ Saygılı ve yardımsever olun\n"
        "4️⃣ Spam / flood → susturma\n"
        "5️⃣ Küfür / hakaret → anında ban\n"
        "6️⃣ Reklam / tanıtım → ban\n"
        "7️⃣ Konu dışı içerik → uyarı\n\n"
        "⚠️ <b>3 uyarı = kalıcı ban!</b>"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_davetlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminin gruba özel davet linki oluşturmasını sağlar."""
    if not is_admin(update.effective_user.id): return
    user = update.effective_user
    try:
        link_obj = await context.bot.create_chat_invite_link(
            Config.GROUP_ID,
            name=f"Admin Davet — {user.first_name}",
        )
        await db.store_invite_link(link_obj.invite_link, user.id)
        await update.effective_message.reply_text(
            f"🔗 <b>Davet Linkin Oluşturuldu:</b>\n\n"
            f"<code>{link_obj.invite_link}</code>\n\n"
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
    await msg.edit_text(f"🏓 <b>Pong!</b> <code>{ms}ms</code>", parse_mode=ParseMode.HTML)

# ═══════════════════════════════════════════════════════════════════════════════
#  GÜNLÜK İSTATİSTİK RAPORU (APScheduler)
# ═══════════════════════════════════════════════════════════════════════════════

async def send_daily_report(app: Application):
    s = await db.get_group_stats()
    try:
        count = await app.bot.get_chat_member_count(Config.GROUP_ID)
    except Exception:
        count = s["total_users"]

    td         = s.get("today") or {}
    top_invite = await db.get_invite_leaderboard(3)
    top_active = await db.get_top_active_today(3)
    now_str    = datetime.now(TR).strftime("%d.%m.%Y")
    medals     = ["🥇", "🥈", "🥉"]

    lines = [
        f"📊 <b>GÜNLÜK İSTATİSTİK RAPORU</b>",
        f"📅 {now_str} — 20:00\n",
        f"👥 Toplam Üye: <b>{count}</b>",
        f"📈 Bugün Katılan: <b>+{td.get('new_members', 0)}</b>",
        f"📉 Bugün Ayrılan: <b>-{td.get('left_members', 0)}</b>",
        f"💬 Bugün Mesaj: <b>{td.get('total_messages', 0)}</b>",
        f"⚠️ Toplam Uyarı: <b>{s['total_warns']}</b>",
    ]

    if top_invite:
        lines.append("\n🏆 <b>Davet Liderleri:</b>")
        for i, r in enumerate(top_invite):
            uname = f"@{r['username']}" if r["username"] else (r["first_name"] or "?")
            lines.append(f"{medals[i]} {uname} — {r['invite_count']} davet")

    if top_active:
        lines.append("\n💬 <b>Bugünün En Aktifi:</b>")
        for i, r in enumerate(top_active, 1):
            uname = f"@{r['username']}" if r.get("username") else (r["first_name"] or "?")
            lines.append(f"{i}. {uname} — {r['message_count']} mesaj")

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
#  UYGULAMA BAŞLATMA
# ═══════════════════════════════════════════════════════════════════════════════

async def post_init(app: Application):
    await db.connect()

    scheduler = AsyncIOScheduler(timezone=TR)
    scheduler.add_job(
        send_daily_report,
        trigger="cron",
        hour=Config.DAILY_REPORT_HOUR,
        minute=Config.DAILY_REPORT_MINUTE,
        args=[app],
    )
    scheduler.start()
    logger.info(
        f"Scheduler başlatıldı — günlük rapor: "
        f"{Config.DAILY_REPORT_HOUR:02d}:{Config.DAILY_REPORT_MINUTE:02d} TR saati"
    )


def main():
    app = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ChatMember handler (üye giriş/çıkış)
    app.add_handler(
        ChatMemberHandler(handle_member_update, ChatMemberHandler.CHAT_MEMBER)
    )

    # Komutlar
    commands = [
        ("start",       cmd_start),
        ("panel",       cmd_panel),
        ("ban",         cmd_ban),
        ("unban",       cmd_unban),
        ("kick",        cmd_kick),
        ("mute",        cmd_mute),
        ("unmute",      cmd_unmute),
        ("warn",        cmd_warn),
        ("unwarn",      cmd_unwarn),
        ("resetwarns",  cmd_resetwarns),
        ("warnings",    cmd_warnings),
        ("stats",       cmd_stats),
        ("top",         cmd_top),
        ("rules",       cmd_rules),
        ("davetlink",   cmd_davetlink),
        ("ping",        cmd_ping),
    ]
    for cmd, func in commands:
        app.add_handler(CommandHandler(cmd, func))

    # Inline buton callback'leri
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Mesaj moderasyonu (tüm mesajlar)
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)
    )

    logger.info("🚀 Referans Bot başlatıldı!")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
