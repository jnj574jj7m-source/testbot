#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import base64
import struct
import time
import asyncio
import aiohttp
import random
import string
import warnings
import re
import os
import threading
import brotli
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import wraps
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)

warnings.filterwarnings('ignore')

# ================================================================
# CONFIGURATIONS & FILE PATHS
# ================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN") 
ADMIN_IDS = [7212602902]  # Add your admin IDs here

COINS_TO_ADD = 1000 # <-- Ithu maatti ningalkku ishtamulla amount (eg: 5000) aakkam

ACCOUNTS_FILE = "accounts.json"
MAX_ACCOUNTS = 50
ITEMS_PER_PAGE = 10

API_KEY = 'AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ'
CF_BASE = 'https://europe-west1-cpm-2-7cea1.cloudfunctions.net'
OG_BASE = 'https://cpm-2.ogames.kz/api'
OG_KEY = '320b93f3e7f4410aa52ce24da363ad04'
VERSION = '1.3.2.3'
CLIENT_HASH = 'F05A72840B40DC4FAADF539C5E38062527AE6422'
BUNDLE_ID = 'com.olzhas.carparking.multyplayer2'
USER_AGENT = 'UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)'
FB_LOGIN = f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}'

KEY_ADD = '12345678'
IV_ADD = '01234567'

MARKO_VERSION = "3.0.0-PHOENIX"
MARKO_SIGNATURE = "PH03N1X_C0R3"
MARKO_DEVICE_PREFIX = "PHOENIX-DEVICE-"
DEVELOPER = "MARKO"

WAITING_FARM_CREDS, WAITING_ADD_ACCOUNTS, WAITING_DELETE_ACCOUNTS = range(3)

# ================================================================
# RENDER HEALTH SERVER
# ================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 Health server listening on port {port}")
    server.serve_forever()

# ================================================================
# ADMIN SECURITY FILTER DECORATOR
# ================================================================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            if update.callback_query: await update.callback_query.answer()
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ================================================================
# PERSISTENCE STORAGE HELPERS
# ================================================================
def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_accounts(data):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

ACCOUNTS_DB = load_accounts()

def get_user_accounts(user_id):
    uid_str = str(user_id)
    if uid_str not in ACCOUNTS_DB:
        ACCOUNTS_DB[uid_str] = []
        save_accounts(ACCOUNTS_DB)
    return ACCOUNTS_DB[uid_str]

# ================================================================
# CRYPTO & MEMORYPACK ENGINE
# ================================================================
class Crypto:
    def __init__(self, uid):
        self.uid = uid
        self.key = (uid[:8] + KEY_ADD).encode()[:16]
        self.iv = (uid[:8] + IV_ADD).encode()[:16]

    def encrypt(self, s):
        return base64.b64encode(AES.new(self.key, AES.MODE_CBC, self.iv).encrypt(pad(s.encode(), 16))).decode()

    def decrypt(self, s):
        try:
            return unpad(AES.new(self.key, AES.MODE_CBC, self.iv).decrypt(base64.b64decode(s)), 16).decode()
        except Exception:
            return None

    def extract_value(self, data):
        if isinstance(data, (int, float)): return int(data)
        if isinstance(data, str):
            try: return self.extract_value(json.loads(data))
            except Exception: pass
            if data.isdigit(): return int(data)
            numbers = re.findall(r'\d+', data)
            if numbers: return int(numbers[0])
        if isinstance(data, list):
            for item in data:
                val = self.extract_value(item)
                if val is not None: return val
        if isinstance(data, dict):
            for key in ['coins', 'value', 'coin', 'amount', 'points', 'data']:
                if key in data:
                    val = self.extract_value(data[key])
                    if val is not None: return val
        return None

def _xor_key(uid):
    c = list(uid)
    if len(c) >= 7: c[4], c[6] = c[6], c[4]
    if len(c) >= 9: del c[8]
    if len(c) >= 1: c.append(c[0])
    return ''.join(c).encode()

def _xor_data(d, k): return bytes(b ^ k[i % len(k)] for i, b in enumerate(d))

def mp_encode(data, uid):
    return base64.b64encode(_xor_data(brotli.compress(data, quality=5), _xor_key(uid))).decode()

def mp_i32(v): return struct.pack('<i', v)
def mp_u16(v): return struct.pack('<H', v)
def mp_i64(v): return struct.pack('<q', v)

def gen_device_id():
    return MARKO_DEVICE_PREFIX + ''.join(random.choice('0123456789abcdef') for _ in range(28))

