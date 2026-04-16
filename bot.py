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

# --- BANCO DE DATOS ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Tabela de Usuários com trial e validade
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
        # Tabela de Notificações Agendadas
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER, phone TEXT, name TEXT, due TEXT, product TEXT, 
            status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # Log para Relatórios Semanais
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            type TEXT, -- 'lead' ou 'sale'
            created_at DATE DEFAULT (DATE('now'))
        )""")
        conn.commit()

init_db()

# --- FUNÇÕES DE APOIO ---
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

# --- SCHEDULER: ENVIO DE FOLLOW-UP ---
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
                    msg_wa = f"Olá {name}! Notei seu interesse no {product}, mas o pedido ainda não foi confirmado. Separei uma unidade para você, mas a procura está alta. Posso te ajudar com o Pix ou Boleto?"
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote(msg_wa)}"
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📲 Recuperar via WhatsApp", url=link)],
                        [InlineKeyboardButton(text="💰 Venda Confirmada", callback_data=f"win_{rid}")]
                    ])
                    
                    await bot.send_message(
                        chat_id, 
                        f"⏰ *HORA DE RECUPERAR!*\n\n👤 Cliente: *{name}*\n📦 Produto: *{product}*\n\nO lead está pronto para o contato. Não deixe esse dinheiro na mesa!", 
                        reply_markup=kb, parse_mode="Markdown"
                    )
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

# --- ROTAS WEBHOOK (VALIDAÇÃO E DADOS) ---

@app.get("/webhook/{token}")
async def validate_webhook(token: str, code: str = None, challenge: str = None):
    # Handshake automático para TikTok Shop (code) e Shopee (challenge)
    if code: return code
    if challenge: return challenge
    return {"status": "Webhook Ativo", "token": token}

@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,))
        user = cursor.fetchone()
        if not user or not is_premium(user[0]): raise HTTPException(status_code=403)
        
        chat_id = user[0]
        # Tradutor Universal de Plataformas
        name = data.get("customer_name") or data.get("name") or data.get("full_name") or data.get("buyer_user_id") or "Cliente"
        phone = str(data.get("phone") or data.get("customer_mobile") or data.get("mobile") or "").replace("+", "").replace(" ", "")
        product = data.get("product_name") or data.get("product") or data.get("item_list", [{}])[0].get("item_name", "Produto")
        status = str(data.get("order_status") or data.get("status") or data.get("purchase_status")).upper()

        if status in ["PAID", "APPROVED", "COMPLETED", "READY_TO_SHIP"]:
            cursor.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'sale')", (chat_id,))
            await bot.send_message(chat_id, f"✅ *VENDA APROVADA!* 🤑\n👤 {name}\n📦 {product}", parse_mode="Markdown")
        
        elif status in ["PENDING", "UNPAID", "WAITING_PAYMENT", "BILLET_PRINTED", "IN_CHECKOUT"]:
            due_time = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?, ?, ?, ?, ?)", (chat_id, phone, name, due_time, product))
            cursor.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'lead')", (chat_id,))
            cursor.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (chat_id,))
            await bot.send_message(chat_id, f"🎯 *CARRINHO CAPTURADO:* {name}\n📦 {product}\n\nAgendei o follow-up para daqui a 30 min!", parse_mode="Markdown")
        
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook_handler(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# --- COMANDOS OPERACIONAIS ---

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
            await message.answer(f"🎁 *PRESENTÃO DE BOAS-VINDAS!*\n\nVocê ganhou *3 DIAS VIP* para testar o sistema!\nSua licença expira em: `{expiry}`", parse_mode="Markdown")
            webhook_token, expires_at = token, expiry
        else:
            webhook_token, expires_at = row

    if not is_premium(chat_id):
        await message.answer(f"❌ *SISTEMA BLOQUEADO*\n\nSua licença expirou em: `{expires_at}`\n🆔 Seu ID para renovação: `{chat_id}`", parse_mode="Markdown")
    else:
        url = f"https://{BASE_URL}/webhook/{webhook_token}"
        await message.answer(
            f"💎 *VENDA+.BOT ATIVO*\n\n"
            f"📅 Vencimento: `{expires_at}`\n"
            f"🔗 URL Webhook: `{url}`\n\n"
            f"📊 `/dashboard` | 📑 `/relatorio`", 
            parse_mode="Markdown"
        )

@dp.message(Command("relatorio"))
async def cmd_relatorio(message: Message):
    if not is_premium(message.chat.id): return
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, COUNT(*) FROM conversion_log WHERE chat_id=? AND created_at >= ? GROUP BY type", (message.chat.id, seven_days_ago))
        stats = dict(cursor.fetchall())
    
    leads, sales = stats.get('lead', 0), stats.get('sale', 0)
    conv = (sales / leads * 100) if leads > 0 else 0
    await message.answer(f"📑 *BALANÇO SEMANAL*\n\n🎯 Leads: {leads}\n💰 Vendas: {sales}\n📈 Sucesso: {conv:.1f}%", parse_mode="Markdown")

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    if not is_premium(message.chat.id): return
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (message.chat.id,))
        s = cursor.fetchone()
    c = (s[1]/s[0]*100) if s[0] > 0 else 0
    await message.answer(f"📊 *PERFORMANCE TOTAL*\n\n🔥 Total Leads: {s[0]}\n💰 Recuperadas: {s[1]}\n📈 Conversão: {c:.1f}%", parse_mode="Markdown")

@dp.message(Command("liberar"))
async def cmd_liberar(message: Message):
    if message.from_user.id != ADMIN_ID: return 
    try:
        parts = message.text.split()
        tid, days = int(parts[1]), int(parts[2])
        expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET premium = 1, expires_at = ? WHERE chat_id = ?", (expiry, tid))
            conn.commit()
        await message.answer(f"✅ ID `{tid}` liberado por {days} dias!")
        await bot.send_message(tid, f"🔥 *ACESSO VIP LIBERADO!* Válido até {expiry}.")
    except: await message.answer("❌ Use: `/liberar ID DIAS`")

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
    await callback.message.edit_text("💰 *MÁQUINA DE VENDAS!* Registro atualizado.", parse_mode="Markdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
