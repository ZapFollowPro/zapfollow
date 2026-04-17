import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURAÇÕES DE ALTA PERFORMANCE ---
logging.basicConfig(level=logging.INFO)
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389 
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")
DB_PATH = "venda_plus.db"

# Informações de Negócio e Suporte (André Silva)
PIX_KEY = "(44) 99964-8254"
SUPPORT_LINK = "https://wa.me/5544999648254" 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- AUTOMAÇÃO DE ABORDAGEM (GATILHOS DE URGÊNCIA) ---
def get_whatsapp_link(phone, name, product):
    # Mensagem focada em Dor, Escassez e Necessidade
    msg = (
        f"Olá {name}, aqui é do suporte VIP! 🚀\n\n"
        f"Notei que você não finalizou sua inscrição no {product}. "
        f"Passando para avisar que sua vaga (e o bônus exclusivo) expira em 15 minutos devido à alta demanda de hoje. ⏳\n\n"
        f"Não quero que você perca essa oportunidade de escalar seus resultados. "
        f"Teve algum problema com o Pix ou cartão? Me chama aqui agora!"
    )
    msg_encoded = urllib.parse.quote(msg)
    clean_phone = ''.join(filter(str.isdigit, str(phone)))
    if not clean_phone.startswith('55'): clean_phone = '55' + clean_phone
    return f"https://wa.me/{clean_phone}?text={msg_encoded}"

# --- BANCO DE DADOS (SILENT BOOT) ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY, username TEXT, premium INTEGER DEFAULT 0, 
            webhook_token TEXT UNIQUE, vendas_recuperadas INTEGER DEFAULT 0, 
            total_leads INTEGER DEFAULT 0, expires_at TEXT)""")
init_db()

# --- INTERFACE "APP STYLE" ---
def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Meu Painel"), KeyboardButton(text="📊 Performance")],
        [KeyboardButton(text="🏆 Top Players"), KeyboardButton(text="💳 Renovar VIP")],
        [KeyboardButton(text="📖 Guia de Escala")]
    ], resize_keyboard=True)

def support_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Falar com Suporte (WhatsApp)", url=SUPPORT_LINK)]
    ])

# --- LÓGICA DE ACESSO ---
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

# --- WEBHOOKS DE INTEGRAÇÃO ---
@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        user = conn.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,)).fetchone()
        if not user or not is_premium(user[0]): return {"error": "blocked"}
        
        cid = user[0]
        name = data.get("customer_name") or data.get("name") or "Cliente"
        phone = data.get("phone") or data.get("customer_mobile") or ""
        prod = data.get("product_name") or data.get("product") or "Produto"
        status = str(data.get("status") or "").upper()

        if status in ["PAID", "APPROVED", "COMPLETED"]:
            conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cid,))
            await bot.send_message(cid, f"✅ *VENDA APROVADA!* 💵\n👤 {name}\n📦 {prod}")
        
        elif status in ["PENDING", "WAITING", "BILLETT"]:
            conn.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,))
            wa_link = get_whatsapp_link(phone, name.split()[0], prod)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 ABORDAR AGORA (Urgência)", url=wa_link)],
                [InlineKeyboardButton(text="💰 Venda Recuperada", callback_data="win_confirm")]
            ])
            
            await bot.send_message(cid, 
                f"⚠️ *CARRINHO ABANDONADO!*\n\n👤 *Cliente:* {name}\n📦 *Produto:* {prod}\n📱 *Zap:* `{phone}`\n\n"
                f"🚀 O lead está quente! Clique no botão abaixo para usar o script de urgência.", 
                reply_markup=kb, parse_mode="Markdown")
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS E BOTÕES ---

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

    status = "🌟 VIP ATIVO" if is_premium(m.chat.id) else "❌ EXPIRADO"
    await m.answer(f"{status}\n\n👤 Usuário: *{m.from_user.first_name}*\n📅 Validade: `{row[1]}`\n\n🔗 **SUA URL:**\n`https://{BASE_URL}/webhook/{row[0]}`", reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "📊 Performance")
async def btn_dash(m: Message):
    if not is_premium(m.chat.id): 
        return await m.answer(f"⚠️ **ACESSO EXPIRADO**\n\nRenove via Pix para liberar seus dados:\n📍 Pix: `{PIX_KEY}`", reply_markup=support_kb())
    
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
    
    l, w = res[0], res[1]
    conv = (w/l*100) if l > 0 else 0
    await m.answer(f"📊 **DASHBOARD**\n\n🔥 Leads: `{l}`\n💰 Salvas: `{w}`\n📈 Taxa: `{conv:.1f}%`", parse_mode="Markdown")

@dp.message(F.text == "🏆 Top Players")
async def btn_ranking(m: Message):
    competitors = [
        ("Felipe | Gestor de Elite", random.randint(152, 194)),
        ("Lucas - Estrategista Digital", random.randint(121, 149)),
        ("Ana Clara | Drop High Ticket", random.randint(95, 118)),
        ("Vanessa | Confeitaria Premium", random.randint(58, 71)),
        ("Mateus Sales (Escala)", random.randint(40, 57))
    ]
    competitors.sort(key=lambda x: x[1], reverse=True)
    txt = "🏆 **RANKING SEMANAL**\n\n"
    icons = ["🥇", "🥈", "🥉", "👤", "👤"]
    for i, (name, sales) in enumerate(competitors):
        txt += f"{icons[i]} *{name}* — `{sales} vendas`\n"
    txt += "\n🔥 _Sua posição: 142º lugar._"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "💳 Renovar VIP")
async def btn_renew(m: Message):
    await m.answer(f"💳 **RENOVAÇÃO ZAPFOLLOW**\n\n📍 **Chave Pix (Telefone):**\n`{PIX_KEY}`\n\nApós o pagamento, envie o comprovante no suporte.", reply_markup=support_kb(), parse_mode="Markdown")

@dp.message(F.text == "📖 Guia de Escala")
async def btn_help(m: Message):
    await m.answer("📖 **GUIA RÁPIDO**\n1. Cole a URL na plataforma.\n2. Aborde o lead assim que o bot apitar.\n3. Use o botão de WhatsApp para ganhar tempo.", reply_markup=support_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "win_confirm")
async def win_callback(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,))
    await cb.message.edit_text("💰 **VENDA RECUPERADA!** Seu ranking subiu. 🚀")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
