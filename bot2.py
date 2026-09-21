#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import base64
import time
import asyncio
import aiohttp
import random
import string
import warnings
import re
import os
import threading
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
ADMIN_IDS = [6876395516, 7199272008]  # Add your admin IDs here

COINS_TO_ADD = 1000 # <-- Ethra coins farm cheyyanam ennu ivide kodukkam

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

# KING RANK STATS (Required to get coins from Drag Race)
KING_RATING_RESULT_ALL = {
    "general": {
        "cars": 100000, "car_fix": 100000, "car_collided": 100000, "car_exchange": 100000,
        "car_trade": 100000, "car_wash": 100000, "slicer_cut": 100000, "drift_max": 100000,
        "drift": 100000, "cargo": 100000, "delivery": 100000, "taxi": 100000, "levels": 100000,
        "gifts": 100000, "fuel": 100000, "offroad": 100000, "speed_banner": 100000,
        "reactions": 100000, "police": 100000, "run": 100000, "real_estate": 100000,
        "t_distance": 100000, "treasure": 100000, "block_post": 100000, "push_ups": 100000,
        "burnt_tire": 100000, "passanger_distance": 100000, "time": 9999999999, "race_win": 5000,
    },
    "achievements": {
        "cars": 5, "car_fix": 5, "car_collided": 5, "car_exchange": 5,
        "car_trade": 5, "car_wash": 5, "slicer_cut": 5, "drift_max": 5,
        "drift": 5, "cargo": 5, "delivery": 5, "taxi": 5, "levels": 5,
        "gifts": 5, "fuel": 5, "offroad": 5, "speed_banner": 5,
        "reactions": 5, "police": 5, "run": 5, "real_estate": 5,
        "t_distance": 5, "treasure": 5, "block_post": 5, "push_ups": 5,
        "burnt_tire": 5, "passanger_distance": 5, "time": 5, "race_win": 5,
    },
    "race_win": 5000, "level": 120, "score": 999.0, "batches": [5, 15, 25, 45, 60, 120],
}

# ================================================================
# RENDER HEALTH SERVER
# ================================================================
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
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ================================================================
# SECURITY & PERSISTENCE
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

def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
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
# CRYPTO ENGINE
# ================================================================
class Crypto:
    def __init__(self, uid):
        self.uid = uid
        self.key = (uid[:8] + KEY_ADD).encode()[:16]
        self.iv = (uid[:8] + IV_ADD).encode()[:16]
    def encrypt(self, s):
        return base64.b64encode(AES.new(self.key, AES.MODE_CBC, self.iv).encrypt(pad(s.encode(), 16))).decode()
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
            for key in ['coins', 'value', 'coin', 'amount', 'data']:
                if key in data:
                    val = self.extract_value(data[key])
                    if val is not None: return val
        return None

def gen_device_id(): return MARKO_DEVICE_PREFIX + ''.join(random.choice('0123456789abcdef') for _ in range(28))

def phoenix_headers(token):
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=utf-8",
        "X-Unity-Version": "2022.3.62f2",
        "Authorization": f"Bearer {token}",
        "X-Client-Hash": CLIENT_HASH,
        "X-Phoenix-Signature": MARKO_SIGNATURE,
        "X-Phoenix-Version": MARKO_VERSION,
        "X-Phoenix-Developer": DEVELOPER,
    }

def ogames_headers(token, device_id):
    return {
        "X-Firebase-Token": token,
        "X-Client-Platform": "ANDROID",
        "X-Client-Version": VERSION,
        "X-Client-DeviceId": device_id,
        "X-Api-Key": OG_KEY,
        "X-Client-Env": "prod",
        "X-Bundle-Id": BUNDLE_ID,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Client-Hash": CLIENT_HASH,
        "X-Phoenix-Tag": MARKO_SIGNATURE,
        "X-Phoenix-Developer": DEVELOPER,
    }

# ================================================================
# ASYNC API FUNCTIONS
# ================================================================
async def phoenix_login(email, password, session):
    try:
        async with session.post(FB_LOGIN, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20) as response:
            data = await response.json()
            if "idToken" in data: return {"token": data["idToken"], "uid": data["localId"]}
    except: pass
    return None

async def phoenix_start_session(token, uid, session):
    device_id = gen_device_id()
    oh = ogames_headers(token, device_id)
    try:
        await session.get(f"{OG_BASE}/check-service/v1/hash/check", headers=oh, timeout=15)
        await session.post(f"{OG_BASE}/check-service/v1/session/start", headers=oh, json={}, timeout=15)
    except: pass

    try:
        await session.post(f"{CF_BASE}/MasterMainStartup23_1", headers=phoenix_headers(token), json={"data": "0"}, timeout=15)
    except: pass

async def phoenix_get_coins(session, token, uid):
    url = f"{CF_BASE}/GetCoins23_1"
    try:
        async with session.post(url, headers=phoenix_headers(token), json={"data": None}, timeout=20) as response:
            if response.status == 200:
                result = await response.json()
                if "result" in result and isinstance(result["result"], dict) and "data" in result["result"]:
                    crypto = Crypto(uid)
                    decrypted_str = crypto.decrypt(result["result"]["data"])
                    return crypto.extract_value(decrypted_str) or 0
    except: pass
    return 0

