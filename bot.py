import os, asyncio, sqlite3, urllib.parse, secrets, logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURAÇÕES ---
logging.basicConfig(level=logging.INFO)
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389 
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")
DB_PATH = "venda_plus.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- INICIALIZAÇÃO SEGURA DO BANCO ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY, premium INTEGER DEFAULT 0, webhook_token TEXT UNIQUE,
        vendas_recuperadas INTEGER DEFAULT 0, total_leads INTEGER DEFAULT 0,
        expires_at TEXT, trial_used INTEGER DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, phone TEXT, name TEXT, 
        due TEXT, product TEXT, status TEXT DEFAULT 'pending')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS conversion_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, type TEXT, created_at DATE DEFAULT (DATE('now')))""")
    conn.commit()
    conn.close()

init_db()

def get_user(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT premium, expires_at FROM users WHERE chat_id=?", (chat_id,))
        return cursor.fetchone()

def is_premium(chat_id):
    user = get_user(chat_id)
    if not user or user[0] == 0: return False
    if user[1] and datetime.now() > datetime.strptime(user[1], "%Y-%m-%d"):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE users SET premium = 0 WHERE chat_id=?", (chat_id,))
        return False
    return True

# --- MOTOR DE AGENDAMENTO ---
async def main_scheduler():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE due <= ? AND status='pending'", (now,))
                for r in cursor.fetchall():
                    rid, cid, phone, name, due, prod, status = r
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote(f'Olá {name}, vi seu interesse no {prod}... ok?')}"
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📲 Recuperar", url=link)], [InlineKeyboardButton(text="💰 Venda Feita", callback_data=f"win_{rid}")]])
                    await bot.send_message(cid, f"⏰ *FOLLOW-UP:* {name}\n📦 {prod}", reply_markup=kb, parse_mode="Markdown")
                    cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
        except Exception as e: logging.error(f"Erro Scheduler: {e}")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(main_scheduler())
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot")
    yield

app = FastAPI(lifespan=lifespan)

# --- WEBHOOKS ---
@app.get("/webhook/{token}")
async def validate(token: str, code: str = None, challenge: str = None):
    return code or challenge or {"status": "ok"}

@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,))
        user = cursor.fetchone()
        if not user or not is_premium(user[0]): return {"error": "unauthorized"}
        
        cid = user[0]
        name = data.get("customer_name") or data.get("name") or "Cliente"
        phone = str(data.get("phone") or data.get("customer_mobile") or "").replace("+", "").replace(" ", "")
        prod = data.get("product_name") or data.get("product") or "Produto"
        status = str(data.get("order_status") or data.get("status")).upper()

        if status in ["PAID", "APPROVED"]:
            await bot.send_message(cid, f"✅ *VENDA:* {name}")
        elif status in ["PENDING", "WAITING_PAYMENT", "UNPAID"]:
            due = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?,?,?,?,?)", (cid, phone, name, due, prod))
            cursor.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,))
            await bot.send_message(cid, f"🎯 *LEAD:* {name}\nFollow-up em 30 min.")
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS ---
@dp.message(Command("start"))
async def cmd_start(m: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT webhook_token, expires_at, premium FROM users WHERE chat_id=?", (m.chat.id,))
        row = cursor.fetchone()
        if not row:
            token, exp = secrets.token_hex(8), (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            cursor.execute("INSERT INTO users (chat_id, webhook_token, premium, expires_at, trial_used) VALUES (?,?,1,?,1)", (m.chat.id, token, exp))
            conn.commit()
            await m.answer(f"🎁 *TESTE 3 DIAS ATIVO!*\nExpira: {exp}", parse_mode="Markdown")
            row = (token, exp, 1)
    
    if is_premium(m.chat.id):
        await m.answer(f"💎 *VIP ATIVO*\nExpira: {row[1]}\nURL: `https://{BASE_URL}/webhook/{row[0]}`", parse_mode="Markdown")
    else:
        await m.answer(f"❌ *EXPIRADO*\nID: `{m.chat.id}`", parse_mode="Markdown")

@dp.message(Command("liberar"))
async def cmd_liberar(m: Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        parts = m.text.split()
        tid, days = int(parts[1]), int(parts[2])
        exp = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE users SET premium=1, expires_at=? WHERE chat_id=?", (exp, tid))
        await m.answer(f"✅ ID {tid} liberado por {days} dias!")
        await bot.send_message(tid, f"🔥 *VIP LIBERADO!* Expira em: {exp}")
    except: await m.answer("Use: `/liberar ID DIAS`")

@dp.message(Command("dashboard"))
async def cmd_dash(m: Message):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
    if res:
        await m.answer(f"📊 *STATUS*\nLeads: {res[0]}\nRecuperadas: {res[1]}", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("win_"))
async def win(cb: types.CallbackQuery):
    rid = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,))
        conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
    await cb.message.edit_text("💰 *SALVA!*")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
