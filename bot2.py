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
# CONFIGURATIONS
# ================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN") 
ADMIN_IDS = [7212602902]  # Add your admin IDs here

CASH_TO_ADD = 50_000_000  # 50 Million Max Cash

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

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args): return

def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    ThreadingHTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            if update.callback_query: await update.callback_query.answer()
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_accounts(data):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

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
    def encrypt(self, s): return base64.b64encode(AES.new(self.key, AES.MODE_CBC, self.iv).encrypt(pad(s.encode(), 16))).decode()
    def decrypt(self, s):
        try: return unpad(AES.new(self.key, AES.MODE_CBC, self.iv).decrypt(base64.b64decode(s)), 16).decode()
        except: return None
    def extract_value(self, data):
        if isinstance(data, (int, float)): return int(data)
        if isinstance(data, str):
            try: return self.extract_value(json.loads(data))
            except: pass
            if data.isdigit(): return int(data)
            numbers = re.findall(r'\d+', data)
            if numbers: return int(numbers[0])
        if isinstance(data, list):
            for item in data:
                val = self.extract_value(item)
                if val is not None: return val
        if isinstance(data, dict):
            for key in ['money', 'cash', 'value', 'amount', 'data']:
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
def mp_encode(data, uid): return base64.b64encode(_xor_data(brotli.compress(data, quality=5), _xor_key(uid))).decode()
def mp_i32(v): return struct.pack('<i', v)
def mp_u16(v): return struct.pack('<H', v)
def mp_i64(v): return struct.pack('<q', v)

def gen_device_id(): return MARKO_DEVICE_PREFIX + ''.join(random.choice('0123456789abcdef') for _ in range(28))

def phoenix_headers(token):
    return {
        "User-Agent": USER_AGENT, "Content-Type": "application/json; charset=utf-8",
        "X-Unity-Version": "2022.3.62f2", "Authorization": f"Bearer {token}",
        "X-Client-Hash": CLIENT_HASH, "X-Phoenix-Signature": MARKO_SIGNATURE,
        "X-Phoenix-Version": MARKO_VERSION, "X-Phoenix-Developer": DEVELOPER,
    }

async def phoenix_login(email, password, session):
    try:
        async with session.post(FB_LOGIN, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20) as response:
            data = await response.json()
            if "idToken" in data: return {"token": data["idToken"], "uid": data["localId"]}
    except: pass
    return None

async def phoenix_inject_cash(session, token, uid, target_amount):
    """MemoryPack vazhi Cash (Money) direct aayi max aakkunna function (Type 0 = Cash)"""
    wallet_data = mp_i32(1) + mp_u16(0) + mp_i32(8) + mp_i64(target_amount)
    encoded_payload = mp_encode(wallet_data, uid)
    url = f"{CF_BASE}/SaveWalletData23_1"
    try:
        async with session.post(url, headers=phoenix_headers(token), json={"data": encoded_payload}, timeout=20) as response:
            if response.status == 200:
                return True
    except: pass
    return False

# ================================================================
# TELEGRAM UI & HANDLERS
# ================================================================
def get_main_menu(): return ReplyKeyboardMarkup([["🚀 Start Max Cash", "📋 My Accounts"]], resize_keyboard=True)
def get_accounts_main_inline(): return InlineKeyboardMarkup([[InlineKeyboardButton("👁 View", callback_data="view_accounts")], [InlineKeyboardButton("✏️ Edit", callback_data="edit_accounts")]])
def get_edit_accounts_inline(): return InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add", callback_data="add_accounts")], [InlineKeyboardButton("🗑 Delete", callback_data="delete_accounts")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_acc_main")]])

