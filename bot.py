import telebot
import os
import sqlite3
import time
import threading
import urllib.parse
from datetime import datetime, timedelta

# Configurações Iniciais
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("ERRO: Variável BOT_TOKEN não configurada!")
    exit()

bot = telebot.TeleBot(TOKEN)
ADMIN_ID = 8449316389  # Seu ID para liberar premium

# --- BANCO DE DADOS ---
# Se usar Volumes no Railway, mude para 'data/bot.db'
DB_PATH = "bot.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

conn = get_db_connection()
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    premium INTEGER DEFAULT 0,
    reminders_count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    phone TEXT,
    name TEXT,
    due TEXT
)
""")
conn.commit()

# --- FUNÇÕES AUXILIARES ---

def get_user(chat_id):
    cursor.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        return (chat_id, 0, 0)
    return user

# --- COMANDOS DO BOT ---

@bot.message_handler(commands=['start'])
def start(msg):
    get_user(msg.chat.id)
    text = (
        "🚀 *ZapFollow Pro - Edição Afiliados*\n\n"
        "Transforme seus leads em vendas com follow-up pontual.\n\n"
        "📌 *Comandos Principais:*\n"
        "1️⃣ `/lembrar telefone Nome Dias` \n"
        "   _Ex: /lembrar 5511999998888 João 1_\n\n"
        "2️⃣ `/lista` - Veja todos os seus agendamentos ativos.\n"
        "3️⃣ `/id` - Veja seu código de identificação.\n"
        "4️⃣ `/assinar` - Libere lembretes ilimitados."
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['id'])
def id_user(msg):
    bot.reply_to(msg, f"🆔 Seu ID: `{msg.chat.id}`", parse_mode="Markdown")

@bot.message_handler(commands=['lembrar'])
def lembrar(msg):
    user = get_user(msg.chat.id)
    is_premium = user[1]
    count = user[2]

    # Trava de segurança para usuários grátis
    if not is_premium and count >= 5:
        text = (
            "🚫 *Limite Grátis Atingido*\n\n"
            "Afiliados Pro não perdem vendas por falta de organização.\n"
            "Assine o plano ilimitado com `/assinar`."
        )
        bot.send_message(msg.chat.id, text, parse_mode="Markdown")
        return

    try:
        parts = msg.text.split(maxsplit=3)
        phone = parts[1].replace("+", "").replace("-", "").replace(" ", "")
        name = parts[2]
        days = int(parts[3])

        due_date = datetime.now() + timedelta(days=days)
        due_str = due_date.strftime("%Y-%m-%d %H:%M")

        cursor.execute(
            "INSERT INTO reminders (chat_id, phone, name, due) VALUES (?, ?, ?, ?)",
            (msg.chat.id, phone, name, due_str)
        )
        cursor.execute("UPDATE users SET reminders_count = reminders_count + 1 WHERE chat_id=?", (msg.chat.id,))
        conn.commit()

        bot.reply_to(msg, f"✅ *Sucesso!* Vou te avisar para chamar o(a) *{name}* no dia {due_date.strftime('%d/%m')}.", parse_mode="Markdown")

    except:
        bot.reply_to(msg, "❌ *Erro de formato!*\nUse: `/lembrar Telefone Nome Dias`", parse_mode="Markdown")

@bot.message_handler(commands=['lista'])
def lista_pendentes(msg):
    cursor.execute("SELECT name, phone, due FROM reminders WHERE chat_id=? ORDER BY due ASC", (msg.chat.id,))
    rows = cursor.fetchall()
    
    if not rows:
        bot.send_message(msg.chat.id, "📭 *Você não tem lembretes agendados.*", parse_mode="Markdown")
        return

    texto = "📋 *Seus próximos Follow-ups:*\n\n"
    for r in rows:
        # Formata a data de YYYY-MM-DD para DD/MM
        data_formatada = datetime.strptime(r[2], "%Y-%m-%d %H:%M").strftime("%d/%m às %H:%M")
        texto += f"🔹 *{r[0]}* ({r[1]}) - {data_formatada}\n"
    
    bot.send_message(msg.chat.id, texto, parse_mode="Markdown")

@bot.message_handler(commands=['assinar'])
def assinar(msg):
    text = (
        "💎 *ZapFollow Premium*\n\n"
        "Garanta que 100% dos seus boletos gerados recebam um contato seu.\n\n"
        "✅ Lembretes Ilimitados\n"
        "✅ Suporte via Chat\n"
        "✅ Função /lista liberada\n\n"
        "💰 *Apenas R$ 19,90/mês*\n\n"
        "🔑 *Chave Pix:* `44999648254` \n\n"
        "Envie o comprovante e seu ID para o suporte após o pagamento."
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['liberar'])
def liberar(msg):
    if msg.chat.id != ADMIN_ID:
        return

    try:
        user_id = int(msg.text.split()[1])
        cursor.execute("UPDATE users SET premium=1 WHERE chat_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "✨ *Sua conta foi atualizada para PREMIUM!*\nBoas vendas!", parse_mode="Markdown")
        bot.reply_to(msg, f"✅ Usuário {user_id} liberado!")
    except:
        bot.reply_to(msg, "❌ Use: `/liberar ID_DO_USUARIO`", parse_mode="Markdown")

# --- LOOP DE VERIFICAÇÃO (Thread) ---

def check_reminders():
    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("SELECT * FROM reminders WHERE due <= ?", (now,))
            rows = cursor.fetchall()

            for r in rows:
                rid, chat_id, phone, name = r[0], r[1], r[2], r[3]
                
                # Mensagem padrão para o afiliado enviar ao cliente
                msg_whatsapp = f"Olá {name}, tudo bem? Notei que você se interessou pelo treinamento mas não concluiu a inscrição. Ficou com alguma dúvida?"
                encoded_msg = urllib.parse.quote(msg_whatsapp)
                link = f"https://wa.me/{phone}?text={encoded_msg}"

                text = (
                    f"🔔 *HORA DO FOLLOW-UP!*\n\n"
                    f"👤 *Cliente:* {name}\n"
                    f"📱 *Zap:* `{phone}`\n\n"
                    f"👉 [CLIQUE AQUI PARA CHAMAR NO ZAP]({link})"
                )
                
                bot.send_message(chat_id, text, parse_mode="Markdown", disable_web_page_preview=True)
                
                # Deleta após avisar
                cursor.execute("DELETE FROM reminders WHERE id=?", (rid,))
                conn.commit()
        except Exception as e:
            print(f"Erro no loop de lembretes: {e}")
        
        time.sleep(40) # Checa a cada 40 segundos

# Iniciar Thread de Segundo Plano
threading.Thread(target=check_reminders, daemon=True).start()

# Iniciar o Bot
print("🚀 ZapFollow Pro está online!")
bot.infinity_polling()

