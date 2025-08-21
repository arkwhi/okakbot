import random, re, logging, time
from database import Database
from handlers import register_user

log = logging.getLogger(__name__)
db = Database()

# === Конфиг ===
MIN_RANDOM = 5
MAX_RANDOM = 150
MIN_BET = 15
BET_COOLDOWN = 7
STREET_COOLDOWN = 15

OWNER_ID = 5758264503

PROPERTIES = {
    "hut": {
        "name": "Хижина на отшибе",
        "price": 20000,
        "command": "mafia",
        "cooldown": 20,
        "income": (100, 300),
        "message": "🥷Ты выполнил маленькое задание от мафии, получив зарплату {money} бублей",
    },
    "communal": {
        "name": "Коммуналка в гетто",
        "price": 95000,
        "command": "clean",
        "cooldown": 30,
        "income": (400, 800),
        "message": "🫧 🧽Ты помыл пол в соседнем общежитии, и тебе скинулись {money} бублей",
    }
}

# === Таблицы ===
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
        conn.commit()

_ensure_tables()

# === Баланс ===
def _get_balance(user_id: int) -> int:
    row = db.get_connection().execute("SELECT balance FROM balances WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else 0

def _update_balance(user_id: int, delta: int):
    with db.get_connection() as conn:
        conn.execute("""INSERT INTO balances (user_id, balance) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance""", (user_id, delta))
        conn.execute("UPDATE balances SET balance=0 WHERE user_id=? AND balance<0", (user_id,))
        conn.commit()

# === Недвижимость ===
def _buy_property(user_id, key):
    with db.get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO properties (user_id, property_key) VALUES (?, ?)", (user_id, key))
        conn.commit()

def _get_properties(user_id):
    rows = db.get_connection().execute("SELECT property_key FROM properties WHERE user_id=?", (user_id,)).fetchall()
    return [r[0] for r in rows]

# === Ники ===
def _set_nickname(user_id, nick):
    with db.get_connection() as conn:
        conn.execute("""INSERT INTO nicknames (user_id, nickname) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname""", (user_id, nick))
        conn.commit()

def _get_nickname(user_id):
    row = db.get_connection().execute("SELECT nickname FROM nicknames WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row else None

# === Кулдауны ===
_last_bet = {}
_last_income = {}
_last_street = {}

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
    uid = message.from_user.id
    now = time.time()
    if now - _last_street.get(uid, 0) < STREET_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int(STREET_COOLDOWN - (now-_last_street[uid]))} сек")
        return
    _last_street[uid] = now
    amount = random.randint(MIN_RANDOM, MAX_RANDOM)
    _update_balance(uid, amount)
    bot.reply_to(message, f"🪙 Ты выпросил {amount} бублей на улице!\n💰 Баланс: {_get_balance(uid)}")

# === Игры ===
def bet_game_handler(bot, message, chance, mult, win_texts, lose_texts):
    uid = message.from_user.id
    now = time.time()
    if now - _last_bet.get(uid, 0) < BET_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int(BET_COOLDOWN-(now-_last_bet[uid]))} сек")
        return
    _last_bet[uid] = now

    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, f"❗ Укажи ставку, например: {parts[0]} 50")
        return
    bet = int(parts[1])
    if bet < MIN_BET:
        bot.reply_to(message, f"❗ Минимальная ставка {MIN_BET}")
        return
    if _get_balance(uid) < bet:
        bot.reply_to(message, "❌ Недостаточно бублей")
        return
    _update_balance(uid, -bet)

    if random.random() < chance:
        win = int(round(bet*mult))
        _update_balance(uid, win)
        text = random.choice(win_texts).format(bet=bet, win=win)
    else:
        text = random.choice(lose_texts).format(bet=bet)
    bot.reply_to(message, f"{text}\n💰 Баланс: {_get_balance(uid)}")

# === Недвижимость/работы ===
def property_buy_handler(bot, message, key):
    uid = message.from_user.id
    p = PROPERTIES[key]
    if _get_balance(uid) < p["price"]:
        bot.reply_to(message, f"❌ Нужно {p['price']} бублей")
        return
    if key in _get_properties(uid):
        bot.reply_to(message, f"❗ У тебя уже есть {p['name']}")
        return
    _update_balance(uid, -p["price"])
    _buy_property(uid, key)
    bot.reply_to(message, f"✅ Куплено: {p['name']} за {p['price']}")

def property_income_handler(bot, message, key):
    uid = message.from_user.id
    p = PROPERTIES[key]
    if key not in _get_properties(uid):
        bot.reply_to(message, f"❌ Нет {p['name']} (стоит {p['price']})")
        return
    now = time.time()
    if now - _last_income.get((uid, key), 0) < p["cooldown"]:
        bot.reply_to(message, f"⏳ Подожди {int(p['cooldown']-(now-_last_income[(uid,key)]))} сек")
        return
    _last_income[(uid,key)] = now
    money = random.randint(*p["income"])
    _update_balance(uid, money)
    bot.reply_to(message, p["message"].format(money=money))

