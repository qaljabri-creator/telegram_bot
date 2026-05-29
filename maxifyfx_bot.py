# -*- coding: utf-8 -*-
"""
========================================================================
                    MaxiFyFX Telegram Moderation Bot  (v3)
========================================================================
العقوبات:
  • الروابط الممنوعة / تكرار الرسائل / الصور العارية → حذف + تحذير + (الطرد عند المخالفة الثالثة)
  • أسماء الشركات المنافسة والمروّجين       → حذف + تحذير فقط (بدون طرد)

الميزات:
  1) حظر الروابط ما عدا روابط MaxiFyFX (مع تعرّف تلقائي على يوتيوب MaxiFyFX)
  2) كشف معرفات القنوات/المجموعات تلقائياً وحظرها (والسماح بمعرفات الأشخاص)
  3) منع تكرار نفس الرسالة
  4) حظر الصور العارية (NudeNet)
  5) حظر أسماء المنافسين/المروّجين بكل أشكال كتابتها (تحذير فقط)
  6) قائمة خدمات تظهر للمستخدم عند كتابة /  + أزرار سريعة

التشغيل:
  py -3.13 -m pip install "python-telegram-bot>=20" nudenet
  py -3.13 maxifyfx_bot.py
========================================================================
"""

import os
import re
import json
import time
import logging
import tempfile
import asyncio
import urllib.parse
from collections import defaultdict, deque

import httpx
from telegram import (
    Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters
)

# ════════════════════════════════════════════════════════════════════
#                     ⚙️  الإعدادات (عدّل من هنا فقط)
# ════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8756447360:AAGc-vkpwLWuV2Vr1b-Ei7aeUaI6vekz9d8"

# ── 1) الروابط المسموحة (MaxiFyFX الرسمية) ────────────────────────────
ALLOWED_LINKS = [
    "maxifyfx.com",
    "www.maxifyfx.com",
    "t.me/MaxiFyFX",
    "facebook.com/MaxiFyFX",
    "instagram.com/MaxiFyFX",
    "x.com/MaxiFyFX",
    "twitter.com/MaxiFyFX",
    "tiktok.com/@MaxiFyFX",
]

# ── 2) يوتيوب MaxiFyFX (تعرّف تلقائي) ─────────────────────────────────
MAXIFYFX_YT_HANDLE = "MaxiFyFX"
MAXIFYFX_YT_CHANNEL_ID = ""
YOUTUBE_API_KEY = ""
BLOCK_UNVERIFIED_YOUTUBE = True
MAXIFYFX_VIDEO_ALLOWLIST = {
    "ZmTxWvv7b4I",  # فتح حساب
    "qeZq-JhlY0w",  # إيداع ماكس فاي
    "53OM1jm7RaE",  # سحب ماكس فاي
    "okerWJJWsfU",  # إيداع/سحب عن طريق وسيط
    "_YiqFvV6GM4",  # إيداع USDT
    "T5bmiieHPTQ",  # سحب USDT
}

# ── 3) أسماء المنافسين والمروّجين الممنوعين ───────────────────────────
# عقوبتها: حذف + تحذير فقط (بدون طرد)
# اكتب كل اسم بالعربي + الإنجليزي، والمُطبّع يكتشف باقي الأشكال تلقائياً.
# ⚠️ راجع التهجئة الإنجليزية للأسماء المعلّمة وعدّلها/أضِف لها حسب الواقع.
COMPETITOR_NAMES = [
    "تيران", "tiran",
    "انزو", "inzo",
    "برايم اكس", "primex", "prime x",
    "اراي افكس", "aryafx",            # ⚠️ تأكّد من التهجئة الإنجليزية
    "سامر جيرمني", "samer germany",   # ⚠️ اسم شخص — أضف التهجئة الدقيقة
    "احمد الاعرجي",                   # ⚠️ اسم شخص — أضف التهجئة الإنجليزية
    "اكس ام", "xm",                   # ⚠️ قصير، قد يسبب مطابقة نادرة غير مقصودة
]