def unity_headers(token):
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=utf-8",
        "X-Unity-Version": "2022.3.62f2",
        "Authorization": f"Bearer {token}",
        "X-Client-Hash": CLIENT_HASH,
        "X-Client-Platform": "ANDROID",
        "X-Client-Version": VERSION,
        "X-Client-DeviceId": gen_device_id(),
        "X-Api-Key": OG_KEY,
        "X-Client-Env": "prod",
        "X-Bundle-Id": BUNDLE_ID,
    }

# ================================================================
# ASYNC API FUNCTIONS
# ================================================================
async def phoenix_login(email, password, session):
    try:
        async with session.post(FB_LOGIN, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20) as response:
            data = await response.json()
            if "idToken" in data:
                return {"token": data["idToken"], "uid": data["localId"]}
    except Exception:
        pass
    return None

async def phoenix_get_coins(session, token, uid):
    url = f"{CF_BASE}/GetCoins23_1"
    try:
        async with session.post(url, headers=unity_headers(token), json={"data": None}, timeout=20) as response:
            if response.status == 200:
                result = await response.json()
                if "result" in result and isinstance(result["result"], dict) and "data" in result["result"]:
                    crypto = Crypto(uid)
                    decrypted_str = crypto.decrypt(result["result"]["data"])
                    return crypto.extract_value(decrypted_str) or 0
    except Exception:
        pass
    return 0

async def phoenix_inject_coins(session, token, uid, target_amount):
    """MemoryPack vazhi coins mathram update cheyyunna function"""
    # Ivide mp_u16(1) aakkiyittundu (1 = Coins)
    wallet_data = mp_i32(1) + mp_u16(1) + mp_i32(8) + mp_i64(target_amount)
    encoded_payload = mp_encode(wallet_data, uid)
    url = f"{CF_BASE}/SaveWalletData23_1"
    try:
        async with session.post(url, headers=unity_headers(token), json={"data": encoded_payload}, timeout=20) as response:
            if response.status == 200:
                return True
    except Exception:
        pass
    return False


# ================================================================
# TELEGRAM UI HELPERS
# ================================================================
def get_main_menu():
    return ReplyKeyboardMarkup(
        [["🚀 Start Farming", "📋 My Accounts"]],
        resize_keyboard=True
    )

