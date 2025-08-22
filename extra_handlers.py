# extra_handlers.py
import random, re, logging, time, threading, math
from database import Database
from handlers import register_user
from telebot import types
import threading

log = logging.getLogger(__name__)
db = Database()

# === Конфиг ===
MIN_RANDOM = 35
MAX_RANDOM = 350
MIN_BET = 15
BET_COOLDOWN = 7            # кулдаун на любые ставки
STREET_COOLDOWN = 15        # кулдаун /bomj

OWNER_ID = 5758264503       # твой ID (админ)

PROPERTIES = {
    "hut": {
        "name": "Хижина на отшибе",
        "price": 20000,
        "command": "mafia",
        "cooldown": 20,
        "income": (140, 740),
        "message": "🥷Ты выполнил маленькое задание от мафии, получив зарплату {money} бублей",
    },
    "communal": {
        "name": "Коммуналка в гетто",
        "price": 95000,
        "command": "clean",
        "cooldown": 30,
        "income": (500, 1800),
        "message": "🫧 🧽Ты помыл пол в соседнем общежитии, и тебе скинулись {money} бублей",
    }
}

# === Таблицы (создание при первом импорте) ===
def _ensure_tables():
    with db.get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS properties (
            user_id INTEGER,
            property_key TEXT,
            UNIQUE(user_id, property_key)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS nicknames (
            user_id INTEGER PRIMARY KEY,
            nickname TEXT
        )""")
        # Для дуэлей
        conn.execute("""CREATE TABLE IF NOT EXISTS duel_stats (
            user_id INTEGER PRIMARY KEY,
            wins INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS bettor_stats (
            user_id INTEGER PRIMARY KEY,
            total_won INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS treasury (
        id INTEGER PRIMARY KEY CHECK (id=1),
        balance INTEGER NOT NULL
    )""")
    row = conn.execute("SELECT balance FROM treasury WHERE id=1").fetchone()
    if not row:
        conn.execute("INSERT INTO treasury (id, balance) VALUES (1, 100000)")
        # — внутри _ensure_tables() —
    
        conn.commit()

_ensure_tables()

# === Баланс ===
def _get_balance(user_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT balance FROM balances WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else 0

def _update_balance(user_id: int, delta: int):
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO balances (user_id, balance) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance""",
            (user_id, delta)
        )
        # защита от отрицательного баланса
        conn.execute("UPDATE balances SET balance=0 WHERE user_id=? AND balance<0", (user_id,))
        conn.commit()

#===Вайп и удача===

# === Wipe всех балансов (только владелец) ===
def wipebubl_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    with db.get_connection() as conn:
        conn.execute("UPDATE balances SET balance=0")
        conn.commit()
    bot.send_message(message.chat.id, "⚠️ Все балансы обнулены.")

# Сокровищница 
def _treasury_get() -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT balance FROM treasury WHERE id=1").fetchone()
        return row[0] if row else 0

def _treasury_add(amount: int) -> None:
    if amount <= 0: 
        return
    with db.get_connection() as conn:
        conn.execute("UPDATE treasury SET balance = balance + ? WHERE id=1", (amount,))
        conn.commit()

def _treasury_sub(amount: int) -> int:
    if amount <= 0: 
        return 0
    with db.get_connection() as conn:
        bal = conn.execute("SELECT balance FROM treasury WHERE id=1").fetchone()
        cur = bal[0] if bal else 0
        take = min(cur, amount)
        if take > 0:
            conn.execute("UPDATE treasury SET balance = balance - ? WHERE id=1", (take,))
            conn.commit()
        return take
# === Luck-игра ===
_last_luck = {}   # user_id -> ts

EMOJIS = [
    "😀","😎","🤡","👻","💀","🐵","🐸","🐱","🦊","🐼",
    "🐨","🐯","🦁","🐮","🐷","🐔","🐧","🐦","🐤","🐣",
    "🐥","🦆","🦅","🦉","🐺"
]

def luck_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_luck.get(uid, 0)
    if now - last < 10:
        bot.reply_to(message, f"⏳ Подожди {int(10 - (now - last))} сек перед следующей попыткой")
        return
    _last_luck[uid] = now

    # Выбираем 5 случайных эмодзи
    chosen = random.sample(EMOJIS, 5)
    lucky_index = random.randint(0, 4)

    markup = types.InlineKeyboardMarkup()
    for i, emoji in enumerate(chosen):
        cb = f"luck_{uid}_{i}_{lucky_index}"
        markup.add(types.InlineKeyboardButton(emoji, callback_data=cb))

    bot.send_message(message.chat.id, "🎰 Под одной кнопкой есть большая деньга:", reply_markup=markup)

def luck_callback_handler(bot, call):
    try:
        parts = call.data.split("_")
        if len(parts) != 4 or parts[0] != "luck":
            return
        uid = int(parts[1])
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Не твоя игра")
            return

        chosen = int(parts[2])
        lucky_index = int(parts[3])

        bal = _get_balance(uid)
        if bal <= 0:
            bot.answer_callback_query(call.id, "❌ У тебя нет бублей", show_alert=True)
            return

        if chosen == lucky_index:
            gain = bal * 5
            _update_balance(uid, gain)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🎉 Удача! Баланс умножен в 5 раз.\n💰 Теперь у тебя {_get_balance(uid)} бублей."
            )
        else:
            loss = bal // 2
            _update_balance(uid, -loss)
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"💀 Не повезло. Минус {loss} бублей.\n💰 Остаток: {_get_balance(uid)}"
            )
    except Exception as e:
        log.error(f"luck_callback_handler error: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
# === Недвижимость ===
def _buy_property_record(user_id, key):
    with db.get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO properties (user_id, property_key) VALUES (?, ?)", (user_id, key))
        conn.commit()

def _get_properties(user_id):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT property_key FROM properties WHERE user_id=?", (user_id,)).fetchall()
        return [r[0] for r in rows]

# === Ники ===
def _set_nickname(user_id, nick):
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO nicknames (user_id, nickname) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET nickname = excluded.nickname""",
            (user_id, nick)
        )
        conn.commit()

def _get_nickname(user_id):
    with db.get_connection() as conn:
        row = conn.execute("SELECT nickname FROM nicknames WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else None

# === Кулдауны ===
_last_bet = {}     # user_id -> ts
_last_income = {}  # (user_id, property_key) -> ts
_last_street = {}  # user_id -> ts

# === Базовые хендлеры ===
def id_handler(bot, message):
    bot.reply_to(message, f"🆔 Твой Telegram ID: {message.from_user.id}")

def whoami_handler(bot, message):
    u = message.from_user
    bot.reply_to(message, f"👤 Инфо о тебе:\nИмя: {u.first_name or ''} {u.last_name or ''}\n"
                          f"Username: @{u.username if u.username else '—'}\nID: {u.id}")

def thanks_handler(bot, message):
    bot.reply_to(message, f"Пожалуйста, {message.from_user.first_name}! 🙌")

# === Баланс/работа ===
def balance_handler(bot, message):
    register_user(message)
    bot.reply_to(message, f"💰 У тебя {_get_balance(message.from_user.id)} бублей")

def street_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_street.get(uid, 0)
    if now - last < STREET_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int(STREET_COOLDOWN - (now - last))} сек")
        return
    _last_street[uid] = now
    amount = random.randint(MIN_RANDOM, MAX_RANDOM)
    _update_balance(uid, amount)
    bot.reply_to(message, f"🪙 Ты выпросил {amount} бублей на улице! (как последний бомж...)\n💰 Баланс: {_get_balance(uid)}")

# === Игры ===

def bubl_handler(bot, message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "❗ Используй так: /bubl 100")
        return

    bet = int(parts[1])
    if bet <= 0:
        bot.reply_to(message, "❗ Ставка должна быть положительной")
        return

    # Определяем ник или имя
    nick = db.get_user_nick(message.from_user.id) if hasattr(db, "get_user_nick") else None
    if not nick:
        nick = message.from_user.first_name or (message.from_user.username or "Игрок")
    nick_first = nick.split()[0]

    text = f"🤑 {nick_first}, ты с собой берёшь {bet} бублей.\n\nКак ты хочешь разбогатеть?"

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🤵 Кража", callback_data=f"bubl_pocket_{bet}_{message.from_user.id}"),
        types.InlineKeyboardButton("🎰 Казино", callback_data=f"bubl_casino_{bet}_{message.from_user.id}"),
        types.InlineKeyboardButton("🎟️ Лотерея", callback_data=f"bubl_loto_{bet}_{message.from_user.id}")
    )

    sent = bot.send_message(message.chat.id, text, reply_markup=markup)

    # Автоудаление через 20 сек, если никто не нажал
    def delete_msg():
        try:
            bot.delete_message(sent.chat.id, sent.message_id)
        except:
            pass

    threading.Timer(20.0, delete_msg).start()
   
def bubl_callback_handler(bot, call):
    try:
        data = call.data.split("_")
        if len(data) != 4 or data[0] != "bubl":
            return
        game, bet, uid = data[1], int(data[2]), int(data[3])

        # Проверяем, что кнопки жмёт именно тот, кто вызывал
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Это не твоя ставка!", show_alert=True)
            return

        # Удаляем кнопки
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass

        # Запускаем соответствующую игру
        fake_message = call.message
        fake_message.text = f"/{game} {bet}"
        fake_message.from_user = call.from_user
        if game == "pocket":
            _h_football(fake_message)
        elif game == "casino":
            _h_casino(fake_message)
        elif game == "loto":
            _h_lottery(fake_message)

        bot.answer_callback_query(call.id)

    except Exception as e:
        log.error(f"bubl_callback_handler: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)


def bet_game_handler(bot, message, chance, mult, win_texts, lose_texts):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_bet.get(uid, 0)
    if now - last < BET_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int(BET_COOLDOWN - (now - last))} сек")
        return
    _last_bet[uid] = now

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, f"❗ Укажи ставку, например: {parts[0]} 50")
        return
    bet = int(parts[1])
    if bet < MIN_BET:
        bot.reply_to(message, f"❗ Минимальная ставка {MIN_BET}")
        return

    bal = _get_balance(uid)
    if bal < bet:
        bot.reply_to(message, "❌ Недостаточно бублей")
        return

    _update_balance(uid, -bet)

    if random.random() < chance:
        win = int(round(bet * mult))
        _update_balance(uid, win)
        text = random.choice(win_texts).format(bet=bet, win=win)
    else:
        # игрок проиграл — 50% ставки уходит в сокровищницу
        _treasury_add(int(bet * 0.5))
        text = random.choice(lose_texts).format(bet=bet)

    bot.reply_to(message, f"{text}\n💰 Баланс: {_get_balance(uid)}")

# Совместимая обёртка под старое имя, как в твоём регистраторе
def _play_game(bot, message, *, chance, multiplier, win_texts, lose_texts):
    return bet_game_handler(bot, message, chance, multiplier, win_texts, lose_texts)

# === Недвижимость/работы ===
def property_buy_handler(bot, message, key):
    uid = message.from_user.id
    p = PROPERTIES[key]
    if key in _get_properties(uid):
        bot.reply_to(message, f"❗ У тебя уже есть {p['name']}")
        return
    if _get_balance(uid) < p["price"]:
        bot.reply_to(message, f"❌ Нужно {p['price']} бублей")
        return
    _update_balance(uid, -p["price"])
    _buy_property_record(uid, key)
    bot.reply_to(message, f"✅ Куплено: {p['name']} за {p['price']}")

def property_income_handler(bot, message, key):
    uid = message.from_user.id
    p = PROPERTIES[key]
    if key not in _get_properties(uid):
        bot.reply_to(message, f"❌ Нет {p['name']} (стоит {p['price']})")
        return
    now = time.time()
    last = _last_income.get((uid, key), 0)
    if now - last < p["cooldown"]:
        bot.reply_to(message, f"⏳ Подожди {int(p['cooldown'] - (now - last))} сек")
        return
    _last_income[(uid, key)] = now
    money = random.randint(*p["income"])
    _update_balance(uid, money)
    bot.reply_to(message, p["message"].format(money=money))

# Обёртки под имена, которые вызываются в регистраторе
def buy_property_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Используй: /buy hut | /buy communal\n(hut=Хижина на отшибе, communal=Коммуналка в гетто)")
        return
    key_raw = parts[1].lower()
    # допускаем русские синонимы
    if key_raw in ("hut", "хижина", "хижина_на_отшибе"):
        key = "hut"
    elif key_raw in ("communal", "коммуналка", "коммуналка_в_гетто"):
        key = "communal"
    else:
        bot.reply_to(message, "❗ Неизвестная недвижимость. Доступно: hut, communal")
        return
    property_buy_handler(bot, message, key)

def mafia_handler(bot, message):
    register_user(message)
    property_income_handler(bot, message, "hut")

def clean_handler(bot, message):
    register_user(message)
    property_income_handler(bot, message, "communal")

# === О себе/ники ===
NICK_RE = re.compile(r'^окак\s+ник\s+(.+)$', re.IGNORECASE)

def nickname_handler(bot, message):
    register_user(message)
    text = (message.text or '').strip()
    m = NICK_RE.fullmatch(text)
    if not m:
        bot.reply_to(message, "❗ Используй: Окак ник <твой ник>")
        return
    nick = m.group(1).strip()
    _set_nickname(message.from_user.id, nick)
    bot.reply_to(message, f"✅ Теперь твой ник: {nick}")

def osebe_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    nick = _get_nickname(uid)
    props = [PROPERTIES[k]["name"] for k in _get_properties(uid)] or ["Нет"]
    bot.reply_to(message, f"👤 О себе:\nИмя: {nick or message.from_user.first_name}\n"
                          f"Баланс: {_get_balance(uid)} бублей\nНедвижимость: {', '.join(props)}")

# === Топ бублей (без упоминаний @) ===
def topbubl_handler(bot, message):
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT 10"
        ).fetchall()
    if not rows:
        bot.send_message(message.chat.id, "Пока пусто.")
        return
    lines = []
    for i, (uid, bal) in enumerate(rows, 1):
        nick = _get_nickname(uid)
        if not nick:
            with db.get_connection() as conn:
                row = conn.execute("SELECT first_name FROM users WHERE user_id=?", (uid,)).fetchone()
            nick = row[0] if row else str(uid)
        lines.append(f"{i}. {nick} — 💰 {bal}")
    bot.send_message(message.chat.id, "🏆 Топ:\n" + "\n".join(lines))

# === Переводы «дать @user 100» ===
TRANSFER_RE = re.compile(r'^дать\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$', re.IGNORECASE)

def transfer_handler(bot, message):
    register_user(message)
    text = (message.text or '').strip()
    m = TRANSFER_RE.fullmatch(text)
    if not m:
        bot.reply_to(message, "❗ Используй: дать @user 100")
        return

    target_raw, amount_str = m.groups()
    amount = int(amount_str)
    if amount <= 0:
        bot.reply_to(message, "❗ Сумма должна быть положительной")
        return

    sender_id = message.from_user.id
    # находим получателя
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = row[0] if row else None

    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден в базе. Попроси его написать боту /start")
        return
    if target_id == sender_id:
        bot.reply_to(message, "❌ Нельзя переводить самому себе")
        return

    if _get_balance(sender_id) < amount:
        bot.reply_to(message, "❌ Недостаточно бублей для перевода")
        return

    _update_balance(sender_id, -amount)
    _update_balance(target_id, amount)
    bot.reply_to(message, f"✅ {amount} бублей → {target_raw}")

# === Админ: добавить/убрать бубли ===
def admin_add_remove(bot, message, mode):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        bot.reply_to(message, f"❗ Формат: /{'add_bubl' if mode=='add' else 'remove_bubl'} @user 100")
        return
    target_raw, amount_str = parts[1], parts[2]
    if not amount_str.isdigit():
        bot.reply_to(message, "❗ Сумма должна быть числом")
        return
    amount = int(amount_str)

    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = row[0] if row else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден")
        return

    if mode == "add":
        _update_balance(target_id, amount)
    else:
        _update_balance(target_id, -amount)
    bot.reply_to(message, f"✅ Баланс обновлён ({mode} {amount})")

# Обёртки под имена из регистратора
def add_bubl_handler(bot, message):
    admin_add_remove(bot, message, "add")

def remove_bubl_handler(bot, message):
    admin_add_remove(bot, message, "remove")

# === Сообщение от лица бота (только владелец) ===
def xhp_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Ты за кого себя пытаешься выдать, малой?")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /xhp <текст>")
        return
    bot.send_message(message.chat.id, parts[1])

# === Дуэли /sf ===
_active_duels = {}              # chat_id -> duel_obj
_chat_duel_cooldown = {}        # chat_id -> last_end_ts
_player_duel_cooldown = {}      # user_id -> last_end_ts

CHAT_COOLDOWN = 60
PLAYER_COOLDOWN = 120
INVITE_TIMEOUT = 35
BETTING_PERIOD = 45

WEAK_HIT_TEXTS = [
    "{attacker} наносит слабый удар — {dmg} урона!",
    "Лёгкий удар от {attacker}: -{dmg} HP."
]
STRONG_HIT_TEXTS = [
    "{attacker} мощно бьёт — {dmg} HP!",
    "Сильный удар от {attacker}: -{dmg} HP."
]
CRIT_HIT_TEXTS = [
    "Критический удар! {attacker} сносит {dmg} HP!",
    "Нокаут-атака от {attacker}: -{dmg} HP!"
]

def _inc_duel_win(user_id, amount=1):
    with db.get_connection() as conn:
        conn.execute("""INSERT INTO duel_stats (user_id,wins) VALUES (?,?)
                        ON CONFLICT(user_id) DO UPDATE SET wins = wins + ?""",
                     (user_id, amount, amount))
        conn.commit()

def _add_bettor_win(user_id, amount):
    with db.get_connection() as conn:
        conn.execute("""INSERT INTO bettor_stats (user_id,total_won) VALUES (?,?)
                        ON CONFLICT(user_id) DO UPDATE SET total_won = total_won + ?""",
                     (user_id, amount, amount))
        conn.commit()

def _display_name(user_id):
    # okak-ник > first_name > id
    nick = _get_nickname(user_id)
    if nick:
        return nick
    with db.get_connection() as conn:
        row = conn.execute("SELECT first_name FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row and row[0] else str(user_id)

def sf_command_handler(bot, message):
    """
    /sf @username
    """
    chat_id = message.chat.id
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /sf @user")
        return
    target_raw = parts[1]
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден в базе. Пусть напишет /start боту.")
        return

    challenger = message.from_user.id
    if target_id == challenger:
        bot.reply_to(message, "❌ Нельзя вызвать на дуэль самого себя.")
        return

    now = time.time()
    if now - _chat_duel_cooldown.get(chat_id, 0) < CHAT_COOLDOWN:
        bot.reply_to(message, f"⏳ В этом чате недавно была дуэль. Подожди {int(CHAT_COOLDOWN - (now - _chat_duel_cooldown[chat_id]))} сек.")
        return
    if now - _player_duel_cooldown.get(challenger, 0) < PLAYER_COOLDOWN:
        bot.reply_to(message, f"⏳ Ты недавно участвовал в дуэли. Подожди {int(PLAYER_COOLDOWN - (now - _player_duel_cooldown[challenger]))} сек.")
        return
    if now - _player_duel_cooldown.get(target_id, 0) < PLAYER_COOLDOWN:
        bot.reply_to(message, "⏳ Цель недавно участвовала в дуэли. Попробуй позже.")
        return
    if chat_id in _active_duels:
        bot.reply_to(message, "❗ В чате уже идёт дуэль. Подожди её окончания.")
        return

    duel = {
        'chat_id': chat_id,
        'challenger': challenger,
        'target': target_id,
        'state': 'invited',
        'invite_timer': None,
        'bet_timer': None,
        'bets': {},
        'placed_sums': {},
        'created_at': now
    }
    _active_duels[chat_id] = duel

    disp_chall = _display_name(challenger)
    disp_target = _display_name(target_id)
    bot.send_message(chat_id, f"⚔️ Дуэль: {disp_chall} вызывает на дуэль {disp_target}.\n{disp_target}, ты можешь принять командой /sf_accept или отклонить /sf_decline в течение {INVITE_TIMEOUT} сек.")

    def invite_timeout():
        try:
            d = _active_duels.get(chat_id)
            if d and d['state'] == 'invited':
                del _active_duels[chat_id]
                bot.send_message(chat_id, "⌛ Время на ответ истекло — дуэль отменена.")
        except Exception as e:
            log.error(f"invite_timeout error: {e}")

    t = threading.Timer(INVITE_TIMEOUT, invite_timeout)
    duel['invite_timer'] = t
    t.start()

def sf_accept_handler(bot, message):
    chat_id = message.chat.id
    register_user(message)
    d = _active_duels.get(chat_id)
    if not d or d['state'] != 'invited':
        bot.reply_to(message, "❗ Нет активного приглашения на дуэль в этом чате.")
        return
    if message.from_user.id != d['target']:
        bot.reply_to(message, "❌ Ты не адресат этого приглашения.")
        return

    if d['invite_timer']:
        d['invite_timer'].cancel()

    d['state'] = 'betting'
    d['bets'] = {}
    d['placed_sums'] = {}
    d['betting_started_at'] = time.time()

    bot.send_message(chat_id, f"✅ {_display_name(d['target'])} принял дуэль! Начинается фаза ставок ({BETTING_PERIOD} секунд).\nСтавьте: /bet @игрок сумма (только 1 ставка на дуэль).")

    def end_betting():
        try:
            dd = _active_duels.get(chat_id)
            if not dd or dd['state'] != 'betting':
                return
            dd['state'] = 'running'
            bot.send_message(chat_id, "⏳ Фаза ставок закончена. Подготовка к дуэли...")
            threading.Thread(target=_run_duel, args=(bot, dd), daemon=True).start()
        except Exception as e:
            log.error(f"end_betting err: {e}")

    bt = threading.Timer(BETTING_PERIOD, end_betting)
    d['bet_timer'] = bt
    bt.start()

def sf_decline_handler(bot, message):
    chat_id = message.chat.id
    register_user(message)
    d = _active_duels.get(chat_id)
    if not d or d['state'] != 'invited':
        bot.reply_to(message, "❗ Нет активного приглашения на дуэль в этом чате.")
        return
    if message.from_user.id != d['target']:
        bot.reply_to(message, "❌ Ты не адресат этого приглашения.")
        return
    if d['invite_timer']:
        d['invite_timer'].cancel()
    del _active_duels[chat_id]
    bot.send_message(chat_id, "❌ Дуэль отклонена.")

BET_RE = re.compile(r'^/bet\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$', re.IGNORECASE)

def bet_handler(bot, message):
    chat_id = message.chat.id
    register_user(message)
    d = _active_duels.get(chat_id)
    if not d or d['state'] != 'betting':
        bot.reply_to(message, "❗ Сейчас нельзя делать ставки (нет фазы ставок).")
        return

    m = BET_RE.fullmatch((message.text or "").strip())
    if not m:
        bot.reply_to(message, "❗ Формат: /bet @user сумма")
        return

    target_raw, amount_s = m.groups()
    amount = int(amount_s)
    bettor = message.from_user.id

    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = row[0] if row else None

    if not target_id or target_id not in (d['challenger'], d['target']):
        bot.reply_to(message, "❗ Можно ставить только на одного из участников дуэли.")
        return
    if bettor in d['bets']:
        bot.reply_to(message, "❗ Ты уже сделал ставку в этой дуэли (только одна ставка).")
        return
    if amount <= 0:
        bot.reply_to(message, "❗ Сумма должна быть положительной.")
        return

    bal = _get_balance(bettor)
    if bal < amount:
        bot.reply_to(message, "❌ Недостаточно бублей для ставки.")
        return

    _update_balance(bettor, -amount)
    d['bets'][bettor] = {'on': target_id, 'amount': amount}
    d['placed_sums'][target_id] = d['placed_sums'].get(target_id, 0) + amount

    lines = []
    for b, info in d['bets'].items():
        lines.append(f"{_display_name(b)} → {info['amount']} на {_display_name(info['on'])}")
    bot.send_message(chat_id, "📋 Ставка принята. Текущие ставки:\n" + ("\n".join(lines) if lines else "Нет ставок"))

def _run_duel(bot, duel):
    chat_id = duel['chat_id']
    try:
        now = time.time()
        if now - _chat_duel_cooldown.get(chat_id, 0) < CHAT_COOLDOWN:
            bot.send_message(chat_id, "❗ Нельзя начать дуэль — чат в кулдауне.")
            del _active_duels[chat_id]
            return

        challenger = duel['challenger']
        target = duel['target']
        _player_duel_cooldown[challenger] = now
        _player_duel_cooldown[target] = now

        def player_hp(uid):
            base = 100
            props = _get_properties(uid)
            if 'hut' in props:
                base += 15
            if 'communal' in props:
                base += 25
            return base

        hp_ch = player_hp(challenger)
        hp_tg = player_hp(target)

        total_pot = sum(v['amount'] for v in duel['bets'].values()) if duel['bets'] else 0
        s_ch = duel['placed_sums'].get(challenger, 0)
        s_tg = duel['placed_sums'].get(target, 0)
        bot.send_message(chat_id, f"⚔️ Дуэль начинается: {_display_name(challenger)} vs {_display_name(target)}\nHP: {hp_ch} / {hp_tg}\nСтавки: на {_display_name(challenger)} — {s_ch}, на {_display_name(target)} — {s_tg}. Всего в банке: {total_pot} бублей")

        attacker, defender = (challenger, target) if random.random() < 0.5 else (target, challenger)
        hp = {challenger: hp_ch, target: hp_tg}
        round_no = 0

        while hp[challenger] > 0 and hp[target] > 0:
            round_no += 1
            r = random.random()
            if r < 0.40:
                dmg = random.randint(5, 12)
                text = random.choice(WEAK_HIT_TEXTS)
            elif r < 0.80:
                dmg = random.randint(13, 20)
                text = random.choice(STRONG_HIT_TEXTS)
            else:
                dmg = random.randint(21, 25)
                text = random.choice(CRIT_HIT_TEXTS)

            hp[defender] -= dmg
            if hp[defender] < 0:
                hp[defender] = 0

            bot.send_message(chat_id, text.format(attacker=_display_name(attacker), dmg=dmg) +
                             f"\n🩺 {_display_name(attacker)}: {hp[attacker]} HP | {_display_name(defender)}: {hp[defender]} HP")

            time.sleep(2.5)
            attacker, defender = defender, attacker

            if round_no > 55:
                bot.send_message(chat_id, "⚠️ Дуэль заняла слишком много ходов — ничья. Возврат ставок.")
                for b, info in duel['bets'].items():
                    _update_balance(b, info['amount'])
                del _active_duels[chat_id]
                _chat_duel_cooldown[chat_id] = time.time()
                return

        winner = challenger if hp[challenger] > 0 else target
        loser = target if winner == challenger else challenger

        bot.send_message(chat_id, f"🏁 Дуэль закончена! Победитель: {_display_name(winner)}. Поздравляю!")

        total_on_winner = duel['placed_sums'].get(winner, 0)
        total_on_loser = duel['placed_sums'].get(loser, 0)
        total_pot = total_on_winner + total_on_loser

        total_bettors_payout = 0
        if total_pot > 0 and total_on_winner > 0:
            payout_multiplier = total_pot / total_on_winner
            for bidder, info in duel['bets'].items():
                if info['on'] == winner:
                    bet_amount = info['amount']
                    payout = int(round(bet_amount * payout_multiplier))
                    _update_balance(bidder, payout)
                    total_bettors_payout += payout
                    _add_bettor_win(bidder, payout)
        winner_reward = int(total_bettors_payout * 2)
        if winner_reward > 0:
            _update_balance(winner, winner_reward)
            bot.send_message(chat_id, f"🏆 Победитель {_display_name(winner)} получает бонус от банка: {winner_reward} бублей!")

        loser_balance_before = _get_balance(loser)
        penalty = int(math.floor(loser_balance_before * 0.32))
        if penalty > 0:
            _update_balance(loser, -penalty)
            bot.send_message(chat_id, f"⚠️ Проигравший {_display_name(loser)} теряет {penalty} бублей за свой проигрыш(")

        _inc_duel_win(winner, 1)
        bot.send_message(chat_id, f"💰 Балансы: {_display_name(winner)} — {_get_balance(winner)}, {_display_name(loser)} — {_get_balance(loser)}")

        _chat_duel_cooldown[chat_id] = time.time()
        _player_duel_cooldown[winner] = time.time()
        _player_duel_cooldown[loser] = time.time()

    except Exception as e:
        log.error(f"duel run error: {e}")
        bot.send_message(chat_id, "❌ Ошибка при выполнении дуэли.")
    finally:
        try:
            if chat_id in _active_duels:
                del _active_duels[chat_id]
        except:
            pass
def topsf_handler(bot, message, limit=10):
    try:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT user_id, wins FROM duel_stats ORDER BY wins DESC LIMIT ?", (limit,)).fetchall()
        if not rows:
            bot.reply_to(message, "❗ Пока нет побед в дуэлях")
            return
        lines = [f"{i}. {_display_name(uid)} — {wins} побед" for i, (uid, wins) in enumerate(rows, 1)]
        bot.send_message(message.chat.id, "🏅 Топ победителей дуэлей:\n\n" + "\n".join(lines))
    except Exception as e:
        log.error(f"topsf err: {e}")
        bot.reply_to(message, "❌ Ошибка при получении топа")

def topst_handler(bot, message, limit=10):
    try:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT user_id, total_won FROM bettor_stats ORDER BY total_won DESC LIMIT ?", (limit,)).fetchall()
        if not rows:
            bot.reply_to(message, "❗ Пока нет данных по ставочникам")
            return
        lines = [f"{i}. {_display_name(uid)} — всего выиграно {total_won} бублей" for i, (uid, total_won) in enumerate(rows, 1)]
        bot.send_message(message.chat.id, "🏅 Топ ставочников:\n\n" + "\n".join(lines))
    except Exception as e:
        log.error(f"topst err: {e}")
        bot.reply_to(message, "❌ Ошибка при получении топа")


#===Сокровищница===

# Кулдауны для сокровищницы: (user_id, action) -> ts
_tre_cd = {}
TRE_ACTION_COOLDOWN = 30 * 60  # 30 минут

def _tre_cooldown_left(user_id: int, action: str) -> int:
    now = time.time()
    last = _tre_cd.get((user_id, action), 0)
    left = int(TRE_ACTION_COOLDOWN - (now - last))
    return left if left > 0 else 0

def _tre_touch_cd(user_id: int, action: str):
    _tre_cd[(user_id, action)] = time.time()

def _tre_markup(origin_uid: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("🦹 Ограбить", callback_data=f"tre_rob_{origin_uid}"),
        types.InlineKeyboardButton("📥 Положить", callback_data=f"tre_put_{origin_uid}")
    )
    kb.row(
        types.InlineKeyboardButton("🤲 Попросить", callback_data=f"tre_ask_{origin_uid}"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data=f"tre_close_{origin_uid}")
    )
    return kb

def tre_show_handler(bot, message):
    register_user(message)
    bal = _treasury_get()
    text = f"🏛 Сокровищница\nБаланс: {bal} бублей"
    bot.send_message(message.chat.id, text, reply_markup=_tre_markup(message.from_user.id))

def tre_callback_handler(bot, call):
    try:
        data = (call.data or "")
        if not data.startswith("tre_"):
            return
        parts = data.split("_")
        # форматы: tre_rob_<origin_uid>, tre_put_<origin_uid>, tre_ask_<origin_uid>, tre_close_<origin_uid>
        if len(parts) != 3:
            return
        action, origin_uid_s = parts[1], parts[2]
        origin_uid = int(origin_uid_s)
        uid = call.from_user.id

        # Ограничение на закрытие: только инициатор может закрыть
        if action == "close":
            if uid != origin_uid and uid != OWNER_ID:
                bot.answer_callback_query(call.id, "❌ Это меню не ты открывал", show_alert=True)
                return
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            return

        # Кулдаун для каждого действия отдельно
        left = _tre_cooldown_left(uid, action)
        if left > 0:
            bot.answer_callback_query(call.id, f"⏳ Подожди {left//60} мин {left%60} сек", show_alert=True)
            return

        # Действия
        if action == "rob":
            # 20% успех; при успехе ворует 5–15% казны
            success = random.random() < 0.20
            if success:
                tre_bal = _treasury_get()
                if tre_bal <= 0:
                    bot.answer_callback_query(call.id, "🏛 Пусто — нечего воровать", show_alert=True)
                    return
                percent = random.randint(5, 15) / 100.0
                steal = max(1, int(tre_bal * percent))
                got = _treasury_sub(steal)
                if got > 0:
                    _update_balance(uid, got)
                    bot.answer_callback_query(call.id, f"🦹 Успех! Украдено {got} бублей", show_alert=True)
                else:
                    bot.answer_callback_query(call.id, "🏛 Не удалось — казна изменилась", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "🚨 Поймали! Ничего не удалось забрать", show_alert=True)
            _tre_touch_cd(uid, "rob")

        elif action == "put":
            # Положить 1% от баланса игрока
            bal = _get_balance(uid)
            amount = int(bal * 0.01)
            if amount <= 0:
                bot.answer_callback_query(call.id, "💸 Слишком мало для вклада", show_alert=True)
                return
            _update_balance(uid, -amount)
            _treasury_add(amount)
            bot.answer_callback_query(call.id, f"📥 Внесено {amount} бублей", show_alert=True)
            _tre_touch_cd(uid, "put")

        elif action == "ask":
            # Попросить 0.1% от казны
            tre_bal = _treasury_get()
            amount = int(tre_bal * 0.001)  # 0.1%
            if amount <= 0:
                bot.answer_callback_query(call.id, "🏛 Недостаточно средств в сокровищнице", show_alert=True)
                return
            taken = _treasury_sub(amount)
            if taken > 0:
                _update_balance(uid, taken)
                bot.answer_callback_query(call.id, f"🤲 Получено {taken} бублей", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "🏛 Недостаточно средств в сокровищнице", show_alert=True)
            _tre_touch_cd(uid, "ask")

        # Обновляем текст баланса под сообщением
        try:
            new_bal = _treasury_get()
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"🏛 Сокровищница\nБаланс: {new_bal} бублей",
                reply_markup=_tre_markup(origin_uid)
            )
        except Exception:
            # если сообщение уже удалили/нельзя редактировать — игнор
            pass

    except Exception as e:
        log.error(f"tre_callback_handler error: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        
            
# === /chests ===
_last_chests = {}  # user_id -> ts
CHEST_COOLDOWN = 180   # 3 минуты

SQUARES = ["🟥", "🟦", "🟩", "🟨", "🟪", "⬜️", "🟫", "⬛️"]

def chests_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_chests.get(uid, 0)
    if now - last < CHEST_COOLDOWN:
        bot.reply_to(
            message,
            f"⏳ Подожди {int(CHEST_COOLDOWN - (now - last))} сек, чтобы открыть сундуки снова!"
        )
        return
    _last_chests[uid] = now

    chosen = random.sample(SQUARES, 3)
    markup = types.InlineKeyboardMarkup()
    for i, sq in enumerate(chosen):
        cb = f"chests_{uid}_{i}"
        markup.add(types.InlineKeyboardButton(sq, callback_data=cb))

    bot.send_message(message.chat.id, "🗝️ Ты отчаянно отправился в пещеру за сундуками из легенды. Легенда права! Выбирай сундук:", reply_markup=markup)    
def chests_callback_handler(bot, call):
    try:
        data = call.data.split("_")
        if len(data) != 3 or data[0] != "chests":
            return
        uid = int(data[1])
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Это не твои сундуки", show_alert=True)
            return

        # убираем кнопки
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass

        # генерим результат
        roll = random.random()
        if roll < 0.4:
            # выигрыш
            amount = random.randint(2000, 6000)
            _update_balance(uid, amount)
            bot.send_message(call.message.chat.id, f"🎉 Сундук, который ты открыл, оказался щедрым! Ты нашёл +{amount} бублей.\n💰 Баланс: {_get_balance(uid)}")
        elif roll < 0.7:
            # проигрыш (баланс может уйти в минус)
            amount = random.randint(1000, 4000)
            _update_balance(uid, -amount)
            bot.send_message(call.message.chat.id, f"💀 Сундук владеет чёрной магией. Забирать твои деньги не было в его планах, но ты его заставил. Минус {amount} бублей.\n💰 Баланс: {_get_balance(uid)}")
        else:
            # ничего
            bot.send_message(call.message.chat.id, "📦 Сундук пуст... Может, он просто спит.")

        bot.answer_callback_query(call.id)

    except Exception as e:
        log.error(f"chests_callback_handler: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        
# === Регистрация всех хэндлеров ===
def register_extra_handlers(bot):

    # ID и инфо
    @bot.message_handler(commands=['id'])
    def _h_id(m): id_handler(bot, m)

    @bot.message_handler(commands=['whoami'])
    def _h_whoami(m): whoami_handler(bot, m)

    # Реакция на "спасибо"
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower() == "спасибо")
    def _h_thanks(m): thanks_handler(bot, m)

    # Баланс
    @bot.message_handler(commands=['balance'])
    def _h_balance(m): balance_handler(bot, m)

    # Просьба денег на улице (/bomj)
    @bot.message_handler(commands=['bomj'])
    def _h_bomj(m): street_handler(bot, m)
    
    # /bubl
    @bot.message_handler(commands=['bubl'])
    def _h_bubl(m): bubl_handler(bot, m)

    # callback для bubl
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("bubl_"))
    def _h_bubl_cb(call): bubl_callback_handler(bot, call)

    # Игры (оставлены твои сообщения выигрыша/проигрыша)
    @bot.message_handler(commands=['pocket'])
    def _h_pocket(m): _play_game(
        bot, m,
        chance=0.69, multiplier=1.4,
        win_texts=[
            "😎Молодец, воришка. Ты потерял свои деньги на ходу, но получил больше - аж {win} бублей!",
            "✨❄️Моя школа! {win} тебе начислено за твой проворот."
        ],
        lose_texts=[
            "🙄Ну ты и лоханулся... мало того, что ты ничего не украл, так у тебя украли {bet}!",
            "🤵Мафия тобой разочарована. Мы оштрафовали тебя на {bet}, чтоб не втыкал."
        ]
    )

    @bot.message_handler(commands=['casino'])
    def _h_casino(m): _play_game(
        bot, m,
        chance=0.35, multiplier=3.0,
        win_texts=[
            "🎰 Джекпот! {win} бублей за ставку {bet}.",
            "🎲 Везёт! Забираешь {win} бублей (ставка {bet})."
        ],
        lose_texts=[
            "🃏 Крупье улыбается… Ставка {bet} ушла в дом.",
            "💸 Рулетка безжалостна. Минус {bet}."
        ]
    )

    @bot.message_handler(commands=['loto'])
    def _h_loto(m): _play_game(
        bot, m,
        chance=0.08, multiplier=18.0,
        win_texts=[
            "🎟 Счастливый билет! +{win} бублей (ставка {bet}).",
            "🌟 Умный человек в очках выиграл {win} бублей скачать обои"
        ],
        lose_texts=[
            "🪙 Ой-ой-ой, не повезло. Ставка в аж {bet} бублей ушла в воздух.",
            "🙃 Сегодня не твой день. Минус {bet}."
        ]
    )

    # Перевод денег ("дать @вася 100")
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("дать "))
    def _h_transfer(m): transfer_handler(bot, m)

    # Покупка/работы недвижимости
    @bot.message_handler(commands=['buy'])
    def _h_buy(m): buy_property_handler(bot, m)

    @bot.message_handler(commands=['mafia'])
    def _h_mafia(m): mafia_handler(bot, m)

    @bot.message_handler(commands=['clean'])
    def _h_clean(m): clean_handler(bot, m)

    # Ник и "о себе"
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and re.match(r"(?i)^окак\s+ник\s+(.+)$", (m.text or "").strip()))
    def _h_setnick(m): nickname_handler(bot, m)

    @bot.message_handler(commands=['osebe'])
    def _h_osebe(m): osebe_handler(bot, m)

    # Топы
    @bot.message_handler(commands=['topbubl'])
    def _h_topbubl(m): topbubl_handler(bot, m)

    @bot.message_handler(commands=['topsf'])
    def _h_topsf(m): topsf_handler(bot, m)

    @bot.message_handler(commands=['topst'])
    def _h_topst(m): topst_handler(bot, m)

    # Админские команды
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("/add_bubl"))
    def _h_add(m): add_bubl_handler(bot, m)

    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("/remove_bubl"))
    def _h_remove(m): remove_bubl_handler(bot, m)

    # Сообщение от имени бота
    @bot.message_handler(commands=['xhp'])
    def _h_xhp(m): xhp_handler(bot, m)

    # Дуэли
    @bot.message_handler(commands=['sf'])
    def _h_sf(m): sf_command_handler(bot, m)

    @bot.message_handler(commands=['sf_accept'])
    def _h_sf_accept(m): sf_accept_handler(bot, m)

    @bot.message_handler(commands=['sf_decline'])
    def _h_sf_decline(m): sf_decline_handler(bot, m)

    @bot.message_handler(commands=['bet'])
    def _h_bet(m): bet_handler(bot, m)
    
    # Обнуление балансов
    @bot.message_handler(commands=['wipebubl'])
    def _h_wipebubl(m): wipebubl_handler(bot, m)

    # Luck-игра
    @bot.message_handler(commands=['luck'])
    def _h_luck(m): luck_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("luck_"))
    def _h_luck_cb(call): luck_callback_handler(bot, call)

    # Сокровищница
    @bot.message_handler(commands=['tre'])
    def _h_tre(m): tre_show_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("tre_"))
    def _h_tre_cb(call): tre_callback_handler(bot, call)
    
    # /chests
    @bot.message_handler(commands=['chests'])
    def _h_chests(m): chests_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("chests_"))
    def _h_chests_cb(call): chests_callback_handler(bot, call)