# ── 3.5) الكلمات المحظورة (شتائم / سبام / أي كلمة تريد منعها) ──────────
# نفس فكرة المنافسين: يكتشف كل أشكال الكتابة تلقائياً (همزات/تشكيل/تكرار/leet).
# ⚠️ تجنّب الكلمات القصيرة جداً (حرفان) لتفادي المطابقة الخاطئة.
BANNED_WORDS_BAN = False   # False = حذف + تحذير  |  True = حذف + تحذير + طرد
BANNED_WORDS = [
    "كسمك",
    "عير",
    "كس",
    "خرب",
    "نيج",
    "كسختك",
    "اختك",
    "امك",
    "شيعي",
    "سني",
    "انيج",
    "النكاح",
    "كفر",
    "اكفر",
    "اتنايج",
    "مشتهي",
    "كحبه",
    "بربوك",
    "منيوج",
    "كواد",
    "بعبوص",
    "طيز",
    "صرم",
    "تناحه",
    "كحاب",
    "الحلمه",
    "الصدر",
    "العنابه",
    "عنابه",
    "صدر",
    "حلمه",
    "امص",
    "ارضع",
    "الحس",
    "لحس",
    "مص",
    "رضع",
]

# ── 4) منع تكرار الرسائل ──────────────────────────────────────────────
DUPLICATE_WINDOW_SECONDS = 60
MIN_DUP_LEN = 6

# ── 5) فحص الصور العارية (NudeNet) ────────────────────────────────────
NUDE_THRESHOLD = 0.50
UNSAFE_CLASSES = {
    "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED", "BUTTOCKS_EXPOSED", "ANUS_EXPOSED",
}

# ── 6) نظام العقوبات ──────────────────────────────────────────────────
MAX_WARNINGS = 2  # تحذيران ثم حظر (للروابط/التكرار/الصور فقط)
STRIKES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "warnings.json"
)
WARN_AUTODELETE_SECONDS = 10

# ── 7) قائمة الخدمات / الردود التلقائية ───────────────────────────────
YOUTUBE_CHANNEL = "https://youtube.com/@MaxiFyFX"
FAQ_COOLDOWN_SECONDS = 30
FAQ = [
    {
        "topic": "إيداع USDT", "cmd": "deposit_usdt", "btn": "💵 إيداع USDT",
        "keywords": ["ايداع usdt", "ايداع يو اس دي تي", "deposit usdt", "شحن usdt", "ايداع تيثر"],
        "reply": "💵 *إيداع USDT في MaxiFyFX*\nالشرح بالفيديو 👇",
        "link": "https://youtu.be/_YiqFvV6GM4",
    },
    {
        "topic": "سحب USDT", "cmd": "withdraw_usdt", "btn": "💵 سحب USDT",
        "keywords": ["سحب usdt", "withdraw usdt", "سحب يو اس دي تي", "سحب تيثر"],
        "reply": "💵 *سحب USDT من MaxiFyFX*\nالشرح بالفيديو 👇",
        "link": "https://youtu.be/T5bmiieHPTQ",
    },
    {
        "topic": "إيداع/سحب وسيط", "cmd": "broker", "btn": "🔁 إيداع/سحب وسيط",
        "keywords": ["مودع وسيط", "ايداع وسيط", "سحب وسيط", "عن طريق وسيط", "مودع و وسيط"],
        "reply": "🔁 *الإيداع والسحب عن طريق مودِع وسيط*\nالشرح بالفيديو 👇",
        "link": "https://youtu.be/okerWJJWsfU",
    },
    {
        "topic": "الإيداع", "cmd": "deposit", "btn": "💰 الإيداع",
        "keywords": ["ايداع ماكس باي", "ايداع ماكس فاي", "ايداع ماكسيفاي", "ايداع ماكسي فاي",
                     "ايداع", "اودع", "شحن رصيد", "deposit"],
        "reply": "💰 *طريقة الإيداع في MaxiFyFX*\nالشرح خطوة بخطوة 👇",
        "link": "https://youtu.be/qeZq-JhlY0w",
    },
    {
        "topic": "السحب", "cmd": "withdraw", "btn": "🏦 السحب",
        "keywords": ["سحب ماكس باي", "سحب ماكس فاي", "سحب ماكسيفاي",
                     "سحب", "اسحب", "withdraw", "payout"],
        "reply": "🏦 *طريقة السحب في MaxiFyFX*\nالشرح خطوة بخطوة 👇",
        "link": "https://youtu.be/53OM1jm7RaE",
    },
    {
        "topic": "فتح حساب", "cmd": "account", "btn": "📊 فتح حساب",
        "keywords": ["فتح حساب", "افتح حساب", "فتح حساب ماكسيفاي", "فتح حساب على ماكسيفاي",
                     "حساب تداول", "حساب جديد", "تسجيل", "سجل", "open account", "register"],
        "reply": "📊 *فتح حساب على MaxiFyFX*\nالشرح خطوة بخطوة 👇",
        "link": "https://www.youtube.com/watch?v=ZmTxWvv7b4I",
    },
    {
        "topic": "التعليم", "cmd": "education", "btn": "🎓 التعليم",
        "keywords": ["تعليم", "تعلم", "كورس", "دورة", "شرح", "education", "course", "learn"],
        "reply": "🎓 *قسم التعليم في MaxiFyFX*\nكل الدروس التعليمية على قناتنا 👇",
        "link": YOUTUBE_CHANNEL,
    },
]