def get_accounts_main_inline():
    keyboard = [
        [InlineKeyboardButton("👁 View All Accounts", callback_data="view_accounts")],
        [InlineKeyboardButton("✏️ Edit Accounts", callback_data="edit_accounts")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_edit_accounts_inline():
    keyboard = [
        [InlineKeyboardButton("➕ Add Accounts", callback_data="add_accounts")],
        [InlineKeyboardButton("🗑 Delete Accounts", callback_data="delete_accounts")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_acc_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_accounts_page(user_id, page=0):
    accounts = get_user_accounts(user_id)
    total_accs = len(accounts)
    total_pages = max(1, (total_accs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_accs = accounts[start_idx:end_idx]

    text = f"📋 **Saved Accounts** (`{total_accs}/{MAX_ACCOUNTS}`)\n"
    text += f"Page `{page + 1}/{total_pages}`\n\n"

    if not accounts:
        text += "_No accounts saved yet._"
    else:
        for idx, acc in enumerate(page_accs, start=start_idx + 1):
            text += f"`{idx}.` `{acc['email']}:{acc['password']}`\n"

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"acc_page_{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1: nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"acc_page_{page + 1}"))

    keyboard = []
    if total_pages > 1 or total_accs > 0: keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_acc_main")])
    return text, InlineKeyboardMarkup(keyboard)

# ================================================================
# HANDLERS
# ================================================================
@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user_accounts(user.id)
    await update.message.reply_text(
        "🤖 **Welcome to Hybrid Injection Bot**\nSelect an option below:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@admin_only
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🚀 Start Farming":
        await update.message.reply_text(
            "🔑 **Start Injection**\n\n"
            "Please send your account details in format:\n"
            "`email:password`",
            parse_mode="Markdown"
        )
        return WAITING_FARM_CREDS
    elif text == "📋 My Accounts":
        await update.message.reply_text(
            "📋 **My Accounts Management**\n\nChoose an action below:",
            reply_markup=get_accounts_main_inline(),
            parse_mode="Markdown"
        )
    return ConversationHandler.END

@admin_only
async def process_farming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = update.message.text.strip()
    if ":" not in creds:
        await update.message.reply_text("❌ Invalid format. Send as `email:password`", parse_mode="Markdown")
        return WAITING_FARM_CREDS

    email, password = creds.split(":", 1)
    status_msg = await update.message.reply_text("🔑 Authenticating account...", parse_mode="Markdown")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        auth = await phoenix_login(email, password, session)
        if not auth:
            await status_msg.edit_text("❌ **Authentication Failed!** Check credentials.")
            return ConversationHandler.END

        token, uid = auth["token"], auth["uid"]
        
        # 1. Check current balance
        await status_msg.edit_text("🔄 Checking current balance...")
        current_coins = await phoenix_get_coins(session, token, uid)
        
        # 2. Calculate new balance
        target_coins = current_coins + COINS_TO_ADD
        await status_msg.edit_text(f"⚡ Injecting {COINS_TO_ADD} coins...\n(Current: {current_coins:,} ➡️ Target: {target_coins:,})")

        # 3. Inject coins directly
        await asyncio.sleep(1) # Small delay for safety
        success = await phoenix_inject_coins(session, token, uid, target_coins)

        # 4. Verify new balance
        final_coins = await phoenix_get_coins(session, token, uid) if success else current_coins
        
        if success:
            result_text = (
                "✅ **Injection Completed Successfully!**\n\n"
                f"• **Account**: `{email}`\n"
                f"• **Previous Balance**: `{current_coins:,}`\n"
                f"• **Coins Added**: `{COINS_TO_ADD:,}` 🪙\n"
                f"• **Final Balance**: `{final_coins:,}`"
            )
        else:
            result_text = "❌ **Injection Failed.** Game server rejected the save data."

        await status_msg.edit_text(result_text, parse_mode="Markdown")

    return ConversationHandler.END

@admin_only
async def handle_inline_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    await query.answer()

    if data == "back_to_acc_main":
        await query.edit_message_text("📋 **My Accounts Management**", reply_markup=get_accounts_main_inline(), parse_mode="Markdown")
    elif data == "view_accounts":
        msg_text, reply_markup = build_accounts_page(user_id, page=0)
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif data == "edit_accounts":
        await query.edit_message_text("✏️ **Edit Accounts Menu**", reply_markup=get_edit_accounts_inline(), parse_mode="Markdown")
    elif data.startswith("acc_page_"):
        page = int(data.split("_")[-1])
        msg_text, reply_markup = build_accounts_page(user_id, page=page)
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif data == "add_accounts":
        await query.message.reply_text(f"📥 **Add Accounts (Max {MAX_ACCOUNTS})**\nSend in `email:password` format:", parse_mode="Markdown")
        return WAITING_ADD_ACCOUNTS
    elif data == "delete_accounts":
        await query.message.reply_text("🗑 **Delete Accounts**\nSend in `email:password` or `email` format:", parse_mode="Markdown")
        return WAITING_DELETE_ACCOUNTS
    elif data == "noop":
        pass

@admin_only
async def process_add_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split("\n")
    accounts = get_user_accounts(user_id)
    added = 0
    for line in lines:
        if ":" in line:
            email, password = line.strip().split(":", 1)
            email, password = email.strip(), password.strip()
            if not any(a["email"] == email for a in accounts):
                if len(accounts) < MAX_ACCOUNTS:
                    accounts.append({"email": email, "password": password})
                    added += 1
    ACCOUNTS_DB[str(user_id)] = accounts
    save_accounts(ACCOUNTS_DB)
    await update.message.reply_text(f"✅ **Saved {added} account(s)!** (`{len(accounts)}/{MAX_ACCOUNTS}`)", reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

@admin_only
async def process_delete_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split("\n")
    accounts = get_user_accounts(user_id)
    targets_to_remove = set()
    for line in lines:
        line_clean = line.strip()
        if ":" in line_clean:
            email, password = line_clean.split(":", 1)
            targets_to_remove.add(email.strip())
        elif line_clean:
            targets_to_remove.add(line_clean)
    initial_count = len(accounts)
    updated_accounts = [acc for acc in accounts if acc["email"] not in targets_to_remove]
    deleted_count = initial_count - len(updated_accounts)
    ACCOUNTS_DB[str(user_id)] = updated_accounts
    save_accounts(ACCOUNTS_DB)
    await update.message.reply_text(f"🗑 **Deleted {deleted_count} account(s)!** (`{len(updated_accounts)}/{MAX_ACCOUNTS}`)", reply_markup=get_main_menu(), parse_mode="Markdown")
    return ConversationHandler.END

@admin_only
async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation canceled.", reply_markup=get_main_menu())
    return ConversationHandler.END

# ================================================================
# MAIN BOT RUNNER
# ================================================================
def main():
    threading.Thread(target=start_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🚀 Start Farming$"), handle_menu),
            CallbackQueryHandler(handle_inline_buttons, pattern="^(add_accounts|delete_accounts)$"),
        ],
        states={
            WAITING_FARM_CREDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_farming)],
            WAITING_ADD_ACCOUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_accounts)],
            WAITING_DELETE_ACCOUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete_accounts)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_handler),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu)
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_inline_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    print("🤖 Hybrid Injection Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
