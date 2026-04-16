import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURAÇÕES E AMBIENTE ---
logging.basicConfig(level=logging.INFO)
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389 
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")
CHECKOUT_URL = "https://suaplataforma.com/checkout" # Link de pagamento
DB_PATH = "venda_plus.db"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- AUTOMAÇÃO DE BANCO DE DADOS ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # Tabela unificada com suporte a ranking e trial
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY, username TEXT, premium INTEGER DEFAULT 0, 
            webhook_token TEXT UNIQUE, vendas_recuperadas INTEGER DEFAULT 0, 
            total_leads INTEGER DEFAULT 0, expires_at TEXT, trial_used INTEGER DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, phone TEXT, name TEXT, 
            due TEXT, product TEXT, status TEXT DEFAULT 'pending')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS conversion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, type TEXT, created_at DATE DEFAULT (DATE('now')))""")
    logging.info("Sistema de dados automatizado com sucesso.")

init_db()

# --- INTERFACE DE BOTÕES INTUITIVOS ---
def main_keyboard():
    # Substitui a necessidade de digitar comandos
    buttons = [
        [KeyboardButton(text="💎 Meu Painel"), KeyboardButton(text="📊 Dashboard")],
        [KeyboardButton(text="🏆 Ranking"), KeyboardButton(text="📖 Ajuda")],
        [KeyboardButton(text="💳 Renovar Assinatura")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def buy_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Adquirir Acesso VIP", url=CHECKOUT_URL)]
    ])

# --- VALIDAÇÃO DE ACESSO ---
def is_premium(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT premium, expires_at FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        if not row or row[0] == 0: return False
        if row[1] and datetime.now() > datetime.strptime(row[1], "%Y-%m-%d"):
            conn.execute("UPDATE users SET premium = 0 WHERE chat_id=?", (chat_id,))
            return False
        return True

# --- MOTOR DE RECONTATO AUTOMÁTICO ---
async def main_scheduler():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE due <= ? AND status='pending'", (now,))
                for r in cursor.fetchall():
                    rid, cid, phone, name, due, prod, status = r
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote(f'Olá {name}, vi seu interesse no {prod}...')}"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📲 Recuperar via WhatsApp", url=link)],
                        [InlineKeyboardButton(text="💰 Venda Confirmada", callback_data=f"win_{rid}")]
                    ])
                    await bot.send_message(cid, f"⏰ *HORA DO RECONTATO!*\n👤 {name}\n📦 {prod}", reply_markup=kb, parse_mode="Markdown")
                    cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
        except Exception as e: logging.error(f"Erro no Scheduler: {e}")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(main_scheduler())
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot")
    yield

app = FastAPI(lifespan=lifespan)

# --- WEBHOOKS DE INTEGRAÇÃO ---
@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        user = conn.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,)).fetchone()
        if not user or not is_premium(user[0]): return {"error": "blocked"}
        
        cid, name, prod = user[0], (data.get("name") or "Cliente"), (data.get("product") or "Produto")
        status = str(data.get("status") or "").upper()

        if status in ["PAID", "APPROVED"]:
            conn.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'sale')", (cid,))
            await bot.send_message(cid, f"✅ *VENDA REALIZADA:* {name}\n📦 {prod}")
        elif status in ["PENDING", "WAITING"]:
            due = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
            conn.execute("INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?,?,?,?,?)", (cid, "55000", name, due, prod))
            conn.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,))
            await bot.send_message(cid, f"🎯 *LEAD CAPTURADO:* {name}\nAgendado para 30 min.")
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS AUTOMATIZADOS POR BOTÕES ---

@dp.message(Command("start"))
@dp.message(F.text == "💎 Meu Painel")
async def cmd_start(m: Message):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT webhook_token, expires_at FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
        if not row:
            token, exp = secrets.token_hex(8), (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            conn.execute("INSERT INTO users (chat_id, username, webhook_token, premium, expires_at) VALUES (?,?,?,1,?)", (m.chat.id, m.from_user.first_name, token, exp))
            conn.commit()
            row = (token, exp)
    
    status = "💎 VIP ATIVO" if is_premium(m.chat.id) else "❌ ASSINATURA EXPIRADA"
    await m.answer(f"{status}\n📅 Validade: {row[1]}\n🔗 URL: `https://{BASE_URL}/webhook/{row[0]}`", reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "📊 Dashboard")
async def btn_dash(m: Message):
    if not is_premium(m.chat.id): return await m.answer("⚠️ Acesso expirado!", reply_markup=buy_button())
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
    await m.answer(f"📊 *STATUS*\nLeads: {res[0]}\nRecuperadas: {res[1]}", parse_mode="Markdown")

@dp.message(F.text == "🏆 Ranking")
async def btn_ranking(m: Message):
    with sqlite3.connect(DB_PATH) as conn:
        top = conn.execute("SELECT username, vendas_recuperadas FROM users ORDER BY vendas_recuperadas DESC LIMIT 5").fetchall()
    txt = "🏆 *TOP AFILIADOS*\n\n" + "\n".join([f"👤 {n}: {v} vendas" for n, v in top])
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "💳 Renovar Assinatura")
async def btn_renew(m: Message):
    await m.answer("💳 *RENOVAÇÃO ZAPFOLLOW PRO*\nEscolha seu plano e mantenha suas recuperações ativas!", reply_markup=buy_button(), parse_mode="Markdown")

@dp.message(F.text == "📖 Ajuda")
async def btn_help(m: Message):
    await m.answer("📖 *SUPORTE*\nCopie sua URL e configure na sua plataforma de vendas.\nDúvidas? @AndreSilva", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("win_"))
async def win_callback(cb: types.CallbackQuery):
    rid = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,))
        conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
    await cb.message.edit_text("💰 *VENDA SALVA!* Seu ranking foi atualizado.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