def build_accounts_page(user_id, page=0):
    accounts = get_user_accounts(user_id)
    total = len(accounts)
    pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    accs = accounts[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]
    text = f"📋 **Accounts** (`{total}/{MAX_ACCOUNTS}`)\nPage `{page + 1}/{pages}`\n\n"
    for i, a in enumerate(accs, start=page * ITEMS_PER_PAGE + 1): text += f"`{i}.` `{a['email']}:{a['password']}`\n"
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("◀️", callback_data=f"acc_page_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1: nav.append(InlineKeyboardButton("▶️", callback_data=f"acc_page_{page + 1}"))
    return text, InlineKeyboardMarkup([nav] if pages > 1 else [])

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    get_user_accounts(update.effective_user.id)
    await update.message.reply_text("🤖 **Max Cash Bot Active**", reply_markup=get_main_menu(), parse_mode="Markdown")

@admin_only
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🚀 Start Max Cash":
        await update.message.reply_text("🔑 Send account details as `email:password`", parse_mode="Markdown")
        return WAITING_FARM_CREDS
    elif text == "📋 My Accounts":
        await update.message.reply_text("📋 **Manage Accounts**", reply_markup=get_accounts_main_inline(), parse_mode="Markdown")
    return ConversationHandler.END

@admin_only
async def process_farming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = update.message.text.strip()
    if ":" not in creds:
        await update.message.reply_text("❌ Send as `email:password`")
        return WAITING_FARM_CREDS

    email, password = creds.split(":", 1)
    status_msg = await update.message.reply_text("🔑 Authenticating...", parse_mode="Markdown")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        auth = await phoenix_login(email, password, session)
        if not auth:
            await status_msg.edit_text("❌ **Login Failed!**")
            return ConversationHandler.END

        token, uid = auth["token"], auth["uid"]
        
        await status_msg.edit_text("⚡ Injecting Max Cash...", parse_mode="Markdown")
        success = await phoenix_inject_cash(session, token, uid, CASH_TO_ADD)

        if success:
            result_text = (
                "✅ **Max Cash Added Successfully!**\n\n"
                f"• **Account**: `{email}`\n"
                f"• **Cash Added**: `{CASH_TO_ADD:,}` 💵\n"
                f"• **Status**: Safe & Updated"
            )
        else:
            result_text = "❌ **Injection Failed.** Server rejected."

        await status_msg.edit_text(result_text, parse_mode="Markdown")

    return ConversationHandler.END

@admin_only
async def handle_inline_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    d = query.data
    await query.answer()
    if d == "back_to_acc_main": await query.edit_message_text("📋 **Accounts**", reply_markup=get_accounts_main_inline(), parse_mode="Markdown")
    elif d == "view_accounts":
        t, m = build_accounts_page(uid, 0)
        await query.edit_message_text(t, reply_markup=m, parse_mode="Markdown")
    elif d == "edit_accounts": await query.edit_message_text("✏️ **Edit**", reply_markup=get_edit_accounts_inline(), parse_mode="Markdown")
    elif d.startswith("acc_page_"):
        t, m = build_accounts_page(uid, int(d.split("_")[-1]))
        await query.edit_message_text(t, reply_markup=m, parse_mode="Markdown")
    elif d == "add_accounts":
        await query.message.reply_text("📥 Send `email:password`:")
        return WAITING_ADD_ACCOUNTS
    elif d == "delete_accounts":
        await query.message.reply_text("🗑 Send `email:password`:")
        return WAITING_DELETE_ACCOUNTS

@admin_only
async def process_add_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    accs = get_user_accounts(uid)
    added = 0
    for line in update.message.text.strip().split("\n"):
        if ":" in line:
            e, p = line.split(":", 1)
            if not any(a["email"] == e.strip() for a in accs) and len(accs) < MAX_ACCOUNTS:
                accs.append({"email": e.strip(), "password": p.strip()}); added += 1
    ACCOUNTS_DB[str(uid)] = accs; save_accounts(ACCOUNTS_DB)
    await update.message.reply_text(f"✅ Saved {added} accounts!", reply_markup=get_main_menu())
    return ConversationHandler.END

@admin_only
async def process_delete_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    accs = get_user_accounts(uid)
    targets = {l.split(":", 1)[0].strip() if ":" in l else l.strip() for l in update.message.text.strip().split("\n")}
    upd = [a for a in accs if a["email"] not in targets]
    ACCOUNTS_DB[str(uid)] = upd; save_accounts(ACCOUNTS_DB)
    await update.message.reply_text(f"🗑 Deleted {len(accs) - len(upd)} accounts!", reply_markup=get_main_menu())
    return ConversationHandler.END

@admin_only
async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Canceled.", reply_markup=get_main_menu())
    return ConversationHandler.END

def main():
    threading.Thread(target=start_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🚀 Start Max Cash$"), handle_menu), CallbackQueryHandler(handle_inline_buttons, pattern="^(add_accounts\vert{}delete_accounts)$")],
        states={
            WAITING_FARM_CREDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_farming)],
            WAITING_ADD_ACCOUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_add_accounts)],
            WAITING_DELETE_ACCOUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete_accounts)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler), MessageHandler(filters.TEXT, handle_menu)]
    ))
    app.add_handler(CallbackQueryHandler(handle_inline_buttons))
    app.add_handler(MessageHandler(filters.TEXT, handle_menu))
    app.run_polling()

if __name__ == "__main__": main()
