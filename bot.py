import os
import re
import time
import requests
from dotenv import load_dotenv

from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_PROMPT = (
    "You are a helpful Myanmar-language AI assistant for content creation and Telegram group admin support. "
    "Default Burmese unless user writes English. Keep output practical, ready to copy-paste."
)

# --- Simple memory (per user) ---
MEM = {}
MAX_TURNS = 8

# --- Anti-spam state (per chat) ---
ANTISPAM = {}  # chat_id -> bool
LAST_MSG = {}  # (chat_id, user_id) -> {"t":time, "txt":text, "count":int}

# Menu buttons
MENU = ReplyKeyboardMarkup(
    [
        ["📝 Post", "🎬 Caption", "📣 Ads"],
        ["🧲 Hook", "✅ CTA", "🧾 Summarize"],
        ["👋 Welcome", "📌 Rules", "⚠️ Warn"],
        ["🛡️ Anti-Spam", "🧹 Reset", "ℹ️ About"],
    ],
    resize_keyboard=True
)

def gemini_generate(text: str) -> str:
    if not GEMINI_API_KEY:
        return "GEMINI_API_KEY မတွေ့ဘူး။ .env ထဲမှာ GEMINI_API_KEY ထည့်ပေးပါ။"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"role": "user", "parts": [{"text": text}]}]}
    r = requests.post(url, json=payload, timeout=60)

    if r.status_code != 200:
        return f"Gemini API Error: {r.status_code}\n{r.text[:300]}"

    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return "Gemini ပြန်လည်ဖြေဆိုမှုကို ဖတ်မရပါ။"

def remember(user_id: int, user_text: str, reply: str):
    MEM.setdefault(user_id, [])
    MEM[user_id].append((user_text, reply))
    MEM[user_id] = MEM[user_id][-MAX_TURNS:]

def build_prompt(user_id: int, user_text: str) -> str:
    hist = MEM.get(user_id, [])
    hist_text = ""
    for u, a in hist[-MAX_TURNS:]:
        hist_text += f"User: {u}\nAssistant: {a}\n"
    return f"{SYSTEM_PROMPT}\n\n{hist_text}\nUser: {user_text}\nAssistant:"

# --- Anti-spam helpers ---
LINK_RE = re.compile(r"(https?://|t\.me/|www\.)", re.I)

def antispam_on(chat_id: int) -> bool:
    return ANTISPAM.get(chat_id, False)

def is_spam(chat_id: int, user_id: int, text: str) -> bool:
    now = time.time()
    key = (chat_id, user_id)
    prev = LAST_MSG.get(key)

    # Too many links
    if len(LINK_RE.findall(text)) >= 2:
        return True

    # Repeated messages quickly
    if prev:
        dt = now - prev["t"]
        same = (text.strip() == prev["txt"].strip())
        if dt < 10 and same:
            prev["count"] += 1
            prev["t"] = now
            LAST_MSG[key] = prev
            if prev["count"] >= 2:
                return True
        else:
            LAST_MSG[key] = {"t": now, "txt": text, "count": 0}
    else:
        LAST_MSG[key] = {"t": now, "txt": text, "count": 0}

    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "မင်္ဂလာပါ 👋\nAImaster_bot မှာ Content Creator + Group Admin helper features ပါပါတယ်။",
        reply_markup=MENU
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ အသုံးပြုနည်း\n"
        "/post <topic> - FB post\n"
        "/caption <desc> - Caption\n"
        "/ads <product/service> - Ads copy\n"
        "/hook <topic> - Hook/Headline\n"
        "/cta <goal> - CTA စာတို\n"
        "/welcome <name/info> - Welcome\n"
        "/rules <group type> - Rules\n"
        "/warn <reason> - Warning\n"
        "/antispam on|off - Anti-spam toggle (Group မှာသာအသုံးဝင်)\n"
        "/menu - Menu\n"
        "/reset - memory clear\n\n"
        "သို့မဟုတ် Menu ခလုတ်တွေကိုနှိပ်ပြီးလည်း သုံးလို့ရပါတယ် ✅",
        reply_markup=MENU
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Menu ✅", reply_markup=MENU)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    MEM.pop(uid, None)
    await update.message.reply_text("OK ✅ memory ရှင်းပြီးပါပြီ။", reply_markup=MENU)

async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "AImaster_bot 🤖\n"
        "✅ Content Creator: post/caption/ads/hook/cta\n"
        "✅ Group Admin helper: welcome/rules/warn/anti-spam\n",
        reply_markup=MENU
    )