FAQ_BY_TOPIC = {item["topic"]: item for item in FAQ}

TELEGRAM_HOSTS = {"t.me", "telegram.me", "telegram.dog"}

# ════════════════════════════════════════════════════════════════════
#                          🔧  المنطق الداخلي
# ════════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("MaxiFyFX-Bot")

# ── مُطبِّع النصوص ─────────────────────────────────────────────────────
_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_LEET = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "@": "a", "$": "s",
})


def normalize(text: str) -> str:
    text = text.lower()
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[إأآٱ]", "ا", text)
    text = text.replace("ى", "ي").replace("ة", "ه")
    text = re.sub(r"[^a-z\u0621-\u064A0-9]", "", text)
    text = text.translate(_LEET)
    text = re.sub(r"[^a-z\u0621-\u064A]", "", text)
    text = re.sub(r"(.)\1+", r"\1", text)
    return text


_NORM_COMPETITORS = [normalize(n) for n in COMPETITOR_NAMES if normalize(n)]


def contains_competitor(text: str) -> bool:
    norm = normalize(text)
    return any(c and c in norm for c in _NORM_COMPETITORS)


_NORM_BANNED = {normalize(w) for w in BANNED_WORDS if normalize(w)}

# سوابق ولواحق عربية شائعة (لمطابقة الكلمة مهما اتصلت بها أداة تعريف/عطف)
_AR_PREFIXES = ("وال", "فال", "بال", "كال", "لل", "ال", "و", "ف", "ب", "ك", "ل")
_AR_SUFFIXES = ("كما", "كم", "كن", "هما", "هم", "هن", "ها", "نا", "ات", "ين", "ون", "ك", "ه", "ي")


def _stems(tok: str):
    """يرجّع الكلمة وكل صيغها بعد إزالة سابقة و/أو لاحقة عربية."""
    cands = {tok}
    for p in _AR_PREFIXES:
        if tok.startswith(p) and len(tok) - len(p) >= 2:
            cands.add(tok[len(p):])
    for t in list(cands):
        for s in _AR_SUFFIXES:
            if t.endswith(s) and len(t) - len(s) >= 2:
                cands.add(t[: -len(s)])
    return cands


def contains_banned(text: str) -> bool:
    """مطابقة الكلمة المحظورة ككلمة كاملة (لا كجزء من كلمة) لتفادي الحذف الخاطئ."""
    for w in re.split(r"[^a-z\u0621-\u064A0-9]+", text.lower()):
        tok = normalize(w)
        if tok and (_stems(tok) & _NORM_BANNED):
            return True
    return False


# ── الروابط ───────────────────────────────────────────────────────────
_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,})"
    r"(/[^\s]*)?",
    re.IGNORECASE,
)
_MENTION_RE = re.compile(r"(?<![\w@/.])@([A-Za-z0-9_]{5,32})")


def _split(entry: str):
    entry = entry.strip().lower()
    entry = re.sub(r"^https?://", "", entry)
    entry = re.sub(r"^www\.", "", entry)
    parts = entry.split("/", 1)
    host = parts[0]
    path = "/" + parts[1] if len(parts) > 1 and parts[1] else ""
    return host, path.rstrip("/")


_ALLOWED = [_split(a) for a in ALLOWED_LINKS]

ALLOWED_TG_USERNAMES = set()
for _h, _p in _ALLOWED:
    if _h in TELEGRAM_HOSTS and _p:
        seg = _p.strip("/").split("/")[0].lstrip("@").lower()
        if seg:
            ALLOWED_TG_USERNAMES.add(seg)


def _is_allowed(host: str, path: str) -> bool:
    host = re.sub(r"^www\.", "", host.lower())
    path = path.lower().rstrip("/")
    for ahost, apath in _ALLOWED:
        if host == ahost and (apath == "" or path.startswith(apath)):
            return True
    return False


# ── يوتيوب ────────────────────────────────────────────────────────────
_yt_cache = {}