async def phoenix_farm_exact_coins(session, token, uid, target_add, status_callback=None):
    crypto = Crypto(uid)
    coins_harvested = 0
    
    # 1. APPLY KING RANK FIRST (Essential for getting coins)
    rank_payload = crypto.encrypt(json.dumps(KING_RATING_RESULT_ALL))
    try:
        await session.post(f"{CF_BASE}/SetUserRating22_1", headers=phoenix_headers(token), json={"data": rank_payload}, timeout=15)
        await session.post(f"{CF_BASE}/ValidateRank23_1", headers=phoenix_headers(token), json={"data": "0"}, timeout=15)
    except: pass

    # Phase 1: Normal Combos
    async def exec_drag_phase1(seq):
        a, b, c = seq
        encrypted = crypto.encrypt(f"{a},{b},{c}")
        try:
            async with session.post(f"{CF_BASE}/SetDragRacing23_1", headers=phoenix_headers(token), json={"data": encrypted}, timeout=20) as response:
                if response.status == 200:
                    result = await response.json()
                    if "result" in result and isinstance(result["result"], dict) and "data" in result["result"]:
                        decrypted = crypto.decrypt(result["result"]["data"])
                        return crypto.extract_value(decrypted) or 0
        except: pass
        return 0

    # Phase 2: High Yield Combos
    async def exec_drag_phase2(combo):
        car, place, gear = combo
        encrypted = crypto.encrypt(f"{car},{place},{gear}")
        try:
            async with session.post(f"{CF_BASE}/SetDragRacing22_1", headers=phoenix_headers(token), json={"data": encrypted}, timeout=20) as response:
                text = await response.text()
                try:
                    parsed = json.loads(text)
                    res = parsed.get("result")
                    if res:
                        arr = []
                        if isinstance(res, str):
                            try:
                                parsed2 = json.loads(res)
                                if isinstance(parsed2, list) and len(parsed2) >= 2: arr = parsed2
                            except: pass
                        elif isinstance(res, list) and len(res) >= 2: arr = res
                        if len(arr) >= 2:
                            decrypted = crypto.decrypt(arr[1]) if isinstance(arr[1], str) else None
                            if decrypted: return int(decrypted)
                except: pass
        except: pass
        return 0

    batch_size = 50
    
    # Run Phase 1
    all_combos_p1 = [(a, b, c) for a in range(10) for b in range(1, 7) for c in range(10)]
    for i in range(0, len(all_combos_p1), batch_size):
        if coins_harvested >= target_add: break
        batch = all_combos_p1[i:i+batch_size]
        results = await asyncio.gather(*[exec_drag_phase1(seq) for seq in batch])
        for c in results:
            if c > 0: coins_harvested += c
        if status_callback: await status_callback(coins_harvested, target_add)
        await asyncio.sleep(0.5)

    # Run Phase 2 (If still not reached target)
    if coins_harvested < target_add:
        all_combos_p2 = [(car, place, gear) for car in range(6) for place in range(1, 4) for gear in range(2)]
        for _ in range(3):  # Loop max 3 times
            if coins_harvested >= target_add: break
            for i in range(0, len(all_combos_p2), batch_size):
                if coins_harvested >= target_add: break
                batch = all_combos_p2[i:i+batch_size]
                results = await asyncio.gather(*[exec_drag_phase2(seq) for seq in batch])
                for c in results:
                    if c > 0: coins_harvested += c
                if status_callback: await status_callback(coins_harvested, target_add)
                await asyncio.sleep(0.5)

    return coins_harvested

# ================================================================
# TELEGRAM UI HELPERS
# ================================================================
def get_main_menu(): return ReplyKeyboardMarkup([["🚀 Start Farming", "📋 My Accounts"]], resize_keyboard=True)

def get_accounts_main_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 View All Accounts", callback_data="view_accounts")],
        [InlineKeyboardButton("✏️ Edit Accounts", callback_data="edit_accounts")]
    ])

def get_edit_accounts_inline():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Accounts", callback_data="add_accounts")],
        [InlineKeyboardButton("🗑 Delete Accounts", callback_data="delete_accounts")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_acc_main")]
    ])

