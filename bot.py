import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramRetryAfter

# --- CONFIGURAÇÕES DE ELITE (REI DO SAAS) ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8614152444:AAExDqoXFSioKso4fJCSqOtdv_awYhlOj10"
ADMIN_ID = 8449316389 
BASE_URL = os.getenv("RAILWAY_STATIC_URL", "zapfollow-production.up.railway.app")
DB_PATH = "venda_plus_enterprise.db"

# Informações de Negócio (André Silva)
PIX_KEY = "(44) 99964-8254"
SUPPORT_LINK = "https://wa.me/5544999648254" 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- DATABASE ENGINE (POOL DE CONEXÕES) ---
def db_query(query, params=(), fetchone=False, commit=False):
    with sqlite3.connect(DB_PATH, timeout=20) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        if commit: conn.commit()
        if fetchone: return cursor.fetchone()
        return cursor.fetchall()

def init_db():
    db_query("""CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY, username TEXT, premium INTEGER DEFAULT 0, 
        webhook_token TEXT UNIQUE, vendas_recuperadas INTEGER DEFAULT 0, 
        total_leads INTEGER DEFAULT 0, last_activity TEXT, expires_at TEXT)""", commit=True)
init_db()

# --- MOTOR DE COPYWRITING DINÂMICO ---
def get_advanced_copy(name, product, payment_type, value):
    first_name = name.split()[0].title()
    high_ticket = " (Condição Especial)" if value and float(value) > 500 else ""
    
    scripts = {
        "PIX": f"Fala {first_name}! Vi que o Pix do {product} foi gerado, mas ainda não caiu no sistema. 🚀\n\nComo esse lote{high_ticket} é limitado, vim te perguntar se deu erro no app do banco ou se quer que eu te mande o código copia e cola por aqui?",
        "CARD": f"Oi {first_name}, tudo bem? Notei uma pequena instabilidade na sua tentativa de compra do {product}. ⚠️\n\nIsso geralmente é o banco bloqueando. Quer que eu tente liberar um link alternativo para você garantir sua vaga e os bônus?",
        "BOLETO": f"Olá {first_name}! Vi que você gerou o boleto do {product}. 📄\n\nSe me mandar o comprovante aqui, eu já libero seu acesso na hora sem precisar esperar os 3 dias do banco!"
    }
    return urllib.parse.quote(scripts.get(payment_type, scripts["PIX"]))

# --- LOGICA DE RECUPERAÇÃO SMART ---
async def process_smart_recovery(cid, name, phone, prod, payment_type, value):
    await asyncio.sleep(300) # O "Ponto de Ouro" de 5 minutos
    
    clean_phone = ''.join(filter(str.isdigit, str(phone)))
    if not clean_phone.startswith('55'): clean_phone = '55' + clean_phone
    
    wa_link = f"https://wa.me/{clean_phone}?text={get_advanced_copy(name, prod, payment_type, value)}"
    score = "🔥 ALTA" if payment_type == "PIX" else "⚡ MÉDIA"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 ABORDAR AGORA (Copy Pronta)", url=wa_link)],
        [InlineKeyboardButton(text="✅ Marcar como Recuperada", callback_data="win_confirm")]
    ])
    
    try:
        await bot.send_message(cid, 
            f"🚀 *NOVA OPORTUNIDADE DE VENDA!*\n\n"
            f"👤 *Cliente:* {name}\n📦 *Produto:* {prod}\n"
            f"💳 *Método:* `{payment_type}`\n💰 *Valor:* `R$ {value}`\n"
            f"🎯 *Chance:* `{score}`\n\n"
            f"O lead está com o celular na mão. Essa é a hora!", reply_markup=kb, parse_mode="Markdown")
    except Exception as e: logger.error(f"Erro envio TG: {e}")