def _youtube_kind(host: str, path: str):
    path = path or ""
    p, _, q = path.partition("?")
    segs = [s for s in p.split("/") if s]
    query = urllib.parse.parse_qs(q)
    if host == "youtu.be":
        return ("video", segs[0]) if segs else None
    if not segs:
        return ("home", "")
    first = segs[0]
    if first.startswith("@"):
        return ("handle", first[1:])
    if first == "channel" and len(segs) > 1:
        return ("channel", segs[1])
    if first in ("c", "user") and len(segs) > 1:
        return ("custom", segs[1])
    if first == "watch":
        v = query.get("v", [None])[0]
        return ("video", v) if v else None
    if first in ("shorts", "live", "embed", "v") and len(segs) > 1:
        return ("video", segs[1])
    return None


async def _yt_video_is_maxifyfx(video_id: str) -> bool:
    if video_id in _yt_cache:
        return _yt_cache[video_id]
    result = False
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet", "id": video_id, "key": YOUTUBE_API_KEY},
            )
            data = r.json()
        items = data.get("items", [])
        if items:
            sn = items[0]["snippet"]
            if MAXIFYFX_YT_CHANNEL_ID and sn.get("channelId", "") == MAXIFYFX_YT_CHANNEL_ID:
                result = True
            elif sn.get("channelTitle", "").lower() == MAXIFYFX_YT_HANDLE.lower():
                result = True
    except Exception as e:
        log.warning("YouTube API error: %s", e)
        result = not BLOCK_UNVERIFIED_YOUTUBE
    _yt_cache[video_id] = result
    return result


async def _is_allowed_youtube(host: str, path: str) -> bool:
    kind = _youtube_kind(host, path)
    if not kind:
        return False
    k, val = kind
    if k in ("handle", "custom"):
        return val.lower() == MAXIFYFX_YT_HANDLE.lower()
    if k == "channel":
        return bool(MAXIFYFX_YT_CHANNEL_ID) and val == MAXIFYFX_YT_CHANNEL_ID
    if k == "video":
        if val in MAXIFYFX_VIDEO_ALLOWLIST:
            return True
        if YOUTUBE_API_KEY:
            return await _yt_video_is_maxifyfx(val)
        return not BLOCK_UNVERIFIED_YOUTUBE
    return False


# ── كشف نوع معرّف تيليجرام ─────────────────────────────────────────────
_chat_type_cache = {}


async def _telegram_username_type(context, username: str) -> str:
    u = username.lower()
    if u in _chat_type_cache:
        return _chat_type_cache[u]
    t = "unknown"
    try:
        chat = await context.bot.get_chat("@" + username)
        ct = chat.type
        if ct == ChatType.PRIVATE:
            t = "user"
        elif ct == ChatType.CHANNEL:
            t = "channel"
        elif ct in (ChatType.GROUP, ChatType.SUPERGROUP):
            t = "group"
    except Exception:
        t = "unknown"
    _chat_type_cache[u] = t
    return t


async def check_links(text: str, context) -> str | None:
    for m in _URL_RE.finditer(text):
        host = re.sub(r"^www\.", "", m.group(1).lower())
        path = m.group(2) or ""
        if "." not in host:
            continue

        if host.endswith("youtube.com") or host == "youtu.be":
            if await _is_allowed_youtube(host, path):
                continue
            return "غير مسموح بنشر روابط يوتيوب خارجية."

        if host in TELEGRAM_HOSTS:
            if _is_allowed(host, path):
                continue
            seg = [s for s in path.split("?")[0].split("/") if s]
            if not seg:
                continue
            first = seg[0].lstrip("@")
            if first.startswith("+") or first.lower() in ("joinchat", "c"):
                return "غير مسموح بنشر روابط دعوة أو قنوات."
            if first.lower() in ALLOWED_TG_USERNAMES:
                continue
            ttype = await _telegram_username_type(context, first)
            if ttype in ("channel", "group"):
                return "غير مسموح بنشر روابط القنوات/المجموعات."
            if ttype == "user":
                continue
            return "غير مسموح بنشر روابط خارجية."

        if _is_allowed(host, path):
            continue
        return "غير مسموح بنشر الروابط الخارجية."

    for mm in _MENTION_RE.finditer(text):
        uname = mm.group(1)
        if uname.lower() in ALLOWED_TG_USERNAMES:
            continue
        if await _telegram_username_type(context, uname) in ("channel", "group"):
            return "غير مسموح بنشر معرفات القنوات/المجموعات."
    return None


