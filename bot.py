import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramRetryAfter

# --- CONFIGURAÇÕES DE INFRAESTRUTURA CLOUD ---
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

# --- ENGINE DE BANCO DE DADOS ESCALÁVEL ---
def db_query(query, params=(), fetchone=False, commit=False):
    """Executa queries de forma segura para evitar Database Locks em escala."""
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

# --- INTELIGÊNCIA DE CONVERSÃO (NEURO-COPY) ---
def get_advanced_copy(name, product, payment_type, value):
    first_name = name.split()[0].title()
    # Se o valor for alto, o script muda para uma abordagem mais consultiva
    high_ticket = " (Condição Especial)" if value and float(value) > 500 else ""
    
    scripts = {
        "PIX": f"Fala {first_name}! Vi que o Pix do {product} foi gerado, mas ainda não caiu no sistema. 🚀\n\nComo esse lote{high_ticket} é limitado, vim te perguntar se deu erro no app do banco ou se quer que eu te mande o código copia e cola por aqui?",
        "CARD": f"Oi {first_name}, tudo bem? Notei uma pequena instabilidade na sua tentativa de compra do {product}. ⚠️\n\nIsso geralmente é o banco bloqueando. Quer que eu tente liberar um link alternativo para você garantir sua vaga e os bônus?",
        "BOLETO": f"Olá {first_name}! Vi que você gerou o boleto do {product}. 📄\n\nLembrando que ele vence rápido e a compensação demora. Se me mandar o comprovante aqui, eu já libero seu acesso na hora sem precisar esperar os 3 dias do banco!"
    }
    
    final_msg = scripts.get(payment_type, scripts["PIX"])
    return urllib.parse.quote(final_msg)

# --- SISTEMA DE FILA E NOTIFICAÇÃO INTELIGENTE ---
async def process_smart_recovery(cid, name, phone, prod, payment_type, value):
    """Lógica de Delay Psicológico para máxima conversão."""
    await asyncio.sleep(300) # 5 minutos: O Ponto de Ouro
    
    clean_phone = ''.join(filter(str.isdigit, str(phone)))
    if not clean_phone.startswith('55'): clean_phone = '55' + clean_phone
    
    wa_link = f"https://wa.me/{clean_phone}?text={get_advanced_copy(name, prod, payment_type, value)}"
    
    # Lead Scoring (Calcula urgência)
    score = "🔥 ALTA" if payment_type == "PIX" else "⚡ MÉDIA"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 ABORDAR AGORA (Copy Pronta)", url=wa_link)],
        [InlineKeyboardButton(text="✅ Marcar como Recuperada", callback_data="win_confirm")]
    ])
    
    try:
        await bot.send_message(cid, 
            f"🚀 *NOVA OPORTUNIDADE DE VENDA!*\n\n"
            f"👤 *Cliente:* {name}\n"
            f"📦 *Produto:* {prod}\n"
            f"💳 *Método:* `{payment_type}`\n"
            f"💰 *Valor:* `R$ {value}`\n"
            f"🎯 *Chance de Fechamento:* `{score}`\n\n"
            f"O lead está com o celular na mão. Essa é a hora!", 
            reply_markup=kb, parse_mode="Markdown")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.send_message(cid, "...")

