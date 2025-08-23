# extra_handlers.py — полный обновлённый файл (замените старый файл этим)
import random
import re
import logging
import time
import threading
import math
import unicodedata
from types import SimpleNamespace
from telebot import types
from database import Database
from handlers import register_user

log = logging.getLogger(__name__)
db = Database()

# === Конфигурация / constants ===
MIN_RANDOM = 35
MAX_RANDOM = 350
MIN_BET = 15
BET_COOLDOWN = 7            # кулдаун на любые ставки (сек)
STREET_COOLDOWN = 15        # кулдаун /bomj (сек)
OWNER_ID = 5758264503       # твой ID (админ)

# PROPERTIES (добавляем новые)
PROPERTIES = {
    "hut": {
        "name": "Хижина на отшибе",
        "price": 20000,
        "command": "mafia",
        "cooldown": 20,
        "income": (140, 740),
        "message": "🥷Ты выполнил маленькое задание от мафии, получив зарплату {money} бублей\n\nБаланс: {balance} бублей"
    },
    "communal": {
        "name": "Коммуналка в гетто",
        "price": 95000,
        "command": "clean",
        "cooldown": 30,
        "income": (500, 1800),
        "message": "🫧 🧽Ты помыл пол в соседнем общежитии, и тебе скинулись {money} бублей\n\nБаланс: {balance} бублей"
    },
    "country": {
        "name": "Загородный дом",
        "price": 200000,
        "command": "pizza",
        "cooldown": 60,
        "income": (3000, 7000),
        "message": "🍕Ты поработал курьером пиццы и выполнил доставку, за которую тебе заплатили {money} бублей.\n\nБаланс: {balance} бублей"
    },
    "cottage": {
        "name": "Стандартный коттедж",
        "price": 950000,
        "command": "waiter",
        "cooldown": 120,
        "income": (6500, 16500),
        "message": "🧑‍💼🍽️Ты подработал, разнося блюда в ресторане. В конверте: {money} бублей.\n💰 Баланс: {balance} бублей."
    },
    "villa": {
        "name": "Вилла у моря",
        "price": 2000000,
        "command": "lawyer",
        "cooldown": 240,
        "income": (15000, 35000),
        "message": "🧑‍⚖️Ты помог тем, кем ты раньше был. Плата: {money} бублей.\n💰 Баланс: {balance} бублей."
    },
    "mansion": {  # новая недвижимость: Роскошный особняк
        "name": "Роскошный особняк",
        "price": 95_000_000,
        "command": "youtuber",
        "cooldown": 600,  # 10 минут
        "income": (80_000, 230_000),
        "message": "🫩После дня кучи коллабораций и монтажа, выручка с реклам и донатов на бусти вышла: {money} бублей.\nБаланс: {balance} бублей."
    }
}

