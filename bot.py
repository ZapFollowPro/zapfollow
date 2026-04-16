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
                    
                    # Mensagem corrigida (sem conflito de aspas)
                    copy = (
                        f"Olá {name}, tudo bem? Vi que você selecionou o {product}, mas o sistema ainda não reconheceu o pagamento. "
                        "Separei sua unidade aqui, mas como a procura está alta, não consigo segurar por muito tempo. "
                        "Precisa de ajuda com o Pix ou boleto?"
                    )
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote(copy)}"
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📲 Recuperar Venda Agora", url=link)],
                        [InlineKeyboardButton(text="💰 Dinheiro no Bolso", callback_data=f"win_{rid}")]
                    ])

                    await bot.send_message(
                        chat_id, 
                        f"⚠️ *ALERTA DE DINHEIRO NA MESA!*\n\n"
                        f"👤 Cliente: *{name}*\n"
                        f"📦 Produto: *{product}*\n\n"
                        f"O lead já está 'aquecido'. Clique abaixo para finalizar a venda antes que ele desista!", 
                        reply_markup=kb, 
                        parse_mode="Markdown"
                    )
                    cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
        except Exception as e:
            logging.error(f"Erro no Scheduler: {e}")
        await asyncio.sleep(40)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(main_scheduler())
    webhook_url = f"https://{BASE_URL}/tg-bot"
    await bot.set_webhook(url=webhook_url)
    yield
    await bot.delete_webhook()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

# --- ROTAS WEBHOOK ---

@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, premium FROM users WHERE webhook_token=?", (token,))
        user = cursor.fetchone()
        
        if not user or user[1] == 0:
            raise HTTPException(status_code=403)

        chat_id = user[0]
        name = data.get("customer_name") or data.get("name") or "Cliente"
        phone = str(data.get("customer_mobile") or data.get("phone") or "").replace("+", "").replace(" ", "")
        product = data.get("product_name") or data.get("product") or "Seu Produto"
        status = data.get("order_status") or data.get("status")

        if status in ["waiting_payment", "pending", "billet_printed", "started"]:
            due_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            cursor.execute(
                "INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?, ?, ?, ?, ?)",
                (chat_id, phone, name, due_time, product)
            )
            cursor.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (chat_id,))
            conn.commit()

            await bot.send_message(
                chat_id,
                f"🎯 *NOVO LEAD CAPTURADO!*\n\n"
                f"👤 *Nome:* {name}\n"
                f"📦 *Item:* {product}\n\n"
                "🔥 O sistema agendou um follow-up estratégico para daqui a 60 minutos. Prepare o bolso!",
                parse_mode="Markdown"
            )
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
        cursor.execute("SELECT webhook_token, premium FROM users WHERE chat_id=?", (chat_id,))
        row = cursor.fetchone()
        
        if not row:
            token = secrets.token_hex(8)
            cursor.execute("INSERT INTO users (chat_id, webhook_token, premium, total_leads, vendas_recuperadas) VALUES (?, ?, 0, 0, 0)", (chat_id, token))
            conn.commit()
            premium, webhook_token = 0, token
        else:
            webhook_token, premium = row

    if premium == 0:
        await message.answer(
            "🚀 *BEM-VINDO À ELITE DA RECUPERAÇÃO!*\n\n"
            "Você acaba de dar o primeiro passo para parar de perder vendas por falta de acompanhamento.\n\n"
            f"🆔 *Seu Token de Acesso:* `{chat_id}`\n\n"
            "⚠️ *LICENÇA PENDENTE:* Sua conta ainda não foi ativada. Envie seu Token para o suporte para liberar o sistema agora!",
            parse_mode="Markdown"
        )
    else:
        url = f"https://{BASE_URL}/webhook/{webhook_token}"
        await message.answer(
            "💎 *VENDA+.BOT ENTERPRISE ATIVO!*\n\n"
            "Seu sistema está operando em força total. Conecte o link abaixo na sua plataforma:\n\n"
            f"🔗 *URL DE INTEGRAÇÃO:* \n`{url}`\n\n"
            "📈 Use o `/dashboard` para monitorar seu lucro crescer.",
            parse_mode="Markdown"
        )

@dp.message(Command("liberar"))
async def cmd_liberar(message: Message):
    if message.from_user.id != ADMIN_ID:
        return 

    try:
        target_id = int(message.text.split()[1])
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET premium = 1 WHERE chat_id = ?", (target_id,))
            conn.commit()
        
        await message.answer(f"✅ Conta `{target_id}` ativada com sucesso!")
        await bot.send_message(target_id, "🔥 *BOAS NOTÍCIAS!* Sua licença foi ativada. Use o /start e comece a escalar suas vendas agora mesmo!")
    except:
        await message.answer("❌ Use: `/liberar ID`")

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_leads, vendas_recuperadas, premium FROM users WHERE chat_id=?", (message.chat.id,))
        stats = cursor.fetchone()
    
    if stats and stats[2] == 1:
        conv = (stats[1]/stats[0]*100) if stats[0] > 0 else 0
        await message.answer(
            "📊 *RELATÓRIO DE PERFORMANCE*\n\n"
            f"🔥 *Leads Monitorados:* {stats[0]}\n"
            f"💰 *Vendas Salvas:* {stats[1]}\n"
            f"📈 *Taxa de Recuperação:* {conv:.1f}%\n\n"
            "Continue fazendo o follow-up, cada lead é uma oportunidade de lucro!",
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
    await callback.message.edit_text("💰 *PROCESSO FINALIZADO!* Mais uma venda garantida para a conta. Parabéns!", parse_mode="Markdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
