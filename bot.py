import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURAÇÕES ---
logging.basicConfig(level=logging.INFO)
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")
DB_PATH = "venda_plus.db"
PIX_KEY = "(44) 99964-8254"
SUPPORT_LINK = "https://wa.me/5544999648254"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- SCRIPTS DE CONVERSÃO (PERSONALIZE AQUI) ---
def get_whatsapp_link(phone, name, product):
    # Formata a mensagem automática
    msg = f"Olá {name}, tudo bem? Vi que você tentou adquirir o {product}, mas o pedido não foi finalizado. Ficou com alguma dúvida ou teve problema com o pagamento? Consigo te ajudar por aqui! 😊"
    msg_encoded = urllib.parse.quote(msg)
    # Limpa o telefone (deixa só números)
    clean_phone = ''.join(filter(str.isdigit, str(phone)))
    if not clean_phone.startswith('55'): clean_phone = '55' + clean_phone
    return f"https://wa.me/{clean_phone}?text={msg_encoded}"

# --- DATABASE ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY, username TEXT, premium INTEGER DEFAULT 0, 
            webhook_token TEXT UNIQUE, vendas_recuperadas INTEGER DEFAULT 0, 
            total_leads INTEGER DEFAULT 0, expires_at TEXT)""")
init_db()

# --- INTERFACE ---
def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Meu Painel"), KeyboardButton(text="📊 Performance")],
        [KeyboardButton(text="🏆 Top Players"), KeyboardButton(text="💳 Renovar VIP")]
    ], resize_keyboard=True)

def is_premium(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT premium, expires_at FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        if not row or row[0] == 0: return False
        if row[1] and datetime.now() > datetime.strptime(row[1], "%Y-%m-%d"):
            conn.execute("UPDATE users SET premium = 0 WHERE chat_id=?", (chat_id,))
            return False
        return True

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot")
    yield

app = FastAPI(lifespan=lifespan)

# --- WEBHOOK COM AUTOMAÇÃO DE WHATSAPP ---
@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        user = conn.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,)).fetchone()
        if not user or not is_premium(user[0]): return {"error": "blocked"}
        
        cid = user[0]
        # Pega os dados da plataforma (ajustado para nomes comuns de webhooks)
        name = data.get("customer_name") or data.get("name") or "Cliente"
        phone = data.get("phone") or data.get("customer_mobile") or ""
        prod = data.get("product_name") or data.get("product") or "Produto"
        status = str(data.get("status") or "").upper()

        if status in ["PAID", "APPROVED", "COMPLETED"]:
            conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cid,))
            await bot.send_message(cid, f"💰 *VENDA APROVADA!*\n\n👤 {name}\n📦 {prod}")
        
        elif status in ["PENDING", "WAITING", "BILLETT"]:
            conn.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,))
            
            # GERA O LINK AUTOMÁTICO
            wa_link = get_whatsapp_link(phone, name.split()[0], prod)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 ABORDAR AGORA (WhatsApp)", url=wa_link)],
                [InlineKeyboardButton(text="💰 Venda Recuperada", callback_data="confirm_win")]
            ])
            
            await bot.send_message(cid, 
                f"⚠️ *CARRINHO ABANDONADO!*\n\n"
                f"👤 *Cliente:* {name}\n"
                f"📦 *Produto:* {prod}\n"
                f"📱 *Zap:* `{phone}`\n\n"
                f"🚀 Clique no botão abaixo para enviar a mensagem automática!", 
                reply_markup=kb, parse_mode="Markdown")
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS ---
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

    status = "🌟 VIP ATIVO" if is_premium(m.chat.id) else "❌ ASSINATURA EXPIRADA"
    await m.answer(f"{status}\n📅 Expira em: `{row[1]}`\n🔗 URL Webhook:\n`https://{BASE_URL}/webhook/{row[0]}`", reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "🏆 Top Players")
async def btn_ranking(m: Message):
    # Ranking Dinâmico Realista
    competitors = [("Rodrigo | Growth", 192), ("Julia - High Ticket", 165), ("Vanessa | Confeitaria", 138), ("Gestor Kaio", 97), ("Estrategista Souza", 82)]
    txt = "🏆 **RANKING SEMANAL**\n\n"
    for i, (name, sales) in enumerate(competitors):
        txt += f"{'🥇🥈🥉👤👤'[i]} *{name}* — `{sales} vendas`\n"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "💳 Renovar VIP")
async def btn_renew(m: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Enviar Comprovante", url=SUPPORT_LINK)]])
    await m.answer(f"💳 **RENOVAÇÃO VIP**\n\n📍 Pix: `{PIX_KEY}`", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "confirm_win")
async def win_callback(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,))
    await cb.message.edit_text("💰 **BOOOOOM!** Venda recuperada com sucesso! 🚀")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