# === О себе/ники ===
def osebe_handler(bot, message):
    uid = message.from_user.id
    nick = _get_nickname(uid)
    props = [PROPERTIES[k]["name"] for k in _get_properties(uid)] or ["Нет"]
    bot.reply_to(message, f"👤 О себе:\nИмя: {nick or message.from_user.first_name}\n"
                          f"Баланс: {_get_balance(uid)} бублей\nНедвижимость: {', '.join(props)}")

NICK_RE = re.compile(r'^окак\s+ник\s+(.+)$', re.IGNORECASE)

def nickname_handler(bot, message):
    text = (message.text or '').strip()
    m = NICK_RE.fullmatch(text)
    if not m:
        bot.reply_to(message, "❗ Используй: Окак ник <твой ник>")
        return
    nick = m.group(1).strip()
    _set_nickname(message.from_user.id, nick)
    bot.reply_to(message, f"✅ Теперь твой ник: {nick}")

'''def nickname_handler(bot, message):
    m = re.match(r"(?i)^окак\s+ник\s+(.+)$", message.text.strip())
    if not m: return
    _set_nickname(message.from_user.id, m.group(1).strip())
    bot.reply_to(message, f"✅ Теперь твой ник: {m.group(1).strip()}")" '''

# === Топ ===
def topbubl_handler(bot, message):
    rows = db.get_connection().execute("SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT 10").fetchall()
    lines=[]
    for i,(uid,bal) in enumerate(rows,1):
        nick = _get_nickname(uid)
        if not nick:
            row=db.get_connection().execute("SELECT first_name FROM users WHERE user_id=?", (uid,)).fetchone()
            nick=row[0] if row else str(uid)
        lines.append(f"{i}. {nick} — 💰 {bal}")
    bot.send_message(message.chat.id, "🏆 Топ:\n"+"\n".join(lines))

# === Переводы ===
import re

TRANSFER_RE = re.compile(r'^дать\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$', re.IGNORECASE)

def transfer_handler(bot, message):
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
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        row = db.get_connection().execute(
            "SELECT user_id FROM users WHERE username=?",
            (target_raw.lstrip("@"),)
        ).fetchone()
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
'''def transfer_handler(bot, message):
    m = re.match(r"(?i)^дать\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$", message.text.strip())
    if not m:
        bot.reply_to(message, "❗ Используй: дать @user 100")
        return
    target_raw, amount_str = m.groups()
    amount=int(amount_str)
    if amount<=0: return
    sender=message.from_user.id
    bal=_get_balance(sender)
    if bal<amount:
        bot.reply_to(message,"❌ Недостаточно средств")
        return
    if target_raw.isdigit():
        target_id=int(target_raw)
    else:
        row=db.get_connection().execute("SELECT user_id FROM users WHERE username=?",(target_raw.lstrip("@"),)).fetchone()
        target_id=row[0] if row else None
    if not target_id:
        bot.reply_to(message,"❌ Пользователь не найден (/start)")
        return
    if target_id==sender:
        bot.reply_to(message,"❌ Самому себе нельзя")
        return
    _update_balance(sender,-amount)
    _update_balance(target_id,amount)
    bot.reply_to(message,f"✅ {amount} бублей → {target_raw}")'''

# === Админ ===
def admin_add_remove(bot,message,mode):
    if message.from_user.id!=OWNER_ID:
        bot.reply_to(message,"❌ Нет доступа");return
    parts=message.text.split()
    if len(parts)<3: return
    target_raw,amount_str=parts[1],parts[2]
    if not amount_str.isdigit():return
    amount=int(amount_str)
    if target_raw.isdigit(): target_id=int(target_raw)
    else:
        row=db.get_connection().execute("SELECT user_id FROM users WHERE username=?",(target_raw.lstrip("@"),)).fetchone()
        target_id=row[0] if row else None
    if not target_id: return
    if mode=="add": _update_balance(target_id,amount)
    else: _update_balance(target_id,-amount)
    bot.reply_to(message,f"✅ Баланс обновлён ({mode} {amount})")

def xhp_handler(bot,message):
    if message.from_user.id!=OWNER_ID:
        bot.reply_to(message,"❌ Нет доступа");return
    parts=message.text.split(maxsplit=1)
    if len(parts)<2:return
    bot.send_message(message.chat.id, parts[1])



# === DUEL /sf system ===
import threading, random, time, math, re, logging
log = logging.getLogger(__name__)

# Зависимости (должны быть определены в файле):
# db (Database instance), register_user(message), _get_balance(user_id),
# _update_balance(user_id, delta), _get_properties(user_id), PROPERTIES dict, _get_nickname(user_id)
# Если у тебя нет какой-то функции — создай её как в основном extra_handlers.

