import os, asyncio, sqlite3, urllib.parse, secrets, logging, random
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

# --- BANCO DE DADOS ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY, username TEXT, premium INTEGER DEFAULT 0, 
            webhook_token TEXT UNIQUE, vendas_recuperadas INTEGER DEFAULT 0, 
            total_leads INTEGER DEFAULT 0, expires_at TEXT, trial_used INTEGER DEFAULT 0)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, phone TEXT, name TEXT, 
            due TEXT, product TEXT, status TEXT DEFAULT 'pending')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS conversion_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, type TEXT, created_at DATE DEFAULT (DATE('now')))""")
init_db()

# --- INTELIGÊNCIA DE VENDAS ---
def get_persuasive_script(product, name, status):
    scripts_pix = [
        f"Olá {name}! Vi que o Pix do {product} foi gerado, mas ainda não caiu aqui. Quer que eu verifique se houve algum erro no banco?",
        f"Oi {name}, notei seu interesse no {product}. Sabia que pagando via Pix agora o seu bônus é liberado na hora? Posso te ajudar?"
    ]
    scripts_boleto = [
        f"Fala {name}! O boleto do {product} vence logo. Se pagar agora e me mandar o comprovante, consigo segurar sua vaga!",
        f"Olá {name}, passando para avisar que sua vaga no {product} está garantida. Alguma dúvida sobre o pagamento?"
    ]
    return random.choice(scripts_pix if "PIX" in status else scripts_boleto)

def is_premium(chat_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT premium, expires_at FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        if not row or row[0] == 0: return False
        if row[1] and datetime.now() > datetime.strptime(row[1], "%Y-%m-%d"):
            conn.execute("UPDATE users SET premium = 0 WHERE chat_id=?", (chat_id,))
            return False
        return True

# --- AGENDADOR ---
async def main_scheduler():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM reminders WHERE due <= ? AND status='pending'", (now,))
                for r in cursor.fetchall():
                    rid, cid, phone, name, due, prod, status = r
                    link = f"https://wa.me/{phone}?text={urllib.parse.quote('Olá ' + name + ', notei que seu pedido do ' + prod + ' ainda não foi confirmado...')}"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📲 Iniciar Recuperação", url=link)],
                        [InlineKeyboardButton(text="💰 Venda Confirmada", callback_data=f"win_{rid}")]
                    ])
                    await bot.send_message(cid, f"⏰ *HORA DO RECONTATO!*\n\n👤 Cliente: *{name}*\n📦 Produto: *{prod}*\n\n_Dica: O lead esfria rápido, chame agora!_", reply_markup=kb, parse_mode="Markdown")
                    cursor.execute("UPDATE reminders SET status='notified' WHERE id=?", (rid,))
                conn.commit()
        except Exception as e: logging.error(f"Erro: {e}")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(main_scheduler())
    await bot.set_webhook(url=f"https://{BASE_URL}/tg-bot")
    yield

app = FastAPI(lifespan=lifespan)

# --- WEBHOOKS ---
@app.get("/webhook/{token}")
async def validate(token: str, code: str = None, challenge: str = None):
    return code or challenge or {"status": "ZapFollowPro Online"}

@app.post("/webhook/{token}")
async def platform_webhook(token: str, request: Request):
    data = await request.json()
    with sqlite3.connect(DB_PATH) as conn:
        user = conn.execute("SELECT chat_id FROM users WHERE webhook_token=?", (token,)).fetchone()
        if not user or not is_premium(user[0]): return {"error": "blocked"}
        
        cid = user[0]
        name = data.get("customer_name") or data.get("name") or "Cliente"
        phone = str(data.get("phone") or data.get("customer_mobile") or "").replace("+", "").replace(" ", "")
        prod = data.get("product_name") or data.get("product") or "Produto"
        status = str(data.get("order_status") or data.get("status")).upper()

        if status in ["PAID", "APPROVED", "COMPLETED"]:
            conn.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'sale')", (cid,))
            await bot.send_message(cid, f"✅ *VENDA REALIZADA!* 💵\n\n👤 {name}\n📦 {prod}\n\n_O dinheiro já está a caminho!_")
        elif status in ["PENDING", "WAITING_PAYMENT", "UNPAID", "BILLET"]:
            due = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
            script = get_persuasive_script(prod, name, status)
            conn.execute("INSERT INTO reminders (chat_id, phone, name, due, product) VALUES (?,?,?,?,?)", (cid, phone, name, due, prod))
            conn.execute("INSERT INTO conversion_log (chat_id, type) VALUES (?, 'lead')", (cid,))
            conn.execute("UPDATE users SET total_leads = total_leads + 1 WHERE chat_id=?", (cid,))
            
            await bot.send_message(cid, 
                f"🎯 *NOVO LEAD IDENTIFICADO!*\n\n"
                f"👤 *Cliente:* {name}\n"
                f"📦 *Produto:* {prod}\n\n"
                f"🛠 *Script Sugerido (Toque para copiar):*\n"
                f"`{script}`\n\n"
                f"⏰ _Follow-up agendado para 30 min._", parse_mode="Markdown")
        conn.commit()
    return {"status": "ok"}

@app.post("/tg-bot")
async def bot_webhook(request: Request):
    await dp.feed_update(bot, types.Update(**await request.json()))
    return {"ok": True}

# --- COMANDOS VISUAIS ---

@dp.message(Command("start"))
async def cmd_start(m: Message):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT webhook_token, expires_at FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
        if not row:
            token, exp = secrets.token_hex(8), (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            conn.execute("INSERT INTO users (chat_id, username, webhook_token, premium, expires_at, trial_used) VALUES (?,?,?,1,?,1)", (m.chat.id, m.from_user.first_name, token, exp))
            conn.commit()
            await m.answer(f"🎁 *BEM-VINDO AO ZAPFOLLOW PRO!*\n\nVocê ganhou *3 DIAS VIP*.\n📅 Expira em: `{exp}`", parse_mode="Markdown")
            row = (token, exp)
    
    url = f"https://{BASE_URL}/webhook/{row[0]}"
    menu = (
        f"💎 *PAINEL EXECUTIVO*\n\n"
        f"👤 Usuário: *{m.from_user.first_name}*\n"
        f"📅 Validade: `{row[1]}`\n\n"
        f"🔗 *URL DE INTEGRAÇÃO:*\n`{url}`\n\n"
        f"🚀 Use os comandos abaixo para gerir:\n"
        f"📊 /dashboard - Resumo geral\n"
        f"📑 /relatorio - Análise semanal\n"
        f"🏆 /ranking - Top Afiliados"
    )
    await m.answer(menu, parse_mode="Markdown")

@dp.message(Command("ranking"))
async def cmd_ranking(m: Message):
    if not is_premium(m.chat.id): return
    with sqlite3.connect(DB_PATH) as conn:
        top = conn.execute("SELECT username, vendas_recuperadas FROM users WHERE vendas_recuperadas > 0 ORDER BY vendas_recuperadas DESC LIMIT 5").fetchall()
    
    txt = "🏆 *RANKING DOS MELHORES AFILIADOS*\n\n"
    icons = ["🥇", "🥈", "🥉", "👤", "👤"]
    for i, (name, sales) in enumerate(top):
        txt += f"{icons[i]} *{name}* - {sales} vendas\n"
    
    if not top: txt += "Ainda não há dados no ranking. Seja o primeiro!"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(Command("dashboard"))
async def cmd_dash(m: Message):
    if not is_premium(m.chat.id): return
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute("SELECT total_leads, vendas_recuperadas FROM users WHERE chat_id=?", (m.chat.id,)).fetchone()
    
    leads, wins = res[0], res[1]
    conv = (wins/leads*100) if leads > 0 else 0
    bar = "🟩" * int(conv/10) + "⬜" * (10 - int(conv/10))
    
    dash = (
        f"📊 *MINHA PERFORMANCE*\n\n"
        f"🔥 Leads Totais: `{leads}`\n"
        f"💰 Vendas Salvas: `{wins}`\n"
        f"📈 Taxa de Conversão: `{conv:.1f}%`\n\n"
        f"{bar}\n\n"
        f"Continue escalando seu negócio!"
    )
    await m.answer(dash, parse_mode="Markdown")

@dp.message(Command("relatorio"))
async def cmd_rel(m: Message):
    if not is_premium(m.chat.id): return
    with sqlite3.connect(DB_PATH) as conn:
        stats = dict(conn.execute("SELECT type, COUNT(*) FROM conversion_log WHERE chat_id=? GROUP BY type", (m.chat.id,)).fetchall())
    l, s = stats.get('lead', 0), stats.get('sale', 0)
    await m.answer(f"📑 *RELATÓRIO DE IMPACTO*\n\n🎯 Leads Captados: `{l}`\n💵 Vendas Confirmadas: `{s}`\n\n_Dados baseados em suas integrações ativas._", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("win_"))
async def win_callback(cb: types.CallbackQuery):
    rid = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET vendas_recuperadas = vendas_recuperadas + 1 WHERE chat_id=?", (cb.from_user.id,))
        conn.execute("DELETE FROM reminders WHERE id=?", (rid,))
        conn.commit()
    await cb.message.edit_text("💰 *VENDA COMPUTADA!* Você subiu no ranking. 🚀")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