# === Инициализация таблиц (при первом импорте) ===
def _ensure_tables():
    with db.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_seen_chat INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                user_id INTEGER,
                property_key TEXT,
                UNIQUE(user_id, property_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nicknames (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS duel_stats (
                user_id INTEGER PRIMARY KEY,
                wins INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bettor_stats (
                user_id INTEGER PRIMARY KEY,
                total_won INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS treasure (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance INTEGER NOT NULL
            )
        """)
        # Таблица для рабства
        conn.execute("""
            CREATE TABLE IF NOT EXISTS slaves (
                slave_id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                enslaved_at INTEGER NOT NULL,
                last_tax_ts INTEGER NOT NULL
            )
        """)
        # Таблица продаж рабов
        conn.execute("""
            CREATE TABLE IF NOT EXISTS slave_sales (
                sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                slave_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                price INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        # Таблица помощников / окaк токенов / банк
        conn.execute("""
            CREATE TABLE IF NOT EXISTS okak_tokens (
                user_id INTEGER PRIMARY KEY,
                tokens INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS helpers (
                user_id INTEGER PRIMARY KEY,
                defender INTEGER DEFAULT 0,
                guard INTEGER DEFAULT 0,
                esoteric INTEGER DEFAULT 0,
                phoenix INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bbank (
                user_id INTEGER PRIMARY KEY,
                bank_balance INTEGER DEFAULT 0,
                invested INTEGER DEFAULT 0,
                last_withdraw_ts INTEGER DEFAULT 0,
                earned_from_invest INTEGER DEFAULT 0
            )
        """)
        # индекс для ников (case-insensitive)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_nick_unique ON nicknames (nickname COLLATE NOCASE)")
        conn.commit()

_ensure_tables()

# Инициализация сокровищницы (если нет записи)
def _ensure_treasure_table():
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT balance FROM treasure WHERE id = 1").fetchone()
            if not row:
                conn.execute("INSERT INTO treasure (id, balance) VALUES (1, ?)", (100000,))
            conn.commit()
    except Exception as e:
        log.error(f"_ensure_treasure_table error: {e}")

_ensure_treasure_table()

# ======= Сокровищница (DB helpers) =======
def _get_treasure_balance() -> int:
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT balance FROM treasure WHERE id = 1").fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        log.error(f"_get_treasure_balance error: {e}")
        return 0

def _update_treasure_balance(delta: int) -> None:
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT balance FROM treasure WHERE id = 1").fetchone()
            if not row:
                conn.execute("INSERT INTO treasure (id, balance) VALUES (1, ?)", (0,))
            conn.execute("UPDATE treasure SET balance = MAX(0, balance + ?) WHERE id = 1", (delta,))
            conn.commit()
    except Exception as e:
        log.error(f"_update_treasure_balance error: {e}")

def _treasury_add(amount: int) -> None:
    _update_treasure_balance(amount)

# === Баланс / accounts ===
def _get_balance(user_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT balance FROM balances WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else 0

def _update_balance(user_id: int, delta: int):
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO balances (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
            """,
            (user_id, delta)
        )
        conn.commit()

# === Окак-Токены ===
def _get_tokens(user_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT tokens FROM okak_tokens WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else 0

def _update_tokens(user_id: int, delta: int):
    with db.get_connection() as conn:
        conn.execute("""
            INSERT INTO okak_tokens (user_id, tokens)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET tokens = tokens + excluded.tokens
        """, (user_id, delta))
        conn.commit()

# === Helpers (покупки в okakshop) ===
def _get_helpers(user_id: int):
    with db.get_connection() as conn:
        row = conn.execute("SELECT defender, guard, esoteric, phoenix FROM helpers WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"defender": 0, "guard": 0, "esoteric": 0, "phoenix": 0}
        return {"defender": row[0], "guard": row[1], "esoteric": row[2], "phoenix": row[3]}

def _set_helper_field(user_id: int, field: str, value: int):
    with db.get_connection() as conn:
        conn.execute("""
            INSERT INTO helpers (user_id, defender, guard, esoteric, phoenix)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              defender=excluded.defender, guard=excluded.guard, esoteric=excluded.esoteric, phoenix=excluded.phoenix
        """, (
            user_id,
            value if field == "defender" else _get_helpers(user_id)["defender"],
            value if field == "guard" else _get_helpers(user_id)["guard"],
            value if field == "esoteric" else _get_helpers(user_id)["esoteric"],
            value if field == "phoenix" else _get_helpers(user_id)["phoenix"],
        ))
        conn.commit()

# === Бубль-банк (bbank) ===
def _get_bbank(user_id: int):
    with db.get_connection() as conn:
        row = conn.execute("SELECT bank_balance, invested, last_withdraw_ts, earned_from_invest FROM bbank WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {"bank_balance": 0, "invested": 0, "last_withdraw_ts": 0, "earned_from_invest": 0}
        return {"bank_balance": row[0], "invested": row[1], "last_withdraw_ts": row[2], "earned_from_invest": row[3]}

def _set_bbank(user_id: int, bank_balance=None, invested=None, last_withdraw_ts=None, earned_from_invest=None):
    cur = _get_bbank(user_id)
    bank_balance = cur["bank_balance"] if bank_balance is None else bank_balance
    invested = cur["invested"] if invested is None else invested
    last_withdraw_ts = cur["last_withdraw_ts"] if last_withdraw_ts is None else last_withdraw_ts
    earned_from_invest = cur["earned_from_invest"] if earned_from_invest is None else earned_from_invest
    with db.get_connection() as conn:
        conn.execute("""
            INSERT INTO bbank (user_id, bank_balance, invested, last_withdraw_ts, earned_from_invest)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
               bank_balance=excluded.bank_balance, invested=excluded.invested, last_withdraw_ts=excluded.last_withdraw_ts, earned_from_invest=excluded.earned_from_invest
        """, (user_id, bank_balance, invested, last_withdraw_ts, earned_from_invest))
        conn.commit()

BBANK_MAX_INVEST = 1_000_000
INVEST_MIN = 100_000
INVEST_MAX = 1_000_000
INVEST_UPDATE_INTERVAL = 60  # 1 минута в секундах
INVEST_UP_CHANCE = 0.62
INVEST_DOWN_CHANCE = 0.33
INVEST_STAY_CHANCE = 0.05
WITHDRAW_COOLDOWN = 180  # 3 минуты
TOKEN_PER_100K = 100_000  # за каждые 100k полученных через инвест даём токен

# Фоновая задача — обновление инвестиций
_invest_thread_started = False
_invest_lock = threading.Lock()

def _investments_worker():
    while True:
        try:
            with db.get_connection() as conn:
                rows = conn.execute("SELECT user_id, invested, bank_balance, earned_from_invest FROM bbank WHERE invested > 0").fetchall()
            for user_id, invested, bank_balance, earned in rows:
                if invested <= 0:
                    continue
                r = random.random()
                delta = 0
                if r < INVEST_UP_CHANCE:
                    # +3%
                    delta = int(math.floor(invested * 0.03))
                elif r < INVEST_UP_CHANCE + INVEST_DOWN_CHANCE:
                    # -3%
                    delta = -int(math.floor(invested * 0.03))
                else:
                    delta = 0
                # применяем к bank_balance (банк баланс отражает value, инвест хранит исходную сумму)
                if delta != 0:
                    # обновляем bank_balance и earned (если delta>0 — считаем это как "полученные" для токенов)
                    new_bank = bank_balance + delta
                    new_earned = earned
                    if delta > 0:
                        new_earned += delta
                    _set_bbank(user_id, bank_balance=new_bank, invested=invested, last_withdraw_ts=None, earned_from_invest=new_earned)
                    # начисляем токены если накопилось >= TOKEN_PER_100K
                    tokens_to_award = new_earned // TOKEN_PER_100K
                    if tokens_to_award > 0:
                        _update_tokens(user_id, tokens_to_award)
                        new_earned = new_earned - tokens_to_award * TOKEN_PER_100K
                        _set_bbank(user_id, bank_balance=new_bank, invested=invested, earned_from_invest=new_earned)
                        # уведомление — только если пользователь в онлайне, но отправляем в телеграм (не блокируем)
                        try:
                            # не блокируем исполнение, просто пробуем отправить (если бот доступен, регистратор сделает отправку)
                            pass
                        except Exception:
                            pass
            # спим
        except Exception as e:
            log.exception(f"_investments_worker error: {e}")
        time.sleep(INVEST_UPDATE_INTERVAL)

def _start_invest_worker():
    global _invest_thread_started
    with _invest_lock:
        if not _invest_thread_started:
            t = threading.Thread(target=_investments_worker, daemon=True)
            t.start()
            _invest_thread_started = True

# запускаем воркер
_start_invest_worker()

# === Nicknames / display name ===
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

def _display_name(user_id):
    nick = _get_nickname(user_id)
    if nick:
        return nick
    with db.get_connection() as conn:
        row = conn.execute("SELECT first_name FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row[0] if row and row[0] else str(user_id)

# === Properties helpers ===
def _buy_property_record(user_id, key):
    with db.get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO properties (user_id, property_key) VALUES (?, ?)", (user_id, key))
        conn.commit()

def _get_properties(user_id):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT property_key FROM properties WHERE user_id=?", (user_id,)).fetchall()
        return [r[0] for r in rows]

# --- Compatibility wrapper: иногда раньше был другой нейминг ---
def buy_property_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Используй: /buy <key> (hut, communal, country, cottage, villa, mansion)")
        return
    key_raw = parts[1].lower()
    mapping = {
        ("hut", "хижина", "хижина_на_отшибе"): "hut",
        ("communal", "коммуналка", "коммуналка_в_гетто"): "communal",
        ("country", "загородный", "загородный_дом"): "country",
        ("cottage", "коттедж", "стандартный"): "cottage",
        ("villa", "вилла", "моря"): "villa",
        ("mansion", "особняк", "роскошный_особняк"): "mansion"
    }
    key = None
    for keys, v in mapping.items():
        if key_raw in keys:
            key = v
            break
    if not key:
        bot.reply_to(message, "❗ Неизвестная недвижимость. Доступно: hut, communal, country, cottage, villa, mansion")
        return
    # вызываем real handler
    property_buy_handler_real(bot, message, key)

def property_buy_handler_real(bot, message, key):
    register_user(message)
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
    bot.reply_to(message, f"✅ Куплено: {p['name']} за {p['price']}\n\nБаланс: {_get_balance(uid)} буб.")

# property income (work commands)
_last_income = {}  # (user_id, property_key) -> ts

def property_income_handler(bot, message, key):
    register_user(message)
    uid = message.from_user.id
    p = PROPERTIES[key]
    if key not in _get_properties(uid):
        bot.reply_to(message, f"❌ У вас нет {p['name']} (стоит {p['price']})")
        return
    now = time.time()
    last = _last_income.get((uid, key), 0)
    if now - last < p["cooldown"]:
        bot.reply_to(message, f"⏳ Подожди {int(p['cooldown'] - (now - last))} сек")
        return
    _last_income[(uid, key)] = now
    money = random.randint(*p["income"])
    # Phoenix helper doubles income
    helpers = _get_helpers(uid)
    if helpers.get("phoenix", 0):
        money = money * 2
    _update_balance(uid, money)
    bot.reply_to(message, p["message"].format(money=money, balance=_get_balance(uid)))

# обёртки команд
def buy_hut_handler(bot, message):
    fake = SimpleNamespace(text="/buy hut", from_user=message.from_user, chat=message.chat)
    buy_property_handler(bot, fake)

def buy_communal_handler(bot, message):
    fake = SimpleNamespace(text="/buy communal", from_user=message.from_user, chat=message.chat)
    buy_property_handler(bot, fake)

def buy_country_handler(bot, message):
    fake = SimpleNamespace(text="/buy country", from_user=message.from_user, chat=message.chat)
    buy_property_handler(bot, fake)

def buy_cottage_handler(bot, message):
    fake = SimpleNamespace(text="/buy cottage", from_user=message.from_user, chat=message.chat)
    buy_property_handler(bot, fake)

def buy_villa_handler(bot, message):
    fake = SimpleNamespace(text="/buy villa", from_user=message.from_user, chat=message.chat)
    buy_property_handler(bot, fake)

def buy_mansion_handler(bot, message):
    fake = SimpleNamespace(text="/buy mansion", from_user=message.from_user, chat=message.chat)
    buy_property_handler(bot, fake)

def lawyer_handler(bot, message):
    property_income_handler(bot, message, "villa")

def waiter_handler(bot, message):
    property_income_handler(bot, message, "cottage")

def mafia_handler(bot, message):
    property_income_handler(bot, message, "hut")

def clean_handler(bot, message):
    property_income_handler(bot, message, "communal")

def pizza_handler(bot, message):
    property_income_handler(bot, message, "country")

def youtuber_handler(bot, message):
    property_income_handler(bot, message, "mansion")

# === Nick / nickname handler (improved) ===
NICK_RE = re.compile(r'(?i)^окак\s+ник\s+(.+)$')

def nickname_handler(bot, message):
    register_user(message)
    text = (message.text or '').strip()
    m = NICK_RE.match(text)
    if not m:
        bot.reply_to(message, "❗ Используй: Окак ник <твой ник>")
        return

    raw_nick = m.group(1).strip()
    nick = unicodedata.normalize('NFKC', raw_nick)
    nick = ' '.join(nick.split())

    if not nick:
        bot.reply_to(message, "❗ Ник не может быть пустым.")
        return

    MAX_NICK_LEN = 25
    if len(nick) > MAX_NICK_LEN:
        bot.reply_to(message, f"❗ Ник слишком длинный ({len(nick)}/{MAX_NICK_LEN}). Максимум {MAX_NICK_LEN} символов.")
        return
    if '\n' in nick or '\r' in nick:
        bot.reply_to(message, "❗ Ник не должен содержать переносы строк.")
        return

    # запрет контрол-символов / combining / zero-width / private use
    for ch in nick:
        cat = unicodedata.category(ch)
        code = ord(ch)
        if cat.startswith('C') or cat.startswith('M'):
            bot.reply_to(message, "❗ Ник содержит недопустимые символы. Убери необычные символы и попробуй снова.")
            return
        if (0x200B <= code <= 0x200F) or (0x202A <= code <= 0x202E) or code == 0xFEFF:
            bot.reply_to(message, "❗ Ник содержит невидимые символы. Убери их и попробуй снова.")
            return
        if 0xFE00 <= code <= 0xFE0F:
            bot.reply_to(message, "❗ Ник содержит недопустимые модификаторы символов. Убери их и попробуй снова.")
            return
        if (0xE000 <= code <= 0xF8FF) or (0xF0000 <= code <= 0xFFFFD) or (0x100000 <= code <= 0x10FFFD):
            bot.reply_to(message, "❗ Ник содержит запрещённые символы. Выбери другой ник.")
            return

    # уникальность
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM nicknames WHERE LOWER(nickname)=LOWER(?)", (nick,)).fetchone()
            if row and row[0] != message.from_user.id:
                bot.reply_to(message, "❗ Этот ник уже занят другим пользователем. Выбери другой.")
                return
    except Exception as e:
        log.exception(f"nickname uniqueness check error: {e}")
        bot.reply_to(message, "❌ Ошибка при проверке ника. Попробуй позже.")
        return

    _set_nickname(message.from_user.id, nick)
    bot.reply_to(message, f"✅ Теперь твой ник: {nick}")

# === Wipe / delete nick handlers (admin) ===
def _find_user_id_by_username_fallback(username_no_at: str):
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE username = ?", (username_no_at,)).fetchone()
            return row[0] if row else None
    except Exception as e:
        log.exception(f"_find_user_id_by_username_fallback error: {e}")
        return None

def _remove_nickname_by_user_id(user_id: int) -> bool:
    try:
        with db.get_connection() as conn:
            r = conn.execute("SELECT 1 FROM nicknames WHERE user_id = ?", (user_id,)).fetchone()
            if not r:
                return False
            conn.execute("DELETE FROM nicknames WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
    except Exception as e:
        log.exception(f"_remove_nickname_by_user_id error: {e}")
        return False

def wipe_nick_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    with db.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM nicknames").fetchone()
        total = row[0] if row else 0
        if total == 0:
            bot.reply_to(message, "ℹ️ В таблице никнеймов ничего нет.")
            return
        conn.execute("DELETE FROM nicknames")
        conn.commit()
    bot.reply_to(message, f"✅ Удалено {total} ник(ов).")

def delete_nick_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    # reply support
    if getattr(message, 'reply_to_message', None) and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        text = (message.text or "").strip()
        m = re.match(r"(?i)^/delete_nick\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s*$", text)
        if not m:
            bot.reply_to(message, "❗ Используй: /delete_nick @username или /delete_nick <user_id>, либо ответь командой на сообщение пользователя.")
            return
        target_raw = m.group(1)
        if target_raw.isdigit():
            target_id = int(target_raw)
        else:
            username = target_raw.lstrip("@")
            target_id = _find_user_id_by_username_fallback(username)
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден в базе.")
        return
    removed = _remove_nickname_by_user_id(target_id)
    if removed:
        bot.reply_to(message, f"✅ Ник пользователя {_display_name(target_id)} удалён.")
    else:
        bot.reply_to(message, f"ℹ️ У {_display_name(target_id)} не было ника.")

# === Базовые хендлеры ===
def id_handler(bot, message):
    bot.reply_to(message, f"🆔 Твой Telegram ID: {message.from_user.id}")

def whoami_handler(bot, message):
    u = message.from_user
    bot.reply_to(message, f"👤 Инфо о тебе:\nИмя: {u.first_name or ''} {u.last_name or ''}\nUsername: @{u.username if u.username else '—'}\nID: {u.id}")

def thanks_handler(bot, message):
    bot.reply_to(message, f"Пожалуйста, {message.from_user.first_name}! 🙌")

# === /bomj (street) ===
_last_street = {}
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
    # Phoenix doubles
    if _get_helpers(uid).get("phoenix", 0):
        amount *= 2
    _update_balance(uid, amount)
    bot.reply_to(message, f"🪙 Ты выпросил {amount} бублей на улице! (как последний бомж...)\n💰 Баланс: {_get_balance(uid)}")

# === Игры — ядро (bet_game_handler) ===
_last_bet = {}

def bet_game_handler(bot, message, chance, mult, win_texts, lose_texts, send_reply=True):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_bet.get(uid, 0)
    if now - last < BET_COOLDOWN:
        if send_reply:
            bot.reply_to(message, f"⏳ Подожди {int(BET_COOLDOWN - (now - last))} сек")
            return ("COOLDOWN", None)
        else:
            return ("COOLDOWN", None)
    _last_bet[uid] = now

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        if send_reply:
            bot.reply_to(message, f"❗ Укажи ставку, например: {parts[0]} 50")
            return ("NO_STAKE", None)
        else:
            return ("NO_STAKE", None)
    bet = int(parts[1])
    if bet < MIN_BET:
        if send_reply:
            bot.reply_to(message, f"❗ Минимальная ставка: {MIN_BET}")
            return ("MIN_BET", None)
        else:
            return ("MIN_BET", None)

    bal = _get_balance(uid)
    if bal < bet:
        if send_reply:
            bot.reply_to(message, "❌ Недостаточно бублей")
            return ("NO_MONEY", None)
        else:
            return ("NO_MONEY", None)

    # списываем ставку
    _update_balance(uid, -bet)

    # Phoenix doubles win
    if random.random() < chance:
        win = int(round(bet * mult))
        if _get_helpers(uid).get("phoenix", 0):
            win = win * 2
        _update_balance(uid, win)
        text = random.choice(win_texts).format(bet=bet, win=win)
    else:
        # игрок проиграл — 50% ставки уходит в сокровищницу
        _treasury_add(int(bet * 0.5))
        text = random.choice(lose_texts).format(bet=bet)

    new_bal = _get_balance(uid)
    if send_reply:
        bot.reply_to(message, f"{text}\n💰 Баланс: {new_bal}")
        return (text, new_bal)
    else:
        return (text, new_bal)

# backward compatibility
def _play_game(bot, message, *, chance, multiplier, win_texts, lose_texts):
    return bet_game_handler(bot, message, chance, multiplier, win_texts, lose_texts, send_reply=True)

# === /bubl (inline buttons that launch games) ===
def bubl_handler(bot, message):
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "❗ Используй так: /bubl 100")
        return
    bet = int(parts[1])
    if bet <= 0:
        bot.reply_to(message, "❗ Ставка должна быть положительной")
        return
    nick = _get_nickname(message.from_user.id) or (message.from_user.first_name or (message.from_user.username or "Игрок"))
    nick_first = nick.split()[0]
    text = f"🤑 {nick_first}, ты с собой берёшь {bet} бублей.\n\nКак ты хочешь разбогатеть?"
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🤵 Кража", callback_data=f"bubl_pocket_{bet}_{message.from_user.id}"),
        types.InlineKeyboardButton("🎰 Казино", callback_data=f"bubl_casino_{bet}_{message.from_user.id}"),
        types.InlineKeyboardButton("🎟️ Лотерея", callback_data=f"bubl_loto_{bet}_{message.from_user.id}")
    )
    sent = bot.send_message(message.chat.id, text, reply_markup=markup)
    # удалить через 20 секунд если не нажали
    def _del():
        try:
            bot.delete_message(sent.chat.id, sent.message_id)
        except Exception:
            pass
    threading.Timer(20.0, _del).start()

def bubl_callback_handler(bot, call):
    try:
        parts = call.data.split("_")
        if len(parts) != 4 or parts[0] != "bubl":
            return
        game, bet_s, uid_s = parts[1], parts[2], parts[3]
        bet = int(bet_s); uid = int(uid_s)
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Это не твоя ставка!", show_alert=True)
            return
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        fake = SimpleNamespace(text=f"/{game} {bet}", from_user=call.from_user, chat=call.message.chat)
        mapping = {
            "pocket": (0.70, 1.25,
                       ["😎Молодец, воришка. Ты потерял свои деньги на ходу, но получил больше - аж {win} бублей!",
                        "✨❄️Моя школа! {win} тебе начислено за твой проворот."],
                       ["🙄Ну ты и лоханулся... мало того, что ты ничего не украл, так у тебя украли {bet}!",
                        "🤵Мафия тобой разочарована. Мы оштрафовали тебя на {bet}, чтоб не втыкал."]),
            "casino": (0.35, 3.0,
                       ["🎰 Джекпот! {win} бублей за ставку {bet}.",
                        "🎲 Везёт! Забираешь {win} бублей (ставка {bet})."],
                       ["🃏 Крупье улыбается… Ставка {bet} ушла в дом.",
                        "💸 Рулетка безжалостна. Минус {bet}."]),
            "loto": (0.10, 14.0,
                     ["🎟 Счастливый билет! +{win} бублей (ставка {bet}).",
                      "🌟 Умный человек в очках выиграл {win} бублей скачать обои"],
                     ["🪙 Ой-ой-ой, не повезло. Ставка в аж {bet} бублей ушла в воздух.",
                      "🙃 Сегодня не твой день. Минус {bet}."])
        }
        if game not in mapping:
            bot.answer_callback_query(call.id, "❌ Неизвестная игра", show_alert=True)
            return
        chance, mult, win_texts, lose_texts = mapping[game]
        res = bet_game_handler(bot, fake, chance, mult, win_texts, lose_texts, send_reply=False)
        if isinstance(res, tuple):
            code, val = res
            if code == "COOLDOWN":
                bot.send_message(call.message.chat.id, f"⏳ Подожди {BET_COOLDOWN} сек перед следующей ставкой")
            elif code == "NO_MONEY":
                bot.send_message(call.message.chat.id, "❌ Недостаточно бублей для ставки")
            elif code == "MIN_BET":
                bot.send_message(call.message.chat.id, f"❗ Минимальная ставка: {MIN_BET}")
            elif code == "NO_STAKE":
                bot.send_message(call.message.chat.id, "❗ Укажи ставку")
            else:
                text_result, new_bal = code, val
                bot.send_message(call.message.chat.id, f"{text_result}\n💰 Баланс: {new_bal}")
        else:
            bot.send_message(call.message.chat.id, "❗ Ошибка при обработке ставки.")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.error(f"bubl_callback_handler: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# === Luck (кнопки) ===
EMOJIS = [
    "😀","😎","🤡","👻","💀","🐵","🐸","🐱","🦊","🐼",
    "🐨","🐯","🦁","🐮","🐷","🐔","🐧","🐦","🐤","🐣",
    "🐥","🦆","🦅","🦉","🐺","🥰","🍎","😃","🙄","🎃","🤓","🤔"
]
_last_luck = {}

def luck_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_luck.get(uid, 0)
    if now - last < 10:
        bot.reply_to(message, f"⏳ Подожди {int(10 - (now - last))} сек перед следующей попыткой")
        return
    _last_luck[uid] = now
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
        chosen = int(parts[2]); lucky_index = int(parts[3])
        bal = _get_balance(uid)
        if bal <= 0:
            bot.answer_callback_query(call.id, "❌ У тебя нет бублей", show_alert=True)
            return
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        if chosen == lucky_index:
            gain = bal * 5
            _update_balance(uid, gain)
            bot.send_message(call.message.chat.id, f"🎉 Настоящий рандом показал свою хорошую сторону тебе! Баланс умножен в 5 раз.\n💰 Теперь у тебя {_get_balance(uid)} бублей.")
        else:
            loss = bal // 2
            _update_balance(uid, -loss)
            bot.send_message(call.message.chat.id, f"💀 Удача отвернулась от тебя. Минус {loss} бублей.\n💰 Остаток: {_get_balance(uid)}")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.error(f"luck_callback_handler error: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# === /chests ===
CHEST_COOLDOWN = 180  # 3 минуты
_last_chests = {}

SQUARES = ["🟥", "🟦", "🟩", "🟨", "🟪", "⬜️", "🟫", "⬛️"]

def chests_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    now = time.time()
    last = _last_chests.get(uid, 0)
    if now - last < CHEST_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int(CHEST_COOLDOWN - (now - last))} сек, чтобы открыть сундуки снова!")
        return
    _last_chests[uid] = now
    chosen = random.sample(SQUARES, 3)
    markup = types.InlineKeyboardMarkup()
    for i, sq in enumerate(chosen):
        cb = f"chests_{uid}_{i}"
        markup.add(types.InlineKeyboardButton(sq, callback_data=cb))
    bot.send_message(message.chat.id, "🗝️ По радио ты услышал легенду о счастливых сундуках. Выбирай сундук:", reply_markup=markup)

def chests_callback_handler(bot, call):
    try:
        parts = call.data.split("_")
        if len(parts) != 3 or parts[0] != "chests":
            return
        uid = int(parts[1])
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Не открывай сундуки другого путника!", show_alert=True)
            return
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        name = _display_name(uid)
        roll = random.random()
        if roll < 0.4:
            amount = random.randint(2000, 6000)
            _update_balance(uid, amount)
            _treasury_add(amount)   # 100% в сокровищницу
            bot.send_message(call.message.chat.id, f"🎉 {name}, сундук, который ты открыл, оказался щедрым! Он подарил +{amount} бублей.\n💰 Баланс: {_get_balance(uid)}")
        elif roll < 0.7:
            amount = random.randint(1000, 4000)
            _update_balance(uid, -amount)
            _treasury_add(amount)
            bot.send_message(call.message.chat.id, f"💀 {name}, сундук отобрал {amount} бублей.\n💰 Баланс: {_get_balance(uid)}")
        else:
            bot.send_message(call.message.chat.id, f"📦 {name}, сундук тебе ничего не дал... Может, он просто спит.")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.error(f"chests_callback_handler: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# === Дуэли /sf, ставки /bet, топы ===
_active_duels = {}              # chat_id -> duel_obj
_chat_duel_cooldown = {}        # chat_id -> last_end_ts
_player_duel_cooldown = {}      # user_id -> last_end_ts

CHAT_COOLDOWN = 60
PLAYER_COOLDOWN = 120
INVITE_TIMEOUT = 25
BETTING_PERIOD = 30  # время где другие могут ставить (сек)

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

def sf_command_handler(bot, message):
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
        'bets': {},         # bettor_id -> {'on': user_id, 'amount': int}
        'placed_sums': {},  # user_id -> total
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

BET_RE = re.compile(r'(?i)^/bet\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$')

def bet_handler(bot, message):
    chat_id = message.chat.id
    register_user(message)
    d = _active_duels.get(chat_id)
    if not d or d['state'] != 'betting':
        bot.reply_to(message, "❗ Сейчас нельзя делать ставки (нет фазы ставок).")
        return
    m = BET_RE.match((message.text or "").strip())
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
            helpers = _get_helpers(uid)
            if 'hut' in props:
                base += 15
            if 'communal' in props:
                base += 25
            if 'country' in props:
                base += 35   # country gives +35 HP
            if helpers.get("defender", 0):
                base += 30 * helpers.get("defender", 0)  # each defender gives +30 HP (stackable though typically 0/1)
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

            sent = bot.send_message(chat_id, text.format(attacker=_display_name(attacker), dmg=dmg) +
                             f"\n🩺 {_display_name(attacker)}: {hp[attacker]} HP | {_display_name(defender)}: {hp[defender]} HP")
            # удаляем сообщение хода через 8 секунд
            def _del_later(c=chat_id, m_id=sent.message_id):
                try:
                    time.sleep(8)
                    bot.delete_message(c, m_id)
                except:
                    pass
            threading.Thread(target=_del_later, daemon=True).start()

            time.sleep(2.5)
            attacker, defender = defender, attacker

            if round_no > 55:
                bot.send_message(chat_id, "⚠️ Дуэль заняла слишком много ходов — ничья. Возврат ставок.")
                for b, info in duel['bets'].items():
                    _update_balance(b, info['amount'])
                del _active_duels[chat_id]
                _chat_duel_cooldown[chat_id] = time.time()
                return

        winner = challenger if hp[target] == 0 else target
        loser = target if winner == challenger else challenger
        bot.send_message(chat_id, f"🏁 Победитель: {_display_name(winner)}! Поздравляем!")
        _inc_duel_win(winner, 1)

        # выплатить ставочникам: каждый ставочник, который ставил на победителя, получает коэффициент,
        # коэффициент можно вычислить по соотношению сумм. Простая логика: распределяем общий банк среди тех, кто ставил на победителя пропорционально ставкам
        total_on_winner = sum(info['amount'] for info in duel['bets'].values() if info['on'] == winner)
        total_on_loser = sum(info['amount'] for info in duel['bets'].values() if info['on'] != winner)
        total_pool = total_on_winner + total_on_loser
        # выплатим ставочникам, которые поставили на победителя: каждый получает свою ставку + долю от проигранных (умножение)
        if total_on_winner and total_on_loser:
            for bettor, info in list(duel['bets'].items()):
                if info['on'] == winner:
                    share = info['amount'] / total_on_winner
                    payout = info['amount'] + int(round( total_on_loser * share ))
                    _update_balance(bettor, payout)
                    _add_bettor_win(bettor, payout)
                    # если bettor == winner (игрок участвовал и ставил на себя), это допустимо — он получает payout
        # штраф проигравшему: теряет 32% своего баланса
        loser_bal = _get_balance(loser)
        penalty = int(math.floor(abs(loser_bal) * 0.32))
        if penalty > 0:
            _update_balance(loser, -penalty)
            _update_balance(winner, penalty * 2)  # победитель получает весь выигрыш ставочников умноженный на 2 (по вашему требованию)
        # удаляем дуэль и ставим кулдауны
        del _active_duels[chat_id]
        _chat_duel_cooldown[chat_id] = time.time()
        _player_duel_cooldown[challenger] = time.time()
        _player_duel_cooldown[target] = time.time()
    except Exception as e:
        log.exception(f"_run_duel error: {e}")
        try:
            del _active_duels[chat_id]
        except:
            pass

# === Топы ===
def topbubl_handler(bot, message):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT 10").fetchall()
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

# === Перевод (дать @user 100) ===
TRANSFER_RE = re.compile(r'(?i)^дать\s+(@?[A-Za-z0-9_]{1,32}|\d+)\s+(\d+)$')

def transfer_handler(bot, message):
    register_user(message)
    text = (message.text or '').strip()
    m = TRANSFER_RE.match(text)
    if not m:
        bot.reply_to(message, "❗ Используй: дать @user 100")
        return
    target_raw, amount_str = m.groups()
    amount = int(amount_str)
    if amount <= 0:
        bot.reply_to(message, "❗ Сумма должна быть положительной")
        return
    sender_id = message.from_user.id
    # поиск получателя
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

# === Админ: add/remove bubl ===
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

def add_bubl_handler(bot, message):
    admin_add_remove(bot, message, "add")

def remove_bubl_handler(bot, message):
    admin_add_remove(bot, message, "remove")

# === Сообщение от лица бота (xhp) ===
def xhp_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Ты за кого себя пытаешься выдать, малой?")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /xhp <текст>")
        return
    bot.send_message(message.chat.id, parts[1])

# === Админская рассылка /soo ===
def soo_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /soo <текст>")
        return
    text = parts[1]
    sent_users = 0
    failed_users = 0
    sent_chats = 0
    failed_chats = 0
    with db.get_connection() as conn:
        rows = conn.execute("SELECT user_id, last_seen_chat FROM users").fetchall()
    for user_id, last_chat in rows:
        try:
            bot.send_message(user_id, text)
            sent_users += 1
        except Exception:
            failed_users += 1
        time.sleep(0.05)
    chat_ids = set([r[1] for r in rows if r[1]])
    for chat_id in chat_ids:
        try:
            bot.send_message(chat_id, text)
            sent_chats += 1
        except Exception:
            failed_chats += 1
        time.sleep(0.05)
    bot.reply_to(message, f"✅ Рассылка завершена. ЛС: {sent_users} / {sent_users+failed_users}, Чаты: {sent_chats} / {sent_chats+failed_chats}")

# === wipe_prop (админ) ===
def wipe_prop_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    with db.get_connection() as conn:
        conn.execute("DELETE FROM properties")
        conn.commit()
    bot.reply_to(message, "✅ Все записи недвижимости удалены.")

# === Сокровищница handlers ===
TRE_ACTION_COOLDOWN = 30 * 60  # 30 минут
try:
    _tre_action_last
except NameError:
    _tre_action_last = {}

def tre_show_handler(bot, message):
    try:
        register_user(message)
        bal = _get_treasure_balance()
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🦹 Ограбить", callback_data="tre_rob"),
            types.InlineKeyboardButton("📥 Положить", callback_data="tre_put")
        )
        markup.row(
            types.InlineKeyboardButton("🙏 Попросить", callback_data="tre_ask"),
            types.InlineKeyboardButton("❌ Закрыть", callback_data="tre_close")
        )
        bot.reply_to(message, f"💎 Баланс сокровищницы: {bal} бублей", reply_markup=markup)
    except Exception as e:
        log.error(f"tre_show_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при открытии сокровищницы")

def tre_callback_handler(bot, call):
    try:
        data = (call.data or "").split("_")
        if not data or data[0] != "tre":
            return
        action = data[1] if len(data) > 1 else None
        uid = call.from_user.id
        now = time.time()
        key = (uid, action)
        last = _tre_action_last.get(key, 0)
        if now - last < TRE_ACTION_COOLDOWN:
            bot.answer_callback_query(call.id, f"⏳ Подожди {int(TRE_ACTION_COOLDOWN - (now-last))} сек для этой операции", show_alert=True)
            return
        tre_bal = _get_treasure_balance()
        if action == "rob":
            chance = 0.20
            if tre_bal <= 0:
                bot.answer_callback_query(call.id, "❗ В сокровищнице пусто", show_alert=True)
                return
            if random.random() < chance:
                pct = random.randint(5, 15)
                amount = max(1, int(tre_bal * pct / 100.0))
                _update_treasure_balance(-amount)
                _update_balance(uid, amount)
                bot.send_message(call.message.chat.id, f"🕵️ {_display_name(uid)}, удачная кража! Ты забрал {amount} бублей из сокровищницы.\n💎 Баланс сокровищницы: {_get_treasure_balance()}\n💰 Твой баланс: {_get_balance(uid)}")
            else:
                bot.send_message(call.message.chat.id, f"🚫 {_display_name(uid)}, попытка ограбления не удалась.")
            _tre_action_last[key] = now
            bot.answer_callback_query(call.id)
            return
        if action == "put":
            bal = _get_balance(uid)
            if bal <= 0:
                bot.answer_callback_query(call.id, "❌ У тебя нет бублей для вклада", show_alert=True)
                return
            amount = max(1, int(bal * 0.01))
            _update_balance(uid, -amount)
            _update_treasure_balance(amount)
            bot.send_message(call.message.chat.id, f"📥 {_display_name(uid)}, ты положил {amount} бублей в сокровищницу.\n💰 Твой баланс: {_get_balance(uid)}\n💎 Сокровищница: {_get_treasure_balance()}")
            _tre_action_last[key] = now
            bot.answer_callback_query(call.id)
            return
        if action == "ask":
            tre_bal = _get_treasure_balance()
            amount = max(1, int(tre_bal * 0.001))
            if amount <= 0:
                bot.send_message(call.message.chat.id, f"❗ {_display_name(uid)}, в сокровищнице сейчас нечего попросить.")
                _tre_action_last[key] = now
                bot.answer_callback_query(call.id)
                return
            _update_treasure_balance(-amount)
            _update_balance(uid, amount)
            bot.send_message(call.message.chat.id, f"🙏 {_display_name(uid)}, тебе выдали {amount} бублей из сокровищницы.\n💰 Твой баланс: {_get_balance(uid)}\n💎 Сокровищница: {_get_treasure_balance()}")
            _tre_action_last[key] = now
            bot.answer_callback_query(call.id)
            return
        if action == "close":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.answer_callback_query(call.id)
            return
        bot.answer_callback_query(call.id, "❗ Неизвестная команда", show_alert=True)
    except Exception as e:
        log.error(f"tre_callback_handler error: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка при обработке", show_alert=True)
        except:
            pass

# === Система рабства: /ensl, /sl, /desl, /escape, /sl_sell, /sl_buy, /topsl ===
def ensl_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /ensl @user")
        return
    target_raw = parts[1]
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = row[0] if row else None
    if not target_id:
        bot.reply_to(message, "❌ Цель не найдена.")
        return
    owner = message.from_user.id
    if target_id == owner:
        bot.reply_to(message, "❌ Нельзя поработить себя.")
        return
    if _is_slave(target_id):
        bot.reply_to(message, "❌ У цели уже есть владелец.")
        return
    # шанс зависит от недвижимости (каждая уменьшает шанс на 10%)
    base_chance = 0.5
    props = _get_properties(target_id)
    if 'hut' in props:
        base_chance -= 0.10
    if 'communal' in props:
        base_chance -= 0.10
    if 'country' in props:
        base_chance -= 0.10
    base_chance = max(0.05, base_chance)
    if random.random() < base_chance:
        _enslave(owner, target_id)
        bot.reply_to(message, f"✅ {_display_name(target_id)} теперь твой раб.")
    else:
        bot.reply_to(message, "❌ Попытка поработить не удалась.")

def sl_handler(bot, message):
    register_user(message)
    owner = message.from_user.id
    rows = _get_slaves_of(owner)
    if not rows:
        bot.reply_to(message, "У вас нет рабов.")
        return
    lines = []
    for slave_id, enslaved_at, last_tax in rows:
        lines.append(f"{_display_name(slave_id)} (id {slave_id}) — раб с {time.ctime(enslaved_at)}")
    bot.reply_to(message, "Ваши рабы:\n" + "\n".join(lines))

def desl_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2 and not getattr(message, 'reply_to_message', None):
        bot.reply_to(message, "❗ Формат: /desl @user или использовать команду в ответ на сообщение пользователя")
        return
    if getattr(message, 'reply_to_message', None) and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        target_raw = parts[1]
        if target_raw.isdigit():
            target_id = int(target_raw)
        else:
            with db.get_connection() as conn:
                r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
                target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден.")
        return
    owner = message.from_user.id
    # проверить что target_id — раб именно этого owner
    cur = _is_slave(target_id)
    if not cur or cur != owner:
        bot.reply_to(message, "❌ Этот пользователь не является вашим рабом.")
        return
    _release_slave(target_id)
    bot.reply_to(message, f"✅ {_display_name(target_id)} освобождён.")

def escape_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    owner = _is_slave(uid)
    if not owner:
        bot.reply_to(message, "❗ Вы не являетесь рабом.")
        return
    # шанс побега 35% уменьшён на 15% если у owner есть guard helper
    base = 0.35
    owner_helpers = _get_helpers(owner)
    if owner_helpers.get("guard", 0):
        base -= 0.15
    base = max(0.05, base)
    if random.random() < base:
        _release_slave(uid)
        bot.reply_to(message, "✅ Ты убежал и теперь свободен.")
    else:
        bot.reply_to(message, "❌ Попытка побега не удалась.")

def topsl_handler(bot, message):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT owner_id, COUNT(*) as cnt FROM slaves GROUP BY owner_id ORDER BY cnt DESC LIMIT 10").fetchall()
    if not rows:
        bot.reply_to(message, "Пока нет рабовладельцев.")
        return
    lines = []
    for i, (owner_id, cnt) in enumerate(rows, 1):
        lines.append(f"{i}. {_display_name(owner_id)} — {cnt} раб(ов)")
    bot.send_message(message.chat.id, "🏆 Топ рабовладельцев:\n" + "\n".join(lines))

def collect_handler(bot, message):
    # принудительный запуск налога/сбора для владельца
    register_user(message)
    owner = message.from_user.id
    total = _apply_hourly_tax_for_owner(owner)
    bot.reply_to(message, f"✅ Собрано с рабов: {total} бублей")

# === Продажа раба: /sl_sell и /sl_buy ===
def sl_sell_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /sl_sell <ник_раба_or_id>")
        return
    target_raw = parts[1]
    if target_raw.isdigit():
        slave_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            slave_id = r[0] if r else None
    if not slave_id:
        bot.reply_to(message, "❌ Раб не найден.")
        return
    seller = message.from_user.id
    # проверка, что slave действительно ваш раб
    cur_owner = _is_slave(slave_id)
    if not cur_owner or cur_owner != seller:
        bot.reply_to(message, "❌ Этот пользователь не является вашим рабом.")
        return
    # вычисляем цену: 4/5 * (0.7*баланс_раба + 0.4*баланс_владельца)
    slave_bal = _get_balance(slave_id)
    seller_bal = _get_balance(seller)
    price = int(math.floor( (0.7 * slave_bal + 0.4 * seller_bal) * 4.0 / 5.0 ))
    if price <= 0:
        bot.reply_to(message, "❌ Цена получилась нулевой — продажа невозможна.")
        return
    now = int(time.time())
    with db.get_connection() as conn:
        r = conn.execute("INSERT INTO slave_sales (slave_id, seller_id, price, created_at) VALUES (?, ?, ?, ?)",
                         (slave_id, seller, price, now))
        conn.commit()
        sale_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    bot.send_message(message.chat.id, f"🔖 Продажа раба выставлена: {_display_name(slave_id)} (id {slave_id})\nЦена: {price} бублей\nЧтобы купить — напишите: /sl_buy {sale_id}\nПервый, кто напишет /sl_buy {sale_id}, купит раба (проверьте баланс).")

def sl_buy_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /sl_buy <sale_id>")
        return
    sale_id_raw = parts[1]
    if not sale_id_raw.isdigit():
        bot.reply_to(message, "❗ sale_id должен быть числом")
        return
    sale_id = int(sale_id_raw)
    buyer = message.from_user.id
    with db.get_connection() as conn:
        row = conn.execute("SELECT slave_id, seller_id, price FROM slave_sales WHERE sale_id=?", (sale_id,)).fetchone()
        if not row:
            bot.reply_to(message, "❌ Продажа не найдена или уже завершена.")
            return
        slave_id, seller_id, price = row
        # проверка - slave должен быть все ещё рабом seller_id
        cur_owner = _is_slave(slave_id)
        if not cur_owner or cur_owner != seller_id:
            bot.reply_to(message, "❌ Этот раб больше не принадлежит продавцу. Операция отменена.")
            # удаляем запись на всякий случай
            conn.execute("DELETE FROM slave_sales WHERE sale_id=?", (sale_id,))
            conn.commit()
            return
        if buyer == seller_id:
            bot.reply_to(message, "❌ Нельзя купить своего раба.")
            return
        bal = _get_balance(buyer)
        if bal < price:
            bot.reply_to(message, "❌ У вас недостаточно средств для покупки.")
            return
        # перевод денег
        _update_balance(buyer, -price)
        _update_balance(seller_id, price)
        # смена владельца
        _enslave(buyer, slave_id)
        # удаляем заявку
        conn.execute("DELETE FROM slave_sales WHERE sale_id=?", (sale_id,))
        conn.commit()
    bot.send_message(message.chat.id, f"✅ {_display_name(buyer)} купил {_display_name(slave_id)} за {price} бублей у {_display_name(seller_id)}!")

# === /osebe (о себе) including helpers & tokens & properties ===
def osebe_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    nick = _get_nickname(uid) or message.from_user.first_name
    props_keys = _get_properties(uid)
    props = [PROPERTIES[k]["name"] for k in props_keys] if props_keys else ["Нет"]
    helpers = _get_helpers(uid)
    helper_lines = []
    if helpers.get("defender"): helper_lines.append("💂 Защитник")
    if helpers.get("guard"): helper_lines.append("👮 Охранник")
    if helpers.get("esoteric"): helper_lines.append("🧝 Эзотерик")
    if helpers.get("phoenix"): helper_lines.append("🐦‍🔥 Феникс")
    tokens = _get_tokens(uid)
    bank = _get_bbank(uid)
    bot.reply_to(message,
                 f"👤 О себе:\nИмя: {nick}\nБаланс: {_get_balance(uid)} бублей\nОкак-Токены: {tokens}\nНедвижимость: {', '.join(props)}\nПомощники: {', '.join(helper_lines) if helper_lines else 'Нет'}\nВ банке: {bank['bank_balance']} (инвестировано: {bank['invested']})")

# === /prop (показать недвижимость и наличие) ===
def prop_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    props = _get_properties(uid)
    lines = []
    for key, data in PROPERTIES.items():
        has = "✅" if key in props else "❌"
        lines.append(f"{has} {data['name']} — стоимость: {data['price']} бублей")
    bot.reply_to(message, "🏠 Твои/доступные недвижимости:\n" + "\n".join(lines))

# === /bbank, /invest, /withdraw handlers ===
def bbank_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    b = _get_bbank(uid)
    bot.reply_to(message, f"🏦 Бубль-Банк\nНа счету: {b['bank_balance']} бублей\nИнвестировано: {b['invested']} бублей\nЗаработано через инвестиции (для токенов): {b['earned_from_invest']} бублей\nКоманды: /invest <сумма>, /withdraw <сумма>")

def invest_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "❗ Используй: /invest <сумма>")
        return
    amount = int(parts[1])
    uid = message.from_user.id
    if amount < INVEST_MIN or amount > INVEST_MAX:
        bot.reply_to(message, f"❗ Инвестиция должна быть от {INVEST_MIN} до {INVEST_MAX} бублей")
        return
    cur_bal = _get_balance(uid)
    if cur_bal < amount:
        bot.reply_to(message, "❌ Недостаточно средств для инвестирования")
        return
    b = _get_bbank(uid)
    if b['invested'] + amount > BBANK_MAX_INVEST:
        bot.reply_to(message, f"❗ Превышен максимум инвестиций ({BBANK_MAX_INVEST})")
        return
    _update_balance(uid, -amount)
    _set_bbank(uid, bank_balance=b['bank_balance'] + amount, invested=b['invested'] + amount, last_withdraw_ts=b['last_withdraw_ts'], earned_from_invest=b['earned_from_invest'])
    bot.reply_to(message, f"✅ Вы инвестировали {amount} бублей. Инвестировано теперь: {_get_bbank(uid)['invested']}")

def withdraw_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "❗ Используй: /withdraw <сумма>")
        return
    amount = int(parts[1])
    uid = message.from_user.id
    b = _get_bbank(uid)
    now = int(time.time())
    if now - b['last_withdraw_ts'] < WITHDRAW_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int(WITHDRAW_COOLDOWN - (now - b['last_withdraw_ts']))} сек перед выводом снова")
        return
    if amount <= 0:
        bot.reply_to(message, "❗ Сумма должна быть положительной")
        return
    if b['bank_balance'] < amount:
        bot.reply_to(message, "❌ В банке недостаточно")
        return
    # переводим с bank_balance на основной баланс
    _set_bbank(uid, bank_balance=b['bank_balance'] - amount, invested=b['invested'], last_withdraw_ts=now, earned_from_invest=b['earned_from_invest'])
    _update_balance(uid, amount)
    bot.reply_to(message, f"✅ Вы вывели {amount} бублей. Баланс в банке: {_get_bbank(uid)['bank_balance']}")

# === /okakshop — магазин помощников ===
def okakshop_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    tokens = _get_tokens(uid)
    text = ("🪝Добро пожаловать в Окак-Шоп!🪝\n\n"
            "💂 Защитник — 2 Окак-Токена: +30 HP в дуэлях\n"
            "👮 Охранник — 4 Окак-Токена: уменьшает шансы побега вашего раба на 15%\n"
            "🧝 Эзотерик — 6 Окак-Токенов: открывает команду /shkatulka (доступна каждые 6 часов)\n"
            "🐦‍🔥 Феникс — 12 Окак-Токенов: удваивает заработки для рабочих команд\n\n"
            f"У вас: {tokens} Окак-Токенов\nВыберите покупку:")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💂 Защитник — 2", callback_data=f"okshop_buy_defender_{uid}"))
    markup.add(types.InlineKeyboardButton("👮 Охранник — 4", callback_data=f"okshop_buy_guard_{uid}"))
    markup.add(types.InlineKeyboardButton("🧝 Эзотерик — 6", callback_data=f"okshop_buy_esoteric_{uid}"))
    markup.add(types.InlineKeyboardButton("🐦‍🔥 Феникс — 12", callback_data=f"okshop_buy_phoenix_{uid}"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

def okakshop_callback_handler(bot, call):
    try:
        parts = call.data.split("_")
        if len(parts) < 4 or parts[0] != "okshop":
            return
        action = parts[1]  # buy
        item = parts[2]
        uid = int(parts[3])
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Это не ваша кнопка", show_alert=True)
            return
        cost_map = {"defender": 2, "guard": 4, "esoteric": 6, "phoenix": 12}
        if item not in cost_map:
            bot.answer_callback_query(call.id, "❌ Неизвестный товар", show_alert=True)
            return
        cost = cost_map[item]
        tokens = _get_tokens(uid)
        if tokens < cost:
            bot.answer_callback_query(call.id, "❌ Недостаточно Окак-Токенов", show_alert=True)
            return
        # списываем токены и выдаём helper
        _update_tokens(uid, -cost)
        # помечаем helper в базе
        cur = _get_helpers(uid)
        if item == "defender":
            _set_helper_field(uid, "defender", cur.get("defender", 0) + 1)
        elif item == "guard":
            _set_helper_field(uid, "guard", cur.get("guard", 0) + 1)
        elif item == "esoteric":
            _set_helper_field(uid, "esoteric", cur.get("esoteric", 0) + 1)
        elif item == "phoenix":
            _set_helper_field(uid, "phoenix", cur.get("phoenix", 0) + 1)
        bot.send_message(call.message.chat.id, f"✅ Покупка успешна: {item}. Токенов осталось: {_get_tokens(uid)}")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.exception(f"okakshop_callback_handler: {e}")
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except:
            pass

# === /shkatulka — только для владельцев esoteric helper ===
_shkatulka_last = {}

ZODIAC_EMOJIS = ["♈","♉","♊","♋","♌","♍","♎","♏","♐","♑","♒","♓"]

def shkatulka_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    helpers = _get_helpers(uid)
    if not helpers.get("esoteric", 0):
        bot.reply_to(message, "❌ У вас нет Эзотерика.")
        return
    now = time.time()
    last = _shkatulka_last.get(uid, 0)
    if now - last < 6*3600:
        bot.reply_to(message, f"⏳ Подожди {int(6*3600 - (now-last))} сек перед следующим использованием")
        return
    _shkatulka_last[uid] = now
    emojis = random.sample(ZODIAC_EMOJIS, 2)
    # place token under random button, money under the other
    lucky = random.choice([0,1])
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(emojis[0], callback_data=f"shk_{uid}_0_{lucky}"))
    markup.add(types.InlineKeyboardButton(emojis[1], callback_data=f"shk_{uid}_1_{lucky}"))
    bot.send_message(message.chat.id, "🔮 Выбери шкатулку:", reply_markup=markup)

def shkatulka_callback_handler(bot, call):
    try:
        parts = call.data.split("_")
        if len(parts) != 4 or parts[0] != "shk":
            return
        uid = int(parts[1])
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Это не ваша шкатулка", show_alert=True)
            return
        chosen = int(parts[2]); lucky = int(parts[3])
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        if chosen == lucky:
            _update_tokens(uid, 1)
            bot.send_message(call.message.chat.id, f"✨ {_display_name(uid)}, вы нашли 1 Окак-Токен! Токенов: {_get_tokens(uid)}")
        else:
            amount = random.randint(40_000, 80_000)
            # Phoenix doubles
            if _get_helpers(uid).get("phoenix", 0):
                amount *= 2
            _update_balance(uid, amount)
            _treasury_add(amount)  # по предыдущим требованиям — 100% сундуков идет в сокровищницу
            bot.send_message(call.message.chat.id, f"💰 {_display_name(uid)}, в шкатулке была наличность: +{amount} бублей.\nБаланс: {_get_balance(uid)}")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.exception(f"shkatulka_callback_handler: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass

# === Перекроенные команды работы: mafia, clean, pizza, waiter, lawyer, youtuber handled above ===

# === /bubl, /chests, дуэли уже реализованы ===

# === Регистрация всех хендлеров в register_extra_handlers(bot) ===
def register_extra_handlers(bot):
    # базовые
    @bot.message_handler(commands=['id'])
    def _h_id(m): id_handler(bot, m)

    @bot.message_handler(commands=['whoami'])
    def _h_whoami(m): whoami_handler(bot, m)

    @bot.message_handler(func=lambda message: isinstance(message.text, str) and message.text.lower() == "спасибо")
    def _h_thanks(m): thanks_handler(bot, m)

    # баланс (показываем также токены) 
    @bot.message_handler(commands=['balance'])
    def _h_balance(m):
        register_user(m)
        uid = m.from_user.id
        b = _get_balance(uid)
        t = _get_tokens(uid)
        bot.reply_to(m, f"💰 У тебя {b} бублей\n🪝 Окак-Токены: {t}")

    # бубли на улице
    @bot.message_handler(commands=['bomj'])
    def _h_street(m): street_handler(bot, m)

    # игры (команды pocket/casino/loto)
    @bot.message_handler(commands=['pocket'])
    def _h_pocket(m):
        bet_game_handler(bot, m, 0.70, 1.25,
                         ["😎Молодец, воришка. Ты потерял свои деньги на ходу, но получил больше - аж {win} бублей!",
                          "✨❄️Моя школа! {win} тебе начислено за твой проворот."],
                         ["🙄Ну ты и лоханулся... мало того, что ты ничего не украл, так у тебя украли {bet}!",
                          "🤵Мафия тобой разочарована. Мы оштрафовали тебя на {bet}, чтоб не втыкал."])

    @bot.message_handler(commands=['casino'])
    def _h_casino(m):
        bet_game_handler(bot, m, 0.35, 3.0,
                         ["🎰 Джекпот! {win} бублей за ставку {bet}.",
                          "🎲 Везёт! Забираешь {win} бублей (ставка {bet})."],
                         ["🃏 Крупье улыбается… Ставка {bet} ушла в дом.",
                          "💸 Рулетка безжалостна. Минус {bet}."])

    @bot.message_handler(commands=['loto'])
    def _h_loto(m):
        bet_game_handler(bot, m, 0.10, 14.0,
                         ["🎟 Счастливый билет! +{win} бублей (ставка {bet}).",
                          "🌟 Умный человек в очках выиграл {win} бублей скачать обои"],
                         ["🪙 Ой-ой-ой, не повезло. Ставка в аж {bet} бублей ушла в воздух.",
                          "🙃 Сегодня не твой день. Минус {bet}."])

    # bubl + callback
    @bot.message_handler(commands=['bubl'])
    def _h_bubl(m): bubl_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("bubl_"))
    def _h_bubl_cb(call): bubl_callback_handler(bot, call)

    # property buy/handlers
    @bot.message_handler(commands=['buy'])
    def _h_buy(m): buy_property_handler(bot, m)

    @bot.message_handler(commands=['buy_hut', 'buy_hut'])
    def _h_buy_hut(m): buy_hut_handler(bot, m)

    @bot.message_handler(commands=['buy_communal'])
    def _h_buy_comm(m): buy_communal_handler(bot, m)

    @bot.message_handler(commands=['buy_country'])
    def _h_buy_country(m): buy_country_handler(bot, m)

    @bot.message_handler(commands=['buy_cottage'])
    def _h_buy_cottage(m): buy_cottage_handler(bot, m)

    @bot.message_handler(commands=['buy_villa'])
    def _h_buy_villa(m): buy_villa_handler(bot, m)

    @bot.message_handler(commands=['buy_mansion'])
    def _h_buy_mansion(m): buy_mansion_handler(bot, m)

    # work commands
    @bot.message_handler(commands=['mafia'])
    def _h_mafia(m): mafia_handler(bot, m)

    @bot.message_handler(commands=['clean'])
    def _h_clean(m): clean_handler(bot, m)

    @bot.message_handler(commands=['pizza'])
    def _h_pizza(m): pizza_handler(bot, m)

    @bot.message_handler(commands=['waiter'])
    def _h_waiter(m): waiter_handler(bot, m)

    @bot.message_handler(commands=['lawyer'])
    def _h_lawyer(m): lawyer_handler(bot, m)

    @bot.message_handler(commands=['youtuber'])
    def _h_youtuber(m): youtuber_handler(bot, m)

    # nickname handlers
    @bot.message_handler(func=lambda message: isinstance(message.text, str) and NICK_RE.match(message.text.strip()))
    def _h_nick(m): nickname_handler(bot, m)

    @bot.message_handler(commands=['osebe'])
    def _h_osebe(m): osebe_handler(bot, m)

    @bot.message_handler(commands=['prop'])
    def _h_prop(m): prop_handler(bot, m)

    # top lists
    @bot.message_handler(commands=['topbubl'])
    def _h_topbubl(m): topbubl_handler(bot, m)

    @bot.message_handler(commands=['topsf'])
    def _h_topsf(m): topsf_handler(bot, m)

    @bot.message_handler(commands=['topst'])
    def _h_topst(m): topst_handler(bot, m)

    # transfers and admin
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("дать "))
    def _h_transfer(m): transfer_handler(bot, m)

    @bot.message_handler(commands=['add_bubl'])
    def _h_add_bubl(m): add_bubl_handler(bot, m)

    @bot.message_handler(commands=['remove_bubl'])
    def _h_remove_bubl(m): remove_bubl_handler(bot, m)

    @bot.message_handler(commands=['xhp'])
    def _h_xhp(m): xhp_handler(bot, m)

    @bot.message_handler(commands=['soo'])
    def _h_soo(m): soo_handler(bot, m)

    @bot.message_handler(commands=['wipe_prop'])
    def _h_wipeprop(m): wipe_prop_handler(bot, m)

    @bot.message_handler(commands=['wipe_nick'])
    def _h_wipe_nick(m): wipe_nick_handler(bot, m)

    @bot.message_handler(commands=['delete_nick'])
    def _h_delete_nick(m): delete_nick_handler(bot, m)

    # luck
    @bot.message_handler(commands=['luck'])
    def _h_luck(m): luck_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("luck_"))
    def _h_luck_cb(call): luck_callback_handler(bot, call)

    # tre
    @bot.message_handler(commands=['tre'])
    def _h_tre(m): tre_show_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("tre_"))
    def _h_tre_cb(call): tre_callback_handler(bot, call)

    # chests
    @bot.message_handler(commands=['chests'])
    def _h_chests(m): chests_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("chests_"))
    def _h_chests_cb(call): chests_callback_handler(bot, call)

    # duel system
    @bot.message_handler(commands=['sf'])
    def _h_sf(m): sf_command_handler(bot, m)

    @bot.message_handler(commands=['sf_accept'])
    def _h_sf_accept(m): sf_accept_handler(bot, m)

    @bot.message_handler(commands=['sf_decline'])
    def _h_sf_decline(m): sf_decline_handler(bot, m)

    @bot.message_handler(commands=['bet'])
    def _h_bet(m): bet_handler(bot, m)

    # shop callbacks
    @bot.message_handler(commands=['okakshop'])
    def _h_okakshop(m): okakshop_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("okshop_"))
    def _h_okakshop_cb(call): okakshop_callback_handler(bot, call)

    @bot.message_handler(commands=['shkatulka'])
    def _h_shkatulka(m): shkatulka_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("shk_"))
    def _h_shk_cb(call): shkatulka_callback_handler(bot, call)

    # sell/buy slaves
    @bot.message_handler(commands=['sl_sell'])
    def _h_sl_sell(m): sl_sell_handler(bot, m)

    @bot.message_handler(commands=['sl_buy'])
    def _h_sl_buy(m): sl_buy_handler(bot, m)

    # slavery system handlers
    @bot.message_handler(commands=['ensl'])
    def _h_ensl(m): ensl_handler(bot, m)

    @bot.message_handler(commands=['sl'])
    def _h_sl(m): sl_handler(bot, m)

    @bot.message_handler(commands=['desl'])
    def _h_desl(m): desl_handler(bot, m)

    @bot.message_handler(commands=['escape'])
    def _h_escape(m): escape_handler(bot, m)

    @bot.message_handler(commands=['topsl'])
    def _h_topsl(m): topsl_handler(bot, m)

    @bot.message_handler(commands=['collect'])
    def _h_collect(m): collect_handler(bot, m)

    # bank
    @bot.message_handler(commands=['bbank'])
    def _h_bbank(m): bbank_handler(bot, m)

    @bot.message_handler(commands=['invest'])
    def _h_invest(m): invest_handler(bot, m)

    @bot.message_handler(commands=['withdraw'])
    def _h_withdraw(m): withdraw_handler(bot, m)

    # shkatulka callback already registered above via 'shk_'
    # chests callback registered above

    # register bubl callback already added above

# === Конец файла extra_handlers.py ===