# --- ENDPOINTS ENTERPRISE (FASTAPI) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot", drop_pending_updates=True)
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/webhook/{token}")
async def enterprise_webhook(token: str, request: Request, background_tasks: BackgroundTasks):
    user = db_query("SELECT chat_id, premium FROM users WHERE webhook_token=?", (token,), fetchone=True)
    
    if not user or user['premium'] == 0:
        raise HTTPException(status_code=401, detail="Invalid token or expired premium")
    
    try:
        data = await request.json()
        status = str(data.get("status", "")).upper()
        
        # Mapeamento de Status Genérico (Funciona em todas as plataformas)
        is_paid = status in ["PAID", "APPROVED", "COMPLETED", "APROVADO", "PAGO"]
        is_pending = status in ["PENDING", "WAITING", "BILLETT", "WAITING_PAYMENT", "ABANDONED", "CARRINHO_ABANDONADO"]

        cid = user['chat_id']
        name = data.get("customer_name") or data.get("name") or "Cliente"
        phone = data.get("phone") or data.get("customer_mobile") or ""
        prod = data.get("product_name") or data.get("product") or "Produto"
        value = data.get("price") or data.get("value") or "0.00"
        pay_type = "PIX" if "PIX" in str(data).upper() else "CARD" if "CARD" in str(data).upper() else "BOLETO"

        if is_paid:
            db_query("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cid,), commit=True)
            await bot.send_message(cid, f"💰 *DINHEIRO NO CAIXA!*\n\nO cliente *{name}* acabou de pagar o {prod}. Parabéns! 🚀")
        
        elif is_pending:
            db_query("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,), commit=True)
            background_tasks.add_task(process_smart_recovery, cid, name, phone, prod, pay_type, value)

        return {"status": "success"}
    except Exception as e:
        logger.error(f"Erro no Webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS E UX ---

@dp.message(Command("start"))
@dp.message(F.text == "💎 Meu Painel")
async def cmd_panel(m: Message):
    user = db_query("SELECT webhook_token, expires_at, premium FROM users WHERE chat_id=?", (m.chat.id,), fetchone=True)
    
    if not user:
        token = secrets.token_hex(10)
        exp = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        db_query("INSERT INTO users (chat_id, username, webhook_token, premium, expires_at) VALUES (?,?,?,1,?)", 
                 (m.chat.id, m.from_user.first_name, token, exp), commit=True)
        user = {'webhook_token': token, 'expires_at': exp, 'premium': 1}

    status = "👑 PREMIUM" if user['premium'] == 1 else "⚠️ EXPIRADO"
    msg = (
        f"🔱 *ZAPFOLLOW ENTERPRISE*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Usuário: *{m.from_user.first_name}*\n"
        f"📊 Status: `{status}`\n"
        f"📅 Validade: `{user['expires_at']}`\n\n"
        f"🔗 *URL DE CONEXÃO:*\n"
        f"`https://{BASE_URL}/webhook/{user['webhook_token']}`\n\n"
        f"💡 _Conecte este link na sua plataforma de vendas para iniciar a recuperação automática._"
    )
    await m.answer(msg, reply_markup=main_keyboard(), parse_mode="Markdown")

@dp.message(F.text == "📊 Performance")
async def btn_perf(m: Message):
    res = db_query("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,), fetchone=True)
    if not res: return
    
    leads, wins = res['total_leads'], res['vendas_recuperadas']
    taxa = (wins/leads*100) if leads > 0 else 0
    
    await m.answer(
        f"📈 *RELATÓRIO DE PERFORMANCE*\n\n"
        f"🎯 Leads Gerados: `{leads}`\n"
        f"💰 Vendas Recuperadas: `{wins}`\n"
        f"📊 Taxa de Conversão: `{taxa:.1f}%`", 
        parse_mode="Markdown")

@dp.message(F.text == "🏆 Top Players")
async def btn_top(m: Message):
    # Aqui o ranking é dinâmico baseado em usuários reais (simulado para este exemplo)
    txt = "🏆 *HALL DA FAMA (Vendas Salvas)*\n\n"
    ranking = [("Vanessa Confeitaria", 244), ("Felipe Elite", 198), ("André Silva", 156), ("Lucas Digital", 92)]
    for i, (name, sales) in enumerate(ranking):
        txt += f"{'🥇' if i==0 else '👤'} *{name}* — `{sales}`\n"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "💳 Renovar VIP")
async def btn_pay(m: Message):
    await m.answer(
        f"💳 *UPGRADE DE CONTA*\n\n"
        f"Mantenha sua operação rodando 24/7.\n\n"
        f"📍 Chave Pix: `{PIX_KEY}`\n"
        f"📦 Plano: *Recuperação Ilimitada*\n\n"
        f"Após o pagamento, envie o comprovante no suporte.", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Enviar Comprovante", url=SUPPORT_LINK)]]),
        parse_mode="Markdown")

def main_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Meu Painel"), KeyboardButton(text="📊 Performance")],
        [KeyboardButton(text="🏆 Top Players"), KeyboardButton(text="💳 Renovar VIP")]
    ], resize_keyboard=True)

@dp.callback_query(F.data == "win_confirm")
async def win_confirm(cb: types.CallbackQuery):
    db_query("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,), commit=True)
    await cb.answer("Parabéns! Venda contabilizada. 🔥", show_alert=True)
    await cb.message.delete()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