# --- WEBHOOKS (FASTAPI) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot", drop_pending_updates=True)
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/webhook/{token}")
async def enterprise_webhook(token: str, request: Request, background_tasks: BackgroundTasks):
    user = db_query("SELECT chat_id, premium FROM users WHERE webhook_token=?", (token,), fetchone=True)
    if not user or user['premium'] == 0: return {"status": "unauthorized"}
    
    try:
        data = await request.json()
        status = str(data.get("status", "")).upper()
        cid, name = user['chat_id'], data.get("customer_name") or data.get("name") or "Cliente"
        phone = data.get("phone") or data.get("customer_mobile") or ""
        prod = data.get("product_name") or data.get("product") or "Produto"
        value = data.get("price") or data.get("value") or "0.00"
        pay_type = "PIX" if "PIX" in str(data).upper() else "CARD" if "CARD" in str(data).upper() else "BOLETO"

        if status in ["PAID", "APPROVED", "COMPLETED"]:
            db_query("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cid,), commit=True)
            await bot.send_message(cid, f"💰 *DINHEIRO NO CAIXA!*\n\nO cliente *{name}* acabou de pagar o {prod}. 🚀")
        elif status in ["PENDING", "WAITING", "BILLETT", "ABANDONED"]:
            db_query("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,), commit=True)
            background_tasks.add_task(process_smart_recovery, cid, name, phone, prod, pay_type, value)
        return {"status": "ok"}
    except Exception as e: return {"status": "error"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS DO TELEGRAM ---

@dp.message(Command("start"))
@dp.message(F.text == "💎 Meu Painel")
async def cmd_panel(m: Message):
    user = db_query("SELECT webhook_token, expires_at, premium FROM users WHERE chat_id=?", (m.chat.id,), fetchone=True)
    if not user:
        token, exp = secrets.token_hex(10), (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        db_query("INSERT INTO users (chat_id, username, webhook_token, premium, expires_at) VALUES (?,?,?,1,?)", 
                 (m.chat.id, m.from_user.first_name, token, exp), commit=True)
        user = {'webhook_token': token, 'expires_at': exp, 'premium': 1}

    status = "👑 PREMIUM" if user['premium'] == 1 else "⚠️ EXPIRADO"
    await m.answer(f"🔱 *ZAPFOLLOW ENTERPRISE*\n━━━━━━━━━━━━━━━━━━━━\n👤 Usuário: *{m.from_user.first_name}*\n📊 Status: `{status}`\n📅 Validade: `{user['expires_at']}`\n\n🔗 *URL DE CONEXÃO:*\n`https://{BASE_URL}/webhook/{user['webhook_token']}`", 
                   reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "📊 Performance")
async def btn_perf(m: Message):
    res = db_query("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,), fetchone=True)
    if not res: return
    
    leads, wins = res['total_leads'], res['vendas_recuperadas']
    
    # MÁSCARA DE ADMIN (Para gravar TikTok)
    if m.from_user.id == ADMIN_ID:
        leads += 1542
        wins += 487
        faturamento = wins * 147.50
        await m.answer(f"📈 *PAINEL DE CONTROLE - ADMIN*\n━━━━━━━━━━━━━━━━━━━━\n🎯 Leads Totais: `{leads}`\n💰 Vendas Recuperadas: `{wins}`\n💵 Faturamento: `R$ {faturamento:,.2f}`\n📊 Conversão: `{(wins/leads*100):.1f}%`", parse_mode="Markdown")
    else:
        taxa = (wins/leads*100) if leads > 0 else 0
        await m.answer(f"📈 *SEUS RESULTADOS*\n\n🎯 Leads Gerados: `{leads}`\n💰 Vendas Recuperadas: `{wins}`\n📊 Taxa: `{taxa:.1f}%`", parse_mode="Markdown")

@dp.message(Command("fake_sale"))
async def cmd_fake(m: Message):
    if m.from_user.id != ADMIN_ID: return
    for _ in range(3):
        await m.answer(f"✅ *VENDA APROVADA!* 💵\n\n👤 *Cliente:* Lead Viral\n📦 *Produto:* Método SaaS Pro\n💰 *Valor:* `R$ 297,00`", parse_mode="Markdown")
        await asyncio.sleep(2)

@dp.message(F.text == "🏆 Top Players")
async def btn_top(m: Message):
    ranking = [("Vanessa Confeitaria", 244), ("Felipe Elite", 198), ("André Silva", 156)]
    txt = "🏆 *HALL DA FAMA*\n\n"
    for i, (n, v) in enumerate(ranking): txt += f"{'🥇' if i==0 else '👤'} *{n}* — `{v} vendas`\n"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "💳 Renovar VIP")
async def btn_pay(m: Message):
    await m.answer(f"💳 *UPGRADE DE CONTA*\n\n📍 Chave Pix: `{PIX_KEY}`\n\nApós o pagamento, envie o comprovante no suporte.", 
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Suporte", url=SUPPORT_LINK)]]), parse_mode="Markdown")

def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="💎 Meu Painel"), KeyboardButton(text="📊 Performance")], [KeyboardButton(text="🏆 Top Players"), KeyboardButton(text="💳 Renovar VIP")]], resize_keyboard=True)

@dp.callback_query(F.data == "win_confirm")
async def win_confirm(cb: types.CallbackQuery):
    db_query("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,), commit=True)
    await cb.answer("Venda salva! 🚀", show_alert=True)
    await cb.message.delete()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
