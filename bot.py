import os
import asyncio
import sqlite3
import urllib.parse
import secrets
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURAÇÕES DE LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- CONSTANTES ---
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")

DB_PATH = "zapfollow_pro.db"

# --- INICIALIZAÇÃO DO BOT ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- CAMADA DE BANCO DE DADOS ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            premium INTEGER DEFAULT 0,
            webhook_token TEXT UNIQUE,
            vendas_recuperadas INTEGER DEFAULT 0,
            total_leads INTEGER DEFAULT 0
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            phone TEXT,
            name TEXT,
            due TEXT,
            product TEXT,
            status TEXT DEFAULT 'pending'
        )""")
        conn.commit()

init_db()

# --- MOTOR DE AGENDAMENTO (SCHEDULER) ---
async def main_scheduler():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE due <= ? AND status='pending'", (now,))
                expired = cursor.fetchall()

                for r in expired:
                    rid, chat_id, phone, name, due, product, status = r
                    
                    # Mensagem de alta conversão
                    copy = f"Olá {name}! Vi que você iniciou o pedido do {product}, mas o pagamento ainda não consta aqui. Posso te ajudar a finalizar?"
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote(copy)}"
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Chamar no WhatsApp", url=link)],
                        [InlineKeyboardButton(text="💰 Marcar como Vendido", callback_data=f"win_{rid}")]
                    ])

                    await bot.send_message(
                        chat_id, 
                        f"⏰ *HORA DO FOLLOW-UP!*\n\n👤 Cliente: *{name}*\n📦 Produto: *{product}*", 
                        reply_markup=kb, 
                        parse_mode="Markdown"
                    )
                    cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
        except Exception as e:
            logger.error(f"Erro no Scheduler: {e}")
        await asyncio.sleep(30)

# --- LIFESPAN (GERENCIAMENTO DE INÍCIO E FIM) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    asyncio.create_task(main_scheduler())
    webhook_url = f"https://{BASE_URL}/tg-bot"
    await bot.set_webhook(url=webhook_url)
    logger.info(f"Bot Online: {webhook_url}")
    yield
    # Shutdown
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Bot Offline.")

app = FastAPI(lifespan=lifespan)

# --- ROTAS WEBHOOK (PLATAFORMAS E TELEGRAM) ---

@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=404)

        chat_id = user[0]
        name = data.get("customer_name") or data.get("name") or "Lead"
        phone = str(data.get("customer_mobile") or data.get("phone") or "").replace("+", "").replace(" ", "")
        product = data.get("product_name") or data.get("product") or "Produto Digital"
        status = data.get("order_status") or data.get("status")

        # Filtro de status pendente
        if status in ["waiting_payment", "pending", "billet_printed"]:
            due_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            cursor.execute(
                "INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?, ?, ?, ?, ?)",
                (chat_id, phone, name, due_time, product)
            )
            cursor.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (chat_id,))
            conn.commit()

            await bot.send_message(
                chat_id,
                f"🎯 *Novo Lead Detectado!*\n\n👤 *Nome:* {name}\n📦 *Produto:* {product}\n\n"
                "⏰ Follow-up agendado para daqui a 1 hora!",
                parse_mode="Markdown"
            )
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook_handler(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# --- HANDLERS DO TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT webhook_token FROM users WHERE chat_id=?", (chat_id,))
        row = cursor.fetchone()
        
        if not row:
            token = secrets.token_hex(8)
            cursor.execute("INSERT INTO users (chat_id, webhook_token, total_leads, vendas_recuperadas) VALUES (?, ?, 0, 0)", (chat_id, token))
            conn.commit()
            webhook_token = token
        else:
            webhook_token = row[0]
    
    url = f"https://{BASE_URL}/webhook/{webhook_token}"
    await message.answer(
        f"✨ *ZapFollow Enterprise*\n\n"
        f"🔗 *Seu Webhook:* \n`{url}`\n\n"
        f"📊 `/dashboard` - Ver resultados\n"
        f"📋 `/lista` - Leads ativos",
        parse_mode="Markdown"
    )

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (message.chat.id,))
        stats = cursor.fetchone()
    
    if stats:
        conv = (stats[1]/stats[0]*100) if stats[0] > 0 else 0
        await message.answer(
            f"📊 *Dashboard de Conversão*\n\n"
            f"🔥 Leads: {stats[0]}\n"
            f"💰 Vendas: {stats[1]}\n"
            f"📈 Taxa: {conv:.1f}%",
            parse_mode="Markdown"
        )

@dp.callback_query(F.data.startswith("win_"))
async def mark_win(callback: types.CallbackQuery):
    reminder_id = callback.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (callback.from_user.id,))
        cursor.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
        conn.commit()
    await callback.message.edit_text("✅ *Venda recuperada! Dinheiro no bolso.* 🎉", parse_mode="Markdown")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)