# ── منع تكرار الرسائل ─────────────────────────────────────────────────
_recent = defaultdict(deque)


def is_duplicate(chat_id: int, user_id: int, text: str) -> bool:
    norm = normalize(text)
    if len(norm) < MIN_DUP_LEN:
        return False
    now = time.time()
    dq = _recent[(chat_id, user_id)]
    while dq and now - dq[0][1] > DUPLICATE_WINDOW_SECONDS:
        dq.popleft()
    dup = any(h == norm for h, _ in dq)
    dq.append((norm, now))
    return dup


# ── فحص الصور (NudeNet) ───────────────────────────────────────────────
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from nudenet import NudeDetector
        _detector = NudeDetector()
        log.info("✅ تم تحميل موديل NudeNet")
    return _detector


def _detect_nudity_sync(path: str) -> bool:
    try:
        detections = _get_detector().detect(path)
    except Exception as e:
        log.error("خطأ في فحص الصورة: %s", e)
        return False
    return any(
        d.get("class") in UNSAFE_CLASSES and d.get("score", 0) >= NUDE_THRESHOLD
        for d in detections
    )


async def is_nude(path: str) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _detect_nudity_sync, path)


# ── المشرفون ──────────────────────────────────────────────────────────
_admin_cache = {}


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat, user = update.effective_chat, update.effective_user
    if chat is None or user is None:
        return False
    if chat.type == ChatType.PRIVATE:
        return True
    ids, exp = _admin_cache.get(chat.id, (set(), 0))
    if time.time() > exp:
        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            ids = {a.user.id for a in admins}
            _admin_cache[chat.id] = (ids, time.time() + 300)
        except Exception:
            pass
    return user.id in ids


