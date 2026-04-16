import os
import asyncio
import sqlite3
import urllib.parse
import secrets
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Query
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

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            premium INTEGER DEFAULT 0,
            webhook_token TEXT UNIQUE,
            vendas_recuperadas INTEGER DEFAULT 0,
            total_leads INTEGER DEFAULT 0,
            expires_at TEXT,
            trial_used INTEGER DEFAULT 0
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER, phone TEXT, name TEXT, due TEXT, product TEXT, 
            status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # Tabela para histórico de conversão (Relatório Semanal)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            type TEXT, -- 'lead' ou 'sale'
            created_at DATE DEFAULT (DATE('now'))
        )""")
        conn.commit()

init_db()

# --- HELPER: VALIDAÇÃO DE ASSINATURA ---
def is_premium(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT premium, expires_at FROM users WHERE chat_id=?", (chat_id,))
        row = cursor.fetchone()
        if not row: return False
        premium, expires_at = row
        if premium == 0: return False
        if expires_at and datetime.now() > datetime.strptime(expires_at, "%Y-%m-%d"):
            cursor.execute("UPDATE users SET premium = 0 WHERE chat_id=?", (chat_id,))
            conn.commit()
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
                expired = cursor.fetchall()
                for r in expired:
                    rid, chat_id, phone, name, due, product, status, c_at = r
                    copy = f"Olá {name}! Notei que seu pedido do {product} está aguardando pagamento. Posso te ajudar a finalizar para você não perder a oferta?"
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote(copy)}"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📲 Recuperar via WhatsApp", url=link)],
                        [InlineKeyboardButton(text="💰 Venda Confirmada", callback_data=f"win_{rid}")]
                    ])
                    await bot.send_message(chat_id, f"⏰ *HORA DO FOLLOW-UP!*\n\n👤 Cliente: *{name}*\n📦 Produto: *{product}*\n\nNão deixe esse dinheiro escapar!", reply_markup=kb, parse_mode="Markdown")
                    cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
        except Exception as e: logging.error(f"Erro no Scheduler: {e}")
        await asyncio.sleep(40)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(main_scheduler())
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot")
    yield
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

# --- ROTAS DE VALIDAÇÃO E WEBHOOK ---

# Rota GET: Validação automática (TikTok, Shopee, etc.)
@app.get("/webhook/{token}")
async def validate_webhook(token: str, code: str = None, challenge: str = None):
    # TikTok usa 'code', Shopee pode usar 'challenge' ou assinatura
    if code: return code
    if challenge: return challenge
    return {"status": "Webhook Ativo", "token": token}

# Rota POST: Recebimento de Leads
@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,))
        user = cursor.fetchone()
        if not user or not is_premium(user[0]): raise HTTPException(status_code=403)
        
        chat_id = user[0]
        name = data.get("customer_name") or data.get("name") or data.get("full_name") or "Cliente"
        phone = str(data.get("phone") or data.get("customer_mobile") or "").replace("+", "").replace(" ", "")
        product = data.get("product_name") or data.get("product") or "Produto"
        status = str(data.get("order_status") or data.get("status")).upper()

        # Lógica de Notificação e Log
        if status in ["PAID", "APPROVED", "COMPLETED"]:
            cursor.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'sale')", (chat_id,))
            await bot.send_message(chat_id, f"✅ *VENDA APROVADA!* 🎉\n👤 {name}\n📦 {product}", parse_mode="Markdown")
        
        elif status in ["PENDING", "UNPAID", "WAITING_PAYMENT", "BILLET_PRINTED"]:
            due_time = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?, ?, ?, ?, ?)", (chat_id, phone, name, due_time, product))
            cursor.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'lead')", (chat_id,))
            cursor.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (chat_id,))
            await bot.send_message(chat_id, f"🎯 *NOVO LEAD (CARRINHO):* {name}\n📦 {product}\n\nAgendado para 30 min!", parse_mode="Markdown")
        
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook_handler(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# --- COMANDOS DO TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT webhook_token, expires_at FROM users WHERE chat_id=?", (chat_id,))
        row = cursor.fetchone()
        
        if not row:
            token = secrets.token_hex(8)
            expiry = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            cursor.execute("INSERT INTO users (chat_id, webhook_token, premium, expires_at, trial_used) VALUES (?, ?, 1, ?, 1)", (chat_id, token, expiry))
            conn.commit()
            await message.answer(f"🎁 *TESTE GRÁTIS ATIVADO!* Você tem 3 dias de acesso VIP.\nExpira em: `{expiry}`", parse_mode="Markdown")
            webhook_token, expires_at = token, expiry
        else:
            webhook_token, expires_at = row

    if not is_premium(chat_id):
        await message.answer(f"❌ *ACESSO EXPIRADO!*\n🆔 ID: `{chat_id}`\nRenove sua licença agora!", parse_mode="Markdown")
    else:
        url = f"https://{BASE_URL}/webhook/{webhook_token}"
        await message.answer(f"💎 *VENDA+.BOT ENTERPRISE*\n📅 Vence: `{expires_at}`\n🔗 URL: `{url}`\n\n📊 `/dashboard` | 📑 `/relatorio`", parse_mode="Markdown")

@dp.message(Command("relatorio"))
async def cmd_relatorio(message: Message):
    if not is_premium(message.chat.id): return
    
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, COUNT(*) FROM conversion_log WHERE chat_id=? AND created_at >= ? GROUP BY type", (message.chat.id, seven_days_ago))
        stats = dict(cursor.fetchall())
    
    leads = stats.get('lead', 0)
    sales = stats.get('sale', 0)
    conv = (sales / leads * 100) if leads > 0 else 0
    
    report = (
        f"📑 *RELATÓRIO SEMANAL (Últimos 7 dias)*\n\n"
        f"🎯 *Leads Capturados:* {leads}\n"
        f"💰 *Vendas Convertidas:* {sales}\n"
        f"📈 *Taxa de Sucesso:* {conv:.1f}%\n\n"
        f"_{datetime.now().strftime('%d/%m/%Y %H:%M')}_"
    )
    await message.answer(report, parse_mode="Markdown")

@dp.message(Command("liberar"))
async def cmd_liberar(message: Message):
    if message.from_user.id != ADMIN_ID: return 
    try:
        p = message.text.split()
        tid, days = int(p[1]), int(p[2])
        expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET premium = 1, expires_at = ? WHERE chat_id = ?", (expiry, tid))
            conn.commit()
        await message.answer(f"✅ ID `{tid}` liberado até {expiry}!")
    except: await message.answer("Use: `/liberar ID DIAS`")

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    if not is_premium(message.chat.id): return
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (message.chat.id,))
        s = cursor.fetchone()
    c = (s[1]/s[0]*100) if s[0] > 0 else 0
    await message.answer(f"📊 *DASHBOARD GERAL*\n\n🔥 Total Leads: {s[0]}\n💰 Recuperadas: {s[1]}\n📈 Conversão: {c:.1f}%", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("win_"))
async def mark_win(callback: types.CallbackQuery):
    if not is_premium(callback.from_user.id): return
    rid = callback.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (callback.from_user.id,))
        cursor.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'sale')", (callback.from_user.id,))
        cursor.execute("DELETE FROM reminders WHERE id=?", (rid,))
        conn.commit()
    await callback.message.edit_text("💰 *VENDA SALVA COM SUCESSO!*", parse_mode="Markdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
