import os
import asyncio
import sqlite3
import urllib.parse
import secrets
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# --- CONFIGURAÇÕES DE AMBIENTE ---
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389
# O Railway define RAILWAY_STATIC_URL automaticamente
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "seu-app.up.railway.app")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

# --- BANCO DE DADOS (Persistência de Elite) ---
DB_PATH = "zapfollow_pro.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
        platform TEXT,
        status TEXT DEFAULT 'pending'
    )""")
    conn.commit()
    conn.close()

init_db()

# --- NÚCLEO DE RECEPÇÃO (WEBHOOKS) ---

@app.post("/webhook/{token}")
async def dynamic_webhook(token: str, request: Request):
    data = await request.json()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=404)

    chat_id = user[0]
    
    # Normalização de Dados (Aceita Kiwify, Hotmart e outros)
    name = data.get("customer_name") or data.get("name") or "Lead"
    phone = str(data.get("customer_mobile") or data.get("phone") or "").replace("+", "").replace(" ", "")
    product = data.get("product_name") or data.get("product") or "Infoproduto"
    status = data.get("order_status") or data.get("status")

    # Gatilhos de Follow-up (Boleto/Pix)
    if status in ["waiting_payment", "pending", "status_pending", "billet_printed"]:
        due_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        
        cursor.execute(
            "INSERT INTO reminders (chat_id, phone, name, due, product, platform) VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, phone, name, due_time, product, "Plataforma Digital")
        )
        cursor.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (chat_id,))
        conn.commit()

        await bot.send_message(
            chat_id,
            f"🎯 *Novo Lead Detectado!*\n\n👤 *Nome:* {name}\n📦 *Produto:* {product}\n📱 *Zap:* `{phone}`\n\n"
            "⏰ Vou te avisar em 1 hora para você não deixar o lead esfriar!",
            parse_mode="Markdown"
        )

    conn.close()
    return {"status": "ok"}

# --- INTERFACE DO TELEGRAM ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT webhook_token FROM users WHERE chat_id=?", (chat_id,))
    row = cursor.fetchone()
    
    if not row:
        token = secrets.token_hex(8)
        cursor.execute("INSERT INTO users (chat_id, webhook_token, total_leads, vendas_recuperadas) VALUES (?, ?, 0, 0)", (chat_id, token))
        conn.commit()
    else:
        token = row[0]
    conn.close()
    
    url = f"https://{BASE_URL}/webhook/{token}"
    text = (
        "✨ *ZapFollow Enterprise v2026*\n\n"
        "Seu Webhook Universal para Kiwify/Hotmart:\n"
        f"`{url}`\n\n"
        "📊 `/dashboard` - Ver suas métricas\n"
        "📋 `/lista` - Leads pendentes\n"
        "💎 `/assinar` - Plano Ilimitado"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (message.chat.id,))
    stats = cursor.fetchone()
    conn.close()

    if stats:
        conv = (stats[1]/stats[0]*100) if stats[0] > 0 else 0
        text = (
            "📊 *Seu Painel de Performance*\n\n"
            f"🔥 *Leads Capturados:* {stats[0]}\n"
            f"💰 *Vendas Recuperadas:* {stats[1]}\n"
            f"📈 *Taxa de Conversão:* {conv:.1f}%"
        )
        await message.answer(text, parse_mode="Markdown")

@dp.message(Command("lista"))
async def cmd_lista(message: Message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, product, due, id FROM reminders WHERE chat_id=? AND status='pending' ORDER BY due ASC", (message.chat.id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return await message.answer("📭 Sem leads pendentes.")

    lista = "📋 *Leads Aguardando Follow-up:*\n\n"
    for r in rows:
        lista += f"🔹 *{r[0]}* - {r[1]} ({r[2]})\n"
    await message.answer(lista, parse_mode="Markdown")

# --- LÓGICA DE MARCAR VENDA (ROI) ---

@dp.callback_query(F.data.startswith("win_"))
async def mark_win(callback: types.CallbackQuery):
    reminder_id = callback.data.split("_")[1]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (callback.from_user.id,))
    cursor.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("✅ *Venda marcada com sucesso! Parabéns!* 🎉", parse_mode="Markdown")

# --- MOTOR DE AGENDAMENTO (SCHEDULER) ---

async def main_scheduler():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reminders WHERE due <= ? AND status='pending'", (now,))
            expired = cursor.fetchall()

            for r in expired:
                rid, chat_id, phone, name, due, product, platform, status = r
                copy = f"Olá {name}! Notei que você iniciou a inscrição para o {product} mas não concluiu. Ficou com alguma dúvida?"
                link = f"https://wa.me/{phone}?text={urllib.parse.quote(copy)}"
                
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Chamar no WhatsApp", url=link)],
                    [InlineKeyboardButton(text="💰 Marcar como Vendido", callback_data=f"win_{rid}")]
                ])

                await bot.send_message(chat_id, f"⏰ *HORA DO FOLLOW-UP!*\n\nCliente: *{name}*\nProduto: *{product}*", reply_markup=kb, parse_mode="Markdown")
                cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
            conn.close()
        except Exception as e:
            print(f"Erro: {e}")
        await asyncio.sleep(40)

# --- STARTUP INTEGRADO ---

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(main_scheduler())
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot")

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}