# ── العقوبات ──────────────────────────────────────────────────────────
def _load_strikes() -> dict:
    try:
        with open(STRIKES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_strikes = _load_strikes()


def _save_strikes():
    try:
        with open(STRIKES_FILE, "w", encoding="utf-8") as f:
            json.dump(_strikes, f, ensure_ascii=False)
    except Exception as e:
        log.warning("تعذّر حفظ التحذيرات: %s", e)


async def _send_temp(context, chat_id, text):
    try:
        warn = await context.bot.send_message(chat_id, text, parse_mode="Markdown")
        if WARN_AUTODELETE_SECONDS > 0:
            await asyncio.sleep(WARN_AUTODELETE_SECONDS)
            try:
                await warn.delete()
            except Exception:
                pass
    except Exception as e:
        log.warning("تعذّر إرسال الرسالة: %s", e)


async def _delete_msg(msg):
    try:
        await msg.delete()
    except Exception as e:
        log.warning("تعذّر حذف الرسالة: %s", e)


# مخالفة صارمة: حذف + تحذير + (طرد عند المخالفة الثالثة)
async def handle_hard_violation(update, context, reason):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    await _delete_msg(msg)
    mention = f"[{user.first_name}](tg://user?id={user.id})"
    cstore = _strikes.setdefault(str(chat.id), {})
    n = cstore.get(str(user.id), 0) + 1
    cstore[str(user.id)] = n
    _save_strikes()

    if n > MAX_WARNINGS:
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            cstore[str(user.id)] = 0
            _save_strikes()
            text = f"⛔ تم حظر {mention} بعد تجاوز عدد التحذيرات."
        except Exception as e:
            text = f"⚠️ تعذّر حظر {mention} (تأكد أن البوت مشرف بصلاحية الحظر).\n{e}"
    elif n < MAX_WARNINGS:
        text = f"⚠️ {mention} {reason}\nتحذير {n}/{MAX_WARNINGS}."
    else:
        text = f"⚠️ {mention} {reason}\nتحذير أخير {n}/{MAX_WARNINGS} — المخالفة القادمة = حظر."
    await _send_temp(context, chat.id, text)


# مخالفة خفيفة: حذف + تحذير فقط (بدون طرد ولا احتساب)
async def handle_soft_violation(update, context, reason):
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    await _delete_msg(msg)
    mention = f"[{user.first_name}](tg://user?id={user.id})"
    await _send_temp(context, chat.id, f"⚠️ {mention} {reason}")


# ── الردود التلقائية ──────────────────────────────────────────────────
_faq_cooldown = {}


async def try_faq_reply(update, context, text) -> bool:
    norm = normalize(text)
    for item in FAQ:
        if any(normalize(k) in norm for k in item["keywords"]):
            key = (update.effective_chat.id, item["topic"])
            now = time.time()
            if now - _faq_cooldown.get(key, 0) < FAQ_COOLDOWN_SECONDS:
                return True
            _faq_cooldown[key] = now
            try:
                await update.effective_message.reply_text(
                    f"{item['reply']}\n{item['link']}", parse_mode="Markdown"
                )
            except Exception as e:
                log.warning("تعذّر إرسال رد FAQ: %s", e)
            return True
    return False


def _menu_keyboard():
    rows, row = [], []
    for item in FAQ:
        row.append(InlineKeyboardButton(item["btn"], callback_data=f"faq:{item['topic']}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ════════════════════════════════════════════════════════════════════
#                          📩  المعالجات
# ════════════════════════════════════════════════════════════════════
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None or not (msg.text or msg.caption):
        return
    text = msg.text or msg.caption

    if not await is_admin(update, context):
        # 1) مخالفات صارمة (روابط)
        reason = await check_links(text, context)
        if reason:
            await handle_hard_violation(update, context, reason)
            return
        # 2) مخالفة خفيفة (أسماء المنافسين/المروّجين) → تحذير فقط
        if contains_competitor(text):
            await handle_soft_violation(update, context, "تم حذف رسالتك (ذكر اسم غير مسموح به).")
            return
        # 2.5) كلمات محظورة
        if contains_banned(text):
            msg_txt = "تم حذف رسالتك (كلمة محظورة)."
            if BANNED_WORDS_BAN:
                await handle_hard_violation(update, context, msg_txt)
            else:
                await handle_soft_violation(update, context, msg_txt)
            return
        # 3) مخالفة صارمة (تكرار الرسائل)
        if is_duplicate(update.effective_chat.id, update.effective_user.id, text):
            await handle_hard_violation(update, context, "ممنوع تكرار نفس الرسالة.")
            return

    await try_faq_reply(update, context, text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None or await is_admin(update, context):
        return
    photo = msg.photo[-1] if msg.photo else None
    if photo is None:
        return
    tmp_path = None
    try:
        f = await context.bot.get_file(photo.file_id)
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        await f.download_to_drive(tmp_path)
        if await is_nude(tmp_path):
            await handle_hard_violation(update, context, "تم حذف الصورة (محتوى غير لائق).")
    except Exception as e:
        log.error("خطأ في معالجة الصورة: %s", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data and q.data.startswith("faq:"):
        item = FAQ_BY_TOPIC.get(q.data.split(":", 1)[1])
        if item:
            await q.message.reply_text(f"{item['reply']}\n{item['link']}", parse_mode="Markdown")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "👋 أهلاً بك في *MaxiFyFX*\nاختر الخدمة التي تريدها 👇",
        parse_mode="Markdown", reply_markup=_menu_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "ℹ️ *قائمة خدمات MaxiFyFX*\nاضغط الزر أو اكتب / لعرض الأوامر 👇",
        parse_mode="Markdown", reply_markup=_menu_keyboard(),
    )


def _make_faq_cmd(topic):
    async def _cmd(update, context):
        item = FAQ_BY_TOPIC[topic]
        await update.effective_message.reply_text(
            f"{item['reply']}\n{item['link']}", parse_mode="Markdown"
        )
    return _cmd


async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    reply = update.effective_message.reply_to_message
    if not reply:
        await update.effective_message.reply_text("↩️ ردّ على رسالة العضو ثم اكتب /resetwarns")
        return
    _strikes.setdefault(str(update.effective_chat.id), {})[str(reply.from_user.id)] = 0
    _save_strikes()
    await update.effective_message.reply_text(f"✅ تم تصفير تحذيرات {reply.from_user.first_name}.")


# تسجيل قائمة الأوامر التي تظهر للمستخدم عند كتابة /
async def _post_init(app):
    cmds = [BotCommand(item["cmd"], item["btn"]) for item in FAQ]
    cmds.append(BotCommand("help", "ℹ️ القائمة والمساعدة"))
    await app.bot.set_my_commands(cmds)


def main():
    if BOT_TOKEN == "ضع_التوكن_هنا":
        raise SystemExit("⚠️ ضع توكن البوت في BOT_TOKEN أولاً.")
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("resetwarns", cmd_resetwarns))
    for item in FAQ:
        app.add_handler(CommandHandler(item["cmd"], _make_faq_cmd(item["topic"])))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^faq:"))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_text))

    log.info("🚀 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()