# --- Content creator commands ---
async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Usage: /post topic", reply_markup=MENU); return
    prompt = (
        f"{SYSTEM_PROMPT}\nWrite a catchy Burmese Facebook post about: {topic}\n"
        "Include: 1 hook line, 3-5 short lines, emojis, and a clear CTA.\n"
        "Output ready to copy."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def caption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = " ".join(context.args).strip()
    if not desc:
        await update.message.reply_text("Usage: /caption photo/video description", reply_markup=MENU); return
    prompt = (
        f"{SYSTEM_PROMPT}\nCreate 5 caption options for: {desc}\n"
        "Mix: short, medium, funny, professional, and emotional. Add suitable emojis."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def ads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prod = " ".join(context.args).strip()
    if not prod:
        await update.message.reply_text("Usage: /ads product/service details", reply_markup=MENU); return
    prompt = (
        f"{SYSTEM_PROMPT}\nWrite an ad copy in Burmese for: {prod}\n"
        "Include: headline, benefits bullets, offer, trust line, CTA.\n"
        "Make it persuasive but not spammy."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def hook_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Usage: /hook topic", reply_markup=MENU); return
    prompt = (
        f"{SYSTEM_PROMPT}\nGenerate 15 strong hook lines/headlines in Burmese for: {topic}\n"
        "Make them scroll-stopping, short, and varied styles."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def cta_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    goal = " ".join(context.args).strip()
    if not goal:
        await update.message.reply_text("Usage: /cta goal (e.g., 'join group', 'order now')", reply_markup=MENU); return
    prompt = (
        f"{SYSTEM_PROMPT}\nWrite 20 short CTA lines in Burmese for this goal: {goal}\n"
        "Include polite + urgent + friendly options."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def summarize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: /summarize text", reply_markup=MENU); return
    prompt = f"{SYSTEM_PROMPT}\nSummarize in Burmese bullets (short & clear):\n\n{text}"
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

# --- Admin helper commands ---
async def welcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = " ".join(context.args).strip() or "Member"
    prompt = (
        f"{SYSTEM_PROMPT}\nWrite a warm welcome message for new member: {info}\n"
        "Include: greet, what group is for, rules reminder, friendly tone."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_type = " ".join(context.args).strip() or "General chat group"
    prompt = (
        f"{SYSTEM_PROMPT}\nWrite clear Telegram group rules for: {group_type}\n"
        "Numbered list, short, friendly. Include: no spam, no scams, respect, relevant posts, report to admin."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = " ".join(context.args).strip() or "spam"
    prompt = (
        f"{SYSTEM_PROMPT}\nWrite a short warning message to a member who violated rules بسبب: {reason}\n"
        "Polite but firm. Include next action if repeated."
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    reply = gemini_generate(prompt)
    await update.message.reply_text(reply, reply_markup=MENU)

async def antispam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    arg = (context.args[0].lower() if context.args else "").strip()

    if arg in ("on", "enable", "1"):
        ANTISPAM[chat_id] = True
        await update.message.reply_text("🛡️ Anti-spam ON ✅", reply_markup=MENU)
    elif arg in ("off", "disable", "0"):
        ANTISPAM[chat_id] = False
        await update.message.reply_text("🛡️ Anti-spam OFF ❌", reply_markup=MENU)
    else:
        status = "ON ✅" if antispam_on(chat_id) else "OFF ❌"
        await update.message.reply_text(f"Anti-spam status: {status}\nUsage: /antispam on | /antispam off", reply_markup=MENU)

# --- Button handling + spam control ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    uid = update.effective_user.id
    msg = (update.message.text or "").strip()

    # Anti-spam (only if enabled)
    if antispam_on(chat_id):
        if is_spam(chat_id, uid, msg):
            # delete spam if bot has admin rights; ignore failures
            try:
                await update.message.delete()
            except Exception:
                pass
            try:
                await context.bot.send_message(chat_id, "⚠️ Spam မလုပ်ပါနဲ့။ Rules ကိုလိုက်နာပေးပါ။")
            except Exception:
                pass
            return

    # Menu shortcuts
    if msg == "📝 Post":
        await update.message.reply_text("Topic ပို့ပါ ✅\nဥပမာ: /post Free Money group promotion", reply_markup=MENU); return
    if msg == "🎬 Caption":
        await update.message.reply_text("Caption အတွက် description ပို့ပါ ✅\nဥပမာ: /caption rainy night photo", reply_markup=MENU); return
    if msg == "📣 Ads":
        await update.message.reply_text("Product/Service details ပို့ပါ ✅\nဥပမာ: /ads skincare set 20% off", reply_markup=MENU); return
    if msg == "🧲 Hook":
        await update.message.reply_text("Hook လိုတဲ့ topic ပို့ပါ ✅\nဥပမာ: /hook earn money online", reply_markup=MENU); return
    if msg == "✅ CTA":
        await update.message.reply_text("CTA goal ပို့ပါ ✅\nဥပမာ: /cta join telegram group", reply_markup=MENU); return
    if msg == "🧾 Summarize":
        await update.message.reply_text("Usage: /summarize <text>", reply_markup=MENU); return
    if msg == "👋 Welcome":
        await update.message.reply_text("Usage: /welcome <name/info>", reply_markup=MENU); return
    if msg == "📌 Rules":
        await update.message.reply_text("Usage: /rules <group type>", reply_markup=MENU); return
    if msg == "⚠️ Warn":
        await update.message.reply_text("Usage: /warn <reason>", reply_markup=MENU); return
    if msg == "🛡️ Anti-Spam":
        # toggle for this chat
        ANTISPAM[chat_id] = not ANTISPAM.get(chat_id, False)
        status = "ON ✅" if ANTISPAM[chat_id] else "OFF ❌"
        await update.message.reply_text(f"🛡️ Anti-spam {status}", reply_markup=MENU); return
    if msg == "🧹 Reset":
        await reset_cmd(update, context); return
    if msg == "ℹ️ About":
        await about_cmd(update, context); return

    # Default: AI chat for any text
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    prompt = build_prompt(uid, msg)
    reply = gemini_generate(prompt)
    remember(uid, msg, reply)

    # Telegram limit
    if len(reply) <= 4000:
        await update.message.reply_text(reply, reply_markup=MENU)
    else:
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000], reply_markup=MENU)

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN မရှိသေးပါ။ .env ထဲထည့်ပါ။")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("about", about_cmd))

    # content
    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("caption", caption_cmd))
    app.add_handler(CommandHandler("ads", ads_cmd))
    app.add_handler(CommandHandler("hook", hook_cmd))
    app.add_handler(CommandHandler("cta", cta_cmd))
    app.add_handler(CommandHandler("summarize", summarize_cmd))

    # admin
    app.add_handler(CommandHandler("welcome", welcome_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("antispam", antispam_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == "__main__":
    main()
