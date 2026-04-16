import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURAÇÕES DE ELITE ---
logging.basicConfig(level=logging.INFO)
TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389 
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")
DB_PATH = "venda_plus.db"

# Informações de Negócio
PIX_KEY = "(44) 99964-8254"
SUPPORT_LINK = "https://wa.me/5544999648254" 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- AUTOMAÇÃO E SEGURANÇA DE DADOS ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY, username TEXT, premium INTEGER DEFAULT 0, 
            webhook_token TEXT UNIQUE, vendas_recuperadas INTEGER DEFAULT 0, 
            total_leads INTEGER DEFAULT 0, expires_at TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS conversion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, type TEXT, created_at DATE DEFAULT (DATE('now')))""")
    logging.info("Core do Banco de Dados: OK")

init_db()

# --- INTERFACE "ZERO-FRICTION" (BOTÕES INTUITIVOS) ---
def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Meu Painel"), KeyboardButton(text="📊 Performance")],
        [KeyboardButton(text="🏆 Top Players"), KeyboardButton(text="📖 Guia de Escala")],
        [KeyboardButton(text="💳 Renovar VIP")]
    ], resize_keyboard=True)

def action_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirmar Pagamento", url=SUPPORT_LINK)]
    ])

# --- LÓGICA DE ESCALA ---
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

# --- WEBHOOKS (ALTA PERFORMANCE) ---
@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        user = conn.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,)).fetchone()
        if not user or not is_premium(user[0]): return {"error": "blocked"}
        
        cid = user[0]
        name = data.get("customer_name") or data.get("name") or "Cliente"
        prod = data.get("product_name") or data.get("product") or "Produto"
        status = str(data.get("status") or "").upper()

        if status in ["PAID", "APPROVED", "COMPLETED"]:
            conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cid,))
            await bot.send_message(cid, f"💰 *VENDA APROVADA!*\n\n👤 {name}\n📦 {prod}\n\n_Sua comissão está garantida!_")
        elif status in ["PENDING", "WAITING", "BILLETT"]:
            conn.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,))
            await bot.send_message(cid, f"⚠️ *CARRINHO ABANDONADO!*\n\n👤 *Cliente:* {name}\n📦 *Produto:* {prod}\n\n🚀 *MODO TURBO:* Chame agora para garantir 80% mais chance de conversão!", parse_mode="Markdown")
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS E FLUXO DE VENDAS ---

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
    msg = (f"{status}\n\n"
           f"📈 Bem-vindo à sua Central de Escala, *{m.from_user.first_name}*.\n"
           f"📅 Seu acesso expira em: `{row[1]}`\n\n"
           f"🔗 **SUA URL DE INTEGRAÇÃO:**\n`https://{BASE_URL}/webhook/{row[0]}`")
    await m.answer(msg, reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "📊 Performance")
async def btn_dash(m: Message):
    if not is_premium(m.chat.id): 
        return await m.answer(f"⚠️ **ACESSO RESTRITO**\n\nSua licença expirou. Faça o Pix agora para liberar o Dashboard e os Scripts:\n\n📍 Pix: `{PIX_KEY}`", reply_markup=action_buttons())
    
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
    
    leads, sales = res[0], res[1]
    conv = (sales/leads*100) if leads > 0 else 0
    bar = "🟩" * int(conv/10) + "⬜" * (10 - int(conv/10))
    
    await m.answer(f"📊 **ANÁLISE DE CONVERSÃO**\n\n🎯 Leads Captados: `{leads}`\n💰 Vendas Salvas: `{sales}`\n📈 Taxa: `{conv:.1f}%`\n\n{bar}\n\n_Foco total no acompanhamento!_", parse_mode="Markdown")

@dp.message(F.text == "🏆 Top Players")
async def btn_ranking(m: Message):
    # Ranking Dinâmico Realista para Gatilho de Competição
    competitors = [
        ("Rodrigo | Growth Ads", random.randint(180, 210)),
        ("Julia - High Ticket", random.randint(145, 179)),
        ("Vanessa | Confeitaria Premium", random.randint(110, 144)),
        ("Gestor Kaio 🚀", random.randint(85, 109)),
        ("Estrategista Souza", random.randint(60, 84))
    ]
    competitors.sort(key=lambda x: x[1], reverse=True)
    
    txt = "🏆 **RANKING GLOBAL DE RECUPERAÇÃO**\n\n"
    icons = ["🥇", "🥈", "🥉", "👤", "👤"]
    for i, (name, sales) in enumerate(competitors):
        txt += f"{icons[i]} *{name}* — `{sales} vendas`\n"
    
    txt += "\n🔥 _Você está na posição 154º. Suba de nível recuperando mais leads!_"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "💳 Renovar VIP")
async def btn_renew(m: Message):
    await m.answer(f"💳 **UPGRADE PARA CONTA PRO**\n\nNão deixe sua operação parar. Renove sua licença agora e mantenha os webhooks ativos.\n\n📍 **Chave Pix (Telefone):**\n`{PIX_KEY}`", reply_markup=action_buttons(), parse_mode="Markdown")

@dp.message(F.text == "📖 Guia de Escala")
async def btn_help(m: Message):
    await m.answer("📖 **MANUAL DE OPERAÇÃO**\n\n1. Integre sua URL na plataforma.\n2. Ao receber um lead, aborde em no máximo 10 min.\n3. Use scripts de bônus para fechar o Pix.\n\nPrecisa de suporte?", reply_markup=action_buttons(), parse_mode="Markdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