# Создаём таблицы статистики, если их нет
def _ensure_duel_tables():
    try:
        with db.get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS duel_stats (
                user_id INTEGER PRIMARY KEY,
                wins INTEGER DEFAULT 0
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS bettor_stats (
                user_id INTEGER PRIMARY KEY,
                total_won INTEGER DEFAULT 0
            )""")
            conn.commit()
    except Exception as e:
        log.error(f"duel: cannot ensure tables: {e}")

_ensure_duel_tables()

# Внутренние структуры (в памяти)
_active_duels = {}   # chat_id -> duel_obj
# duel_obj structure:
# {
#   'chat_id': int,
#   'challenger': user_id,
#   'target': user_id,
#   'state': 'invited'|'betting'|'running'|'finished',
#   'invite_timer': threading.Timer,
#   'bet_timer': threading.Timer,
#   'bets': { bettor_id: {'on': user_id, 'amount': int} },
#   'placed_sums': { user_id: total_on_user },
#   'created_at': timestamp
# }

_chat_duel_cooldown = {}   # chat_id -> last_end_ts
_player_duel_cooldown = {} # user_id -> last_end_ts

CHAT_COOLDOWN = 60   # sec between duels in chat
PLAYER_COOLDOWN = 120  # sec between duels per player
INVITE_TIMEOUT = 25
BETTING_PERIOD = 30

# Attack texts (можешь менять)
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

# Helper functions for stats
def _inc_duel_win(user_id, amount=1):
    try:
        with db.get_connection() as conn:
            conn.execute("INSERT INTO duel_stats (user_id,wins) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET wins = wins + ?",
                         (user_id, amount, amount))
            conn.commit()
    except Exception as e:
        log.error(f"duel: inc duel win error: {e}")

def _add_bettor_win(user_id, amount):
    try:
        with db.get_connection() as conn:
            conn.execute("INSERT INTO bettor_stats (user_id,total_won) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET total_won = total_won + ?",
                         (user_id, amount, amount))
            conn.commit()
    except Exception as e:
        log.error(f"duel: add bettor stat error: {e}")

# get display name (use okak nick if present)
def _display_name(user_id):
    try:
        nick_row = db.get_connection().execute("SELECT nickname FROM nicknames WHERE user_id=?", (user_id,)).fetchone()
        if nick_row and nick_row[0]:
            return nick_row[0]
    except:
        pass
    try:
        row = db.get_connection().execute("SELECT first_name FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0]:
            return row[0]
    except:
        pass
    return str(user_id)

# Create duel
def sf_command_handler(bot, message):
    """
    Usage: /sf @username
    """
    chat_id = message.chat.id
    register_user(message)
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /sf @user")
        return
    target_raw = parts[1]
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        target_id_row = db.get_connection().execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
        target_id = target_id_row[0] if target_id_row else None

    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден в базе. Пусть напишет /start боту.")
        return
    challenger = message.from_user.id
    if target_id == challenger:
        bot.reply_to(message, "❌ Нельзя вызвать на дуэль самого себя.")
        return

    # Check chat cooldown
    now = time.time()
    last_chat = _chat_duel_cooldown.get(chat_id, 0)
    if now - last_chat < CHAT_COOLDOWN:
        bot.reply_to(message, f"⏳ В этом чате недавно была дуэль. Подожди {int(CHAT_COOLDOWN - (now-last_chat))} сек.")
        return

    # Check player cooldowns
    last_chall = _player_duel_cooldown.get(challenger, 0)
    last_target = _player_duel_cooldown.get(target_id, 0)
    if now - last_chall < PLAYER_COOLDOWN:
        bot.reply_to(message, f"⏳ Ты недавно участвовал в дуэли. Подожди {int(PLAYER_COOLDOWN - (now-last_chall))} сек.")
        return
    if now - last_target < PLAYER_COOLDOWN:
        bot.reply_to(message, f"⏳ Цель недавно участвовала в дуэли. Попробуй позже.")
        return

    # Check no active duel in this chat
    if chat_id in _active_duels:
        bot.reply_to(message, "❗ В чате уже идёт дуэль. Подожди её окончания.")
        return

    # create invite
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

    # send invitation
    disp_chall = _display_name(challenger)
    disp_target = _display_name(target_id)
    msg = bot.send_message(chat_id, f"⚔️ Дуэль: {disp_chall} вызывает на дуэль {disp_target}.\n{disp_target}, ты можешь принять командой /sf_accept или отклонить /sf_decline в течение {INVITE_TIMEOUT} сек.")
    # start invite timeout
    def invite_timeout():
        try:
            d = _active_duels.get(chat_id)
            if d and d['state'] == 'invited':
                del _active_duels[chat_id]
                bot.send_message(chat_id, f"⌛ Время на ответ истекло — дуэль отменена.")
        except Exception as e:
            log.error(f"invite_timeout error: {e}")
    t = threading.Timer(INVITE_TIMEOUT, invite_timeout)
    duel['invite_timer'] = t
    t.start()

# Accept handler
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

    # cancel invite timer
    if d['invite_timer']:
        d['invite_timer'].cancel()

    d['state'] = 'betting'
    d['bets'] = {}
    d['placed_sums'] = {}
    d['betting_started_at'] = time.time()

    disp_chall = _display_name(d['challenger'])
    disp_target = _display_name(d['target'])

    bot.send_message(chat_id, f"✅ {disp_target} принял дуэль! Начинается фаза ставок ({BETTING_PERIOD} секунд). Ставьте командой: /bet @игрок сумма\n(Можно сделать только одну ставку на эту дуэль.)")

    # send periodic update of bettors (we will update message when bets come)
    # start bet timeout
    def end_betting():
        try:
            dd = _active_duels.get(chat_id)
            if not dd or dd['state'] != 'betting':
                return
            # move to running
            dd['state'] = 'running'
            bot.send_message(chat_id, "⏳ Фаза ставок закончена. Подготовка к дуэли...")
            # schedule duel run in a new thread to avoid blocking
            threading.Thread(target=_run_duel, args=(bot, dd), daemon=True).start()
        except Exception as e:
            log.error(f"end_betting err: {e}")
    bt = threading.Timer(BETTING_PERIOD, end_betting)
    d['bet_timer'] = bt
    bt.start()

# Decline handler
def sf_decline_handler(bot, message):
    chat_id = message.chat.id
    register_user(message)
    d = _active_duals.get(chat_id)
    if not d or d['state'] != 'invited':
        bot.reply_to(message, "❗ Нет активного приглашения на дуэль в этом чате.")
        return
    if message.from_user.id != d['target']:
        bot.reply_to(message, "❌ Ты не адресат этого приглашения.")
        return
    # cancel invite timer
    if d['invite_timer']:
        d['invite_timer'].cancel()
    del _active_duels[chat_id]
    bot.send_message(chat_id, "❌ Дуэль отклонена.")

# Bet handler
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
    # resolve target id
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        row = db.get_connection().execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
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
    # deduct bet immediately
    _update_balance(bettor, -amount)
    # record bet
    d['bets'][bettor] = {'on': target_id, 'amount': amount}
    d['placed_sums'][target_id] = d['placed_sums'].get(target_id, 0) + amount

    # show updated bettors
    lines = []
    for b, info in d['bets'].items():
        lines.append(f"{_display_name(b)} → {info['amount']} на {_display_name(info['on'])}")
    bot.send_message(chat_id, "📋 Ставка принята. Текущие ставки:\n" + ("\n".join(lines) if lines else "Нет ставок"))

# Core duel runner
def _run_duel(bot, duel):
    chat_id = duel['chat_id']
    # mark chat cooldown at the end of duel
    try:
        # enforce player cooldowns pre-check one more time (in case)
        now = time.time()
        if now - _chat_duel_cooldown.get(chat_id, 0) < CHAT_COOLDOWN:
            bot.send_message(chat_id, "❗ Нельзя начать дуэль — чат в кулдауне.")
            del _active_duels[chat_id]
            return

        challenger = duel['challenger']
        target = duel['target']
        # set player cooldowns to now (they will be updated at end as well)
        _player_duel_cooldown[challenger] = now
        _player_duel_cooldown[target] = now

        # prepare HP
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

        # announce participants and bets summary
        total_pot = sum(v['amount'] for v in duel['bets'].values()) if duel['bets'] else 0
        s_ch = duel['placed_sums'].get(challenger, 0)
        s_tg = duel['placed_sums'].get(target, 0)
        bot.send_message(chat_id, f"⚔️ Дуэль начинается: {_display_name(challenger)} vs {_display_name(target)}\nHP: {hp_ch} / {hp_tg}\nСтавки: на { _display_name(challenger)} — {s_ch}, на {_display_name(target)} — {s_tg}. Всего в банке: {total_pot} бублей")

        # simulate turns (random who starts)
        attacker, defender = (challenger, target) if random.random() < 0.5 else (target, challenger)
        hp = {challenger: hp_ch, target: hp_tg}
        round_no = 0

        while hp[challenger] > 0 and hp[target] > 0:
            round_no += 1
            # pick attack type
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

            bot.send_message(chat_id, text.format(attacker=_display_name(attacker), dmg=dmg) + f"\n🩺 { _display_name(attacker)}: {hp[attacker]} HP | {_display_name(defender)}: {hp[defender]} HP")
            # small pause between moves
            time.sleep(1.5)

            # swap
            attacker, defender = defender, attacker
            # safety limit
            if round_no > 200:
                bot.send_message(chat_id, "⚠️ Дуэль заняла слишком много ходов — ничья. Возврат ставок.")
                # refund all bets
                for b, info in duel['bets'].items():
                    _update_balance(b, info['amount'])
                del _active_duels[chat_id]
                _chat_duel_cooldown[chat_id] = time.time()
                return

        # determine winner/loser
        if hp[challenger] > 0:
            winner = challenger
            loser = target
        else:
            winner = target
            loser = challenger

        bot.send_message(chat_id, f"🏁 Дуэль закончена! Победитель: {_display_name(winner)}. Поздравляю!")

        # process bets payouts
        # compute sums
        total_on_winner = duel['placed_sums'].get(winner, 0)
        total_on_loser = duel['placed_sums'].get(loser, 0)
        total_pot = total_on_winner + total_on_loser

        # If there were bets, calculate multipliers and pay bettors who bet on winner
        total_bettors_payout = 0
        if total_pot > 0 and total_on_winner > 0:
            # payout_multiplier for those who bet on winner = total_pot / total_on_winner
            payout_multiplier = (total_pot) / total_on_winner
            # iterate bets
            for bidder, info in duel['bets'].items():
                if info['on'] == winner:
                    bet_amount = info['amount']
                    payout = int(round(bet_amount * payout_multiplier))
                    _update_balance(bidder, payout)
                    total_bettors_payout += payout
                    _add_bettor_win(bidder, payout)
                else:
                    # bettors who bet on loser already had their money deducted at bet time; no refund
                    pass
        else:
            # no bettors on winner (or no bets at all)
            total_bettors_payout = 0

        # Winner reward: получает весь выигрыш ставочников * 2
        winner_reward = int(total_bettors_payout * 2)
        if winner_reward > 0:
            _update_balance(winner, winner_reward)
            bot.send_message(chat_id, f"🏆 Победитель {_display_name(winner)} получает бонус от банка: {winner_reward} бублей!")

        # Loser penalty: теряет 32% баланса
        loser_balance_before = _get_balance(loser)
        penalty = int(math.floor(loser_balance_before * 0.32))
        if penalty > 0:
            _update_balance(loser, -penalty)
            bot.send_message(chat_id, f"⚠️ Проигравший {_display_name(loser)} теряет {penalty} бублей за свой проигрыш(")

        # increment winner stat
        _inc_duel_win(winner, 1)

        # announce final balances (brief)
        bot.send_message(chat_id, f"💰 Балансы: {_display_name(winner)} — {_get_balance(winner)}, {_display_name(loser)} — {_get_balance(loser)}")

        # mark cooldowns
        _chat_duel_cooldown[chat_id] = time.time()
        _player_duel_cooldown[winner] = time.time()
        _player_duel_cooldown[loser] = time.time()

    except Exception as e:
        log.error(f"duel run error: {e}")
        bot.send_message(chat_id, "❌ Ошибка при выполнении дуэли.")
    finally:
        # cleanup
        try:
            if chat_id in _active_duels:
                del _active_duels[chat_id]
        except:
            pass

# Tops commands
def topsf_handler(bot, message, limit=10):
    try:
        with db.get_connection() as conn:
            rows = conn.execute("SELECT user_id, wins FROM duel_stats ORDER BY wins DESC LIMIT ?", (limit,)).fetchall()
        if not rows:
            bot.reply_to(message, "❗ Пока нет побед в дуэлях")
            return
        lines = []
        for i, (uid, wins) in enumerate(rows, start=1):
            lines.append(f"{i}. {_display_name(uid)} — {wins} побед")
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
        lines = []
        for i, (uid, total_won) in enumerate(rows, start=1):
            lines.append(f"{i}. {_display_name(uid)} — всего выиграно {total_won} бублей")
        bot.send_message(message.chat.id, "🏅 Топ ставочников:\n\n" + "\n".join(lines))
    except Exception as e:
        log.error(f"topst err: {e}")
        bot.reply_to(message, "❌ Ошибка при получении топа")

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

    # Игры
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
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and re.match(r"(?i)^окак\s+ник\s+(.+)$", m.text.strip()))
    def _h_setnick(m): set_nick_handler(bot, m)

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
# === Регистрация ===
'''def register_extra_handlers(bot):
    @bot.message_handler(commands=['id'])        ; def _(m): id_handler(bot,m)
    @bot.message_handler(commands=['whoami'])    ; def _(m): whoami_handler(bot,m)
    @bot.message_handler(func=lambda m: m.text and m.text.lower()=="спасибо") ; def _(m): thanks_handler(bot,m)
    @bot.message_handler(commands=['balance'])   ; def _(m): balance_handler(bot,m)
    @bot.message_handler(commands=['bomj'])      ; def _(m): street_handler(bot,m)

    @bot.message_handler(commands=['pocket']) ; def _(m): bet_game_handler(bot,m,0.69,1.4,
        ["😎Молодец, воришка. Ты потерял свои деньги на ходу, но получил больше - аж {win} бублей!",
         "✨❄️Моя школа! {win} тебе начислено за твой проворот."],
        ["🙄Ну ты и лоханулся... мало того, что ты ничего не украл, так у тебя украли {bet}!",
         "🤵Мафия тобой разочарована. Мы оштрафовали тебя на {bet}, чтоб не втыкал."])

    @bot.message_handler(commands=['casino']) ; def _(m): bet_game_handler(bot,m,0.35,3.0,
        ["🎰 Джекпот! {win} бублей за ставку {bet}.","🎲 Везёт! Забираешь {win} бублей (ставка {bet})."],
        ["🃏 Крупье улыбается… Ставка {bet} ушла в дом.","💸 Рулетка безжалостна. Минус {bet}."])

    @bot.message_handler(commands=['loto']) ; def _(m): bet_game_handler(bot,m,0.08,18.0,
        ["🎟 Счастливый билет! +{win} бублей (ставка {bet}).","🌟 Умный человек в очках выиграл {win} бублей скачать обои"],
        ["🪙 Ой-ой-ой, не повезло. Ставка в аж {bet} бублей ушла в воздух.","🙃 Сегодня не твой день. Минус {bet}."])

    @bot.message_handler(commands=['buy_hut']) ; def _(m): property_buy_handler(bot,m,"hut")
    @bot.message_handler(commands=['mafia'])   ; def _(m): property_income_handler(bot,m,"hut")
    @bot.message_handler(commands=['buy_communal']) ; def _(m): property_buy_handler(bot,m,"communal")
    @bot.message_handler(commands=['clean'])   ; def _(m): property_income_handler(bot,m,"communal")

    @bot.message_handler(commands=['osebe'])   ; def _(m): osebe_handler(bot,m)
    @bot.message_handler(func=lambda msg: isinstance(msg.text,str) and msg.text.lower().startswith("окак ник")) ; def _(m): nickname_handler(bot,m)
    @bot.message_handler(commands=['topbubl']) ; def _(m): topbubl_handler(bot,m)

    @bot.message_handler(func=lambda m: isinstance(m.text,str) and m.text.lower().startswith("дать ")) ; def _(m): transfer_handler(bot,m)

    @bot.message_handler(commands=['add_bubl']) ; def _(m): admin_add_remove(bot,m,"add")
    @bot.message_handler(commands=['remove_bubl']) ; def _(m): admin_add_remove(bot,m,"remove")
    @bot.message_handler(commands=['xhp']) ;def _(m): xhp_handler(bot,m)
    @bot.message_handler(commands=['sf']);def _h_sf(m): sf_command_handler(bot, m)
#
    @bot.message_handler(commands=['sf_accept']);def _h_sf_accept(m): sf_accept_handler(bot, m)
#
    @bot.message_handler(commands=['sf_decline']);def _h_sf_decline(m): sf_decline_handler(bot, m)
#
@bot.message_handler(commands=['bet']);def _h_bet(m): bet_handler(bot, m)
#
@bot.message_handler(commands=['topsf']);def _h_topsf(m): topsf_handler(bot, m)
#
@bot.message_handler(commands=['topst']);def _h_topst(m): topst_handler(bot, m)

'''





# НОВОЕ


''' 
from database import Database
from handlers import register_user
import random, re, logging, time

log = logging.getLogger(__name__)
db = Database()

# === Конфиг ===
MIN_RANDOM = 5
MAX_RANDOM = 150
MIN_BET = 15
STREET_COOLDOWN = 15   # кулдаун на /bomj
OWNER_ID = 5758264503   # замени на свой Telegram ID (/id)

# === Вспомогательные функции ===
_last_street = {}

def _ensure_balances_table():
    try:
        with db.get_connection() as conn:
            conn.execute("""
                '''CREATE TABLE IF NOT EXISTS balances (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0
                )'''
            """)
            conn.commit()
    except Exception as e:
        log.error(f"Не удалось создать таблицу balances: {e}")

def _get_balance(user_id: int) -> int:
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT balance FROM balances WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else 0
    except Exception as e:
        log.error(f"Ошибка чтения баланса: {e}")
        return 0

def _update_balance(user_id: int, delta: int) -> bool:
    try:
        with db.get_connection() as conn:
            conn.execute(
                """
                '''INSERT INTO balances (user_id, balance)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance'''
                """,
                (user_id, delta)
            )
            conn.commit()
            # защита от отрицательных балансов
            conn.execute("UPDATE balances SET balance = 0 WHERE user_id = ? AND balance < 0", (user_id,))
            conn.commit()
            return True
    except Exception as e:
        log.error(f"Ошибка обновления баланса: {e}")
        return False

def _find_user_id_by_username(username_no_at: str):
    try:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT user_id FROM users WHERE username = ?",
                (username_no_at,)
            ).fetchone()
            return row[0] if row else None
    except Exception as e:
        log.error(f"Ошибка поиска user_id @{username_no_at}: {e}")
        return None

_ensure_balances_table()

# === Хендлеры ===
def balance_handler(bot, message):
    register_user(message)
    bal = _get_balance(message.from_user.id)
    bot.reply_to(message, f"💰 У тебя {bal} бублей")

def street_handler(bot, message):
    register_user(message)
    now = time.time()
    last = _last_street.get(message.from_user.id, 0)
    if now - last < STREET_COOLDOWN:
        wait = int(STREET_COOLDOWN - (now - last))
        bot.reply_to(message, f"⏳ Подожди ещё {wait} секунд, прежде чем снова просить бубли")
        return

    amount = random.randint(MIN_RANDOM, MAX_RANDOM)
    _update_balance(message.from_user.id, amount)
    _last_street[message.from_user.id] = now
    new_bal = _get_balance(message.from_user.id)
    bot.reply_to(message, f"🪙 Ты выпросил {amount} бублей на улице! (как последний бомж...)\n💰 Баланс: {new_bal}")

def _parse_bet(message):
    parts = message.text.split()
    if len(parts) < 2:
        return None
    amt = parts[1].strip()
    if not amt.isdigit():
        return None
    return int(amt)

def _play_game(bot, message, *, chance: float, multiplier: float, win_texts, lose_texts):
    register_user(message)
    bet = _parse_bet(message)
    if bet is None:
        bot.reply_to(message, f"❗ Укажи ставку, например: {message.text.split()[0]} 50")
        return
    if bet < MIN_BET:
        bot.reply_to(message, f"❗ Минимальная ставка: {MIN_BET} бублей")
        return

    bal = _get_balance(message.from_user.id)
    if bal < bet:
        bot.reply_to(message, "❌ Недостаточно бублей для этой ставки")
        return

    if not _update_balance(message.from_user.id, -bet):
        bot.reply_to(message, "❌ Ошибка при списании ставки")
        return

    if random.random() < chance:
        win_amount = int(round(bet * multiplier))
        _update_balance(message.from_user.id, win_amount)
        result = random.choice(win_texts).format(bet=bet, win=win_amount)
    else:
        result = random.choice(lose_texts).format(bet=bet)

    new_bal = _get_balance(message.from_user.id)
    bot.reply_to(message, f"{result}\n💰 Баланс: {new_bal}")

def transfer_handler(bot, message):
    register_user(message)
    text = message.text.strip()
    m = re.match(r"(?i)^перевод\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$", text)
    if not m:
        bot.reply_to(message, "❗ Используй: перевод @username 100")
        return

    target_raw, amount_str = m.group(1), m.group(2)
    amount = int(amount_str)
    if amount <= 0:
        bot.reply_to(message, "❗ Сумма должна быть положительной")
        return

    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        username = target_raw.lstrip("@")
        target_id = _find_user_id_by_username(username)

    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден. Попроси его написать боту /start")
        return
    if target_id == message.from_user.id:
        bot.reply_to(message, "❌ Нельзя переводить самому себе")
        return

    bal = _get_balance(message.from_user.id)
    if bal < amount:
        bot.reply_to(message, "❌ Недостаточно бублей для перевода")
        return

    if not _update_balance(message.from_user.id, -amount):
        bot.reply_to(message, "❌ Ошибка при списании средств")
        return
    if not _update_balance(target_id, amount):
        _update_balance(message.from_user.id, amount)
        bot.reply_to(message, "❌ Не удалось зачислить получателю")
        return

    bot.reply_to(message, f"✅ Перевод выполнен: {amount} бублей → {target_raw}")

def admin_change_balance(bot, message, is_add=True):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ У тебя нет прав для этой команды")
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, f"❗ Формат: {'/add_bubl' if is_add else '/remove_bubl'} @username 100")
        return

    target_raw, amount_str = parts[1], parts[2]
    if not amount_str.isdigit():
        bot.reply_to(message, "❗ Укажи число бублей")
        return

    amount = int(amount_str)
    if not is_add:
        amount = -amount

    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        username = target_raw.lstrip("@")
        target_id = _find_user_id_by_username(username)

    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден")
        return

    _update_balance(target_id, amount)
    new_bal = _get_balance(target_id)
    bot.reply_to(message, f"✅ Баланс обновлён: теперь у {target_raw} {new_bal} бублей")

def topbubl_handler(bot, message, limit: int = 10):
    try:
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT ?",
                (limit,)
            ).fetchall()

        if not rows:
            bot.reply_to(message, "❗ Ещё никто не накопил бубли")
            return

        lines = []
        for idx, (uid, bal) in enumerate(rows, start=1):
            # ищем имя пользователя
            user = conn.execute(
                "SELECT username, first_name, last_name FROM users WHERE user_id = ?",
                (uid,)
            ).fetchone()
            if user:
                username, first_name, last_name = user
                display_name = None
                if username:
                    display_name = f"@{username}"
                elif first_name or last_name:
                    display_name = f"{first_name or ''} {last_name or ''}".strip()
                else:
                    display_name = str(uid)
            else:
                display_name = str(uid)

            lines.append(f"{idx}. {display_name} — 💰 {bal} бублей")

        text = "🏆 Топ самых богатых игроков:\n\n" + "\n".join(lines)
        bot.send_message(message.chat.id, text)

    except Exception as e:
        log.error(f"/topbubl: {e}")
        bot.reply_to(message, "❌ Ошибка при получении топа")


# === Регистрация ===
def register_extra_handlers(bot):
    @bot.message_handler(commands=['balance'])
    def _h_balance(message): balance_handler(bot, message)

    @bot.message_handler(commands=['bomj'])
    def _h_street(message): street_handler(bot, message)

    @bot.message_handler(commands=['pocket'])
    def _h_pocket(message):
        _play_game(
            bot, message,
            chance=0.69, multiplier=1.4,
            win_texts=[
                "😎 Молодец, воришка. Зал аж {win} бублей!",
                "✨❄️ Моя школа! {win} тебе начислено."
            ],
            lose_texts=[
                "🙄 Обчистили тебя, минус {bet}!",
                "🤵 Мафия разочарована. Штраф {bet}."
            ]
        )

    @bot.message_handler(commands=['casino'])
    def _h_casino(message):
        _play_game(
            bot, message,
            chance=0.35, multiplier=3.0,
            win_texts=[
                "🎰 Джекпот! {win} бублей за ставку {bet}.",
                "🎲 Везёт! Забираешь {win}."
            ],
            lose_texts=[
                "🃏 Крупье улыбается… Минус {bet}.",
                "💸 Рулетка безжалостна. Ставка {bet} проиграна."
            ]
        )

    @bot.message_handler(commands=['loto'])
    def _h_loto(message):
        _play_game(
            bot, message,
            chance=0.08, multiplier=18.0,
            win_texts=[
                "🎟 Счастливый билет! +{win} бублей (ставка {bet}).",
                "🌟 Один шанс из ста — и он твой! {win} бублей!"
            ],
            lose_texts=[
                "🪙 Увы, ставка {bet} проиграна.",
                "🙃 Сегодня не твой день. Минус {bet}."
            ]
        )

    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("перевод "))
    def _h_transfer(message): transfer_handler(bot, message)

    @bot.message_handler(commands=['add_bubl'])
    def _h_add(message): admin_change_balance(bot, message, is_add=True)

    @bot.message_handler(commands=['remove_bubl'])
    def _h_remove(message): admin_change_balance(bot, message, is_add=False)
    
    @bot.message_handler(commands=['topbubl'])
    def _h_top(message): topbubl_handler(bot, message)'''
  
    # СТАРОЕ 
      
'''
import random
from database import Database

db = Database()

# === Конфиг ===
MIN_RANDOM = 5     # минимальное количество при "поиске бублей"
MAX_RANDOM = 150    # максимальное количество при "поиске бублей"
MIN_BET = 20       # минимальная ставка

# === Команда: проверить баланс ===
def balance_handler(bot, message):
    balance = db.get_balance(message.from_user.id)
    bot.reply_to(message, f"💰{message.from_user.first_name}, у тебя {balance} бублей")

# === Команда: попросить денег "на улице" ===
def street_handler(bot, message):
    amount = random.randint(MIN_RANDOM, MAX_RANDOM)
    db.update_balance(message.from_user.id, amount)
    new_balance = db.get_balance(message.from_user.id)
    bot.reply_to(message, f"Ты выпросил {amount} бублей на улице!\n💰 Теперь у тебя {new_balance} бублей!")

# === Игры ===
def play_game(bot, message, chance, multiplier):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, f"❗ Укажи ставку, например: {parts[0]} 50")
        return

    bet = int(parts[1])
    if bet < MIN_BET:
        bot.reply_to(message, f"❗ Минимальная ставка {MIN_BET} бублей")
        return

    balance = db.get_balance(message.from_user.id)
    if balance < bet:
        bot.reply_to(message, "❌ У тебя недостаточно бублей для этой ставки")
        return

    # списываем ставку
    db.update_balance(message.from_user.id, -bet)

    if random.random() < chance:
        win_amount = int(bet * multiplier)
        db.update_balance(message.from_user.id, win_amount)
        result = f"✅ Победа! Ты выиграл {win_amount} бублей!"
    else:
        result = "💀 Увы, проигрыш!"

    new_balance = db.get_balance(message.from_user.id)
    bot.reply_to(message, f"{result}\n💰 Текущий баланс: {new_balance} бублей")

# === Регистрация команд ===
def register_extra_handlers(bot):
    @bot.message_handler(commands=['balance'])
    def handle_balance(message): balance_handler(bot, message)

    @bot.message_handler(commands=['bomj'])
    def handle_street(message): street_handler(bot, message)

    # Игра 1: шанс 70%, выигрыш х1.25
    @bot.message_handler(commands=['bordel'])
    def handle_football(message): play_game(bot, message, chance=0.7, multiplier=1.25)

    # Игра 2: шанс 35%, выигрыш х3
    @bot.message_handler(commands=['poker'])
    def handle_casino(message): play_game(bot, message, chance=0.35, multiplier=3)

    # Игра 3: шанс 10%, выигрыш х14
    @bot.message_handler(commands=['loto'])
    def handle_lottery(message): play_game(bot, message, chance=0.10, multiplier=14)'''