def build_accounts_page(user_id, page=0):
    accounts = get_user_accounts(user_id)
    total_accs = len(accounts)
    total_pages = max(1, (total_accs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_accs = accounts[start_idx:end_idx]

    text = f"📋 **Saved Accounts** (`{total_accs}/{MAX_ACCOUNTS}`)\nPage `{page + 1}/{total_pages}`\n\n"
    if not accounts: text += "_No accounts saved yet._"
    else:
        for idx, acc in enumerate(page_accs, start=start_idx + 1): text += f"`{idx}.` `{acc['email']}:{acc['password']}`\n"

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
    get_user_accounts(update.effective_user.id)
    await update.message.reply_text("🤖 **Welcome to Safe Farming Bot**", reply_markup=get_main_menu(), parse_mode="Markdown")

@admin_only
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🚀 Start Farming":
        await update.message.reply_text("🔑 **Start Safe Farming**\nSend details as `email:password`", parse_mode="Markdown")
        return WAITING_FARM_CREDS
    elif text == "📋 My Accounts":
        await update.message.reply_text("📋 **My Accounts Management**", reply_markup=get_accounts_main_inline(), parse_mode="Markdown")
    return ConversationHandler.END

@admin_only
async def process_farming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = update.message.text.strip()
    if ":" not in creds:
        await update.message.reply_text("❌ Invalid format. Send as `email:password`")
        return WAITING_FARM_CREDS

    email, password = creds.split(":", 1)
    status_msg = await update.message.reply_text("🔑 Authenticating...", parse_mode="Markdown")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        auth = await phoenix_login(email, password, session)
        if not auth:
            await status_msg.edit_text("❌ **Authentication Failed!**")
            return ConversationHandler.END

        token, uid = auth["token"], auth["uid"]
        
        await status_msg.edit_text("⚡ Initiating Safe Server Bypass...", parse_mode="Markdown")
        await phoenix_start_session(token, uid, session)
        
        current_coins = await phoenix_get_coins(session, token, uid)
        
        last_update_time = time.time()
        async def update_progress(harvested, target):
            nonlocal last_update_time
            if time.time() - last_update_time > 2.0:  
                try:
                    await status_msg.edit_text(
                        f"⚡ Farming {target} coins via Safe API...\n"
                        f"(Previous Balance: `{current_coins:,}`)\n\n"
                        f"Progress: `{harvested} / {target}` 🪙", 
                        parse_mode="Markdown"
                    )
                    last_update_time = time.time()
                except: pass

        await status_msg.edit_text(f"🚜 Starting to farm {COINS_TO_ADD} Coins...")
        farmed = await phoenix_farm_exact_coins(session, token, uid, COINS_TO_ADD, update_progress)
        final_coins = await phoenix_get_coins(session, token, uid)

        result_text = (
            "✅ **Farming Completed Successfully!**\n\n"
            f"• **Account**: `{email}`\n"
            f"• **Previous Balance**: `{current_coins:,}`\n"
            f"• **Coins Added**: `{farmed:,}` 🪙\n"
            f"• **Final Balance**: `{final_coins:,}`"
        )
        await status_msg.edit_text(result_text, parse_mode="Markdown")

    return ConversationHandler.END

@admin_only
async def handle_inline_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    await query.answer()

    if data == "back_to_acc_main":
        await query.edit_message_text("📋 **My Accounts**", reply_markup=get_accounts_main_inline(), parse_mode="Markdown")
    elif data == "view_accounts":
        msg_text, reply_markup = build_accounts_page(user_id, page=0)
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif data == "edit_accounts":
        await query.edit_message_text("✏️ **Edit Accounts**", reply_markup=get_edit_accounts_inline(), parse_mode="Markdown")
    elif data.startswith("acc_page_"):
        page = int(data.split("_")[-1])
        msg_text, reply_markup = build_accounts_page(user_id, page=page)
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif data == "add_accounts":
        await query.message.reply_text("📥 **Add Accounts**\nSend in `email:password` format:", parse_mode="Markdown")
        return WAITING_ADD_ACCOUNTS
    elif data == "delete_accounts":
        await query.message.reply_text("🗑 **Delete Accounts**\nSend in `email:password` format:", parse_mode="Markdown")
        return WAITING_DELETE_ACCOUNTS

@admin_only
async def process_add_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split("\n")
    accounts = get_user_accounts(user_id)
    added = 0
    for line in lines:
        if ":" in line:
            email, password = line.strip().split(":", 1)
            if not any(a["email"] == email.strip() for a in accounts) and len(accounts) < MAX_ACCOUNTS:
                accounts.append({"email": email.strip(), "password": password.strip()})
                added += 1
    ACCOUNTS_DB[str(user_id)] = accounts
    save_accounts(ACCOUNTS_DB)
    await update.message.reply_text(f"✅ Saved {added} accounts!", reply_markup=get_main_menu())
    return ConversationHandler.END

@admin_only
async def process_delete_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split("\n")
    accounts = get_user_accounts(user_id)
    targets = {line.split(":", 1)[0].strip() if ":" in line else line.strip() for line in lines}
    updated = [a for a in accounts if a["email"] not in targets]
    ACCOUNTS_DB[str(user_id)] = updated
    save_accounts(ACCOUNTS_DB)
    await update.message.reply_text(f"🗑 Deleted {len(accounts) - len(updated)} accounts!", reply_markup=get_main_menu())
    return ConversationHandler.END

@admin_only
async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Canceled.", reply_markup=get_main_menu())
    return ConversationHandler.END

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
        fallbacks=[CommandHandler("cancel", cancel_handler), MessageHandler(filters.TEXT, handle_menu)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_inline_buttons))
    app.add_handler(MessageHandler(filters.TEXT, handle_menu))
    app.run_polling()

if __name__ == "__main__":
    main()
