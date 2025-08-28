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
        "price": 95000000,
        "command": "youtuber",
        "cooldown": 600,  # 10 минут
        "income": (80000, 230000),
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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS psych (
            user_id INTEGER PRIMARY KEY,
            stage INTEGER DEFAULT 7,       -- 7..0 (7 стартовая)
            last_upgrade_ts INTEGER DEFAULT 0
        )
    """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS clans (
            clan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            don_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            wins INTEGER DEFAULT 0,
            last_war_ts INTEGER DEFAULT 0
        )
    """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_members (
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'member', -- donor roles: don / capo / member
            joined_at INTEGER NOT NULL,
            last_promote_ts INTEGER DEFAULT 0,
            UNIQUE(clan_id, user_id)
        )
    """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_goods (
            clan_id INTEGER PRIMARY KEY,
            goods INTEGER DEFAULT 0
        )
    """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_bans (
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            banned_at INTEGER NOT NULL,
            PRIMARY KEY (clan_id, user_id)
        )
    """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS clan_stats (
            clan_id INTEGER PRIMARY KEY,
            wars_won INTEGER DEFAULT 0
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
                conn.execute("INSERT INTO treasure (id, balance) VALUES (1, ?)", (10000000,))
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


# --- PSYCH helpers ---
PSYCH_STAGES = {
    7: "Глубокая депрессия",
    6: "Депрессия",
    5: "Тоска",
    4: "Упадок",
    3: "Грусть",
    2: "Обычное состояние",
    1: "Стабильность",
    0: "Счастье"
}
PSYCH_COOLDOWN = 15 * 60  # 15 минут в секундах

def _get_psych(user_id: int) -> dict:
    with db.get_connection() as conn:
        row = conn.execute("SELECT stage, last_upgrade_ts FROM psych WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO psych (user_id, stage, last_upgrade_ts) VALUES (?, ?, ?)", (user_id, 7, 0))
            conn.commit()
            return {"stage": 7, "last_upgrade_ts": 0}
        return {"stage": row[0], "last_upgrade_ts": row[1]}

def _set_psych(user_id: int, stage: int, ts: int=None):
    ts = int(time.time()) if ts is None else int(ts)
    with db.get_connection() as conn:
        conn.execute("INSERT INTO psych (user_id, stage, last_upgrade_ts) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET stage=excluded.stage, last_upgrade_ts=excluded.last_upgrade_ts", (user_id, stage, ts))
        conn.commit()

def _psych_upgrade_cost(stage_from: int):
    """
    Стоимость перехода со stage_from -> stage_from-1.
    Базовая цена 3_000, умножается на 3 на каждой ступени вверх (т.е. чем ближе к 0 — дороже).
    Но для stage 1 (Стабильность) — цена 2 Окак-токена, для stage 0 (Счастье) — 5 Окак-токенов.
    Возвращает tuple (is_token_cost:bool, amount:int)
    """
    if stage_from <= 1:
        # если уже 1 -> переход на 0: special token cost
        if stage_from == 1:
            return (True, 2)  # 2 токена на переход 1->0
        return (True, 5)      # если вдруг 0->? (нереально), оставить
    # обычные бубли
    base = 3000
    # сколько раз умножать: (7 - stage_from) ? но логичнее: cost grows, 
    # для простоты: cost = base * (3 ** (7 - stage_from))
    exponent = max(0, 7 - stage_from)
    amount = int(base * (3 ** exponent))
    return (False, amount)

def _can_upgrade_psych(user_id: int):
    data = _get_psych(user_id)
    now = int(time.time())
    return now - data["last_upgrade_ts"] >= PSYCH_COOLDOWN

# --- CLAN helpers ---
def _count_clans_in_chat(chat_id: int) -> int:
    with db.get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM clans WHERE chat_id=?", (chat_id,)).fetchone()[0] or 0

def _get_clan_by_name(chat_id: int, name: str):
    with db.get_connection() as conn:
        return conn.execute("SELECT clan_id, name, don_id, created_at FROM clans WHERE chat_id=? AND LOWER(name)=LOWER(?)", (chat_id, name)).fetchone()

def _get_member_role(clan_id: int, user_id: int):
    with db.get_connection() as conn:
        r = conn.execute("SELECT role FROM clan_members WHERE clan_id=? AND user_id=?", (clan_id, user_id)).fetchone()
        return r[0] if r else None

def _add_member(clan_id: int, user_id: int, role="member"):
    ts = int(time.time())
    with db.get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)", (clan_id, user_id, role, ts))
        conn.commit()

def _remove_member(clan_id: int, user_id: int):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM clan_members WHERE clan_id=? AND user_id=?", (clan_id, user_id))
        conn.commit()

def _clan_goods_get(clan_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT goods FROM clan_goods WHERE clan_id=?", (clan_id,)).fetchone()
        return row[0] if row else 0

def _clan_goods_add(clan_id: int, amount: int):
    with db.get_connection() as conn:
        conn.execute("INSERT INTO clan_goods (clan_id, goods) VALUES (?, ?) ON CONFLICT(clan_id) DO UPDATE SET goods = goods + excluded.goods", (clan_id, amount))
        conn.commit()

def _clan_goods_subtract(clan_id: int, amount: int):
    with db.get_connection() as conn:
        cur = _clan_goods_get(clan_id)
        newv = max(0, cur - amount)
        conn.execute("INSERT INTO clan_goods (clan_id, goods) VALUES (?, ?) ON CONFLICT(clan_id) DO UPDATE SET goods = ?", (clan_id, newv, newv))
        conn.commit()

def _is_banned_from_clan(clan_id:int, user_id:int) -> bool:
    with db.get_connection() as conn:
        row = conn.execute("SELECT 1 FROM clan_bans WHERE clan_id=? AND user_id=?", (clan_id,user_id)).fetchone()
        return bool(row)
        
        
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
            "pocket": (0.65, 2,
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
CHEST_COOLDOWN = 30  # 30sec
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

# === Admin: add/remove property handlers (only OWNER) ===
def _normalize_property_key(key_raw: str):
    """Вернёт canonical key из PROPERTIES по разным вариантам ввода или None."""
    if not key_raw:
        return None
    k = key_raw.lower().strip()
    # прямое совпадение с ключом
    if k in PROPERTIES:
        return k
    # синонимы
    synonyms = {
        "hut": ("hut", "хижина", "хижина_на_отшибе"),
        "communal": ("communal", "коммуналка", "коммуналка_в_гетто"),
        "country": ("country", "загородный", "загородный_дом"),
        "cottage": ("cottage", "коттедж", "стандартный"),
        "villa": ("villa", "вилла", "моря"),
        "mansion": ("mansion", "особняк", "роскошный_особняк"),
    }
    for canon, variants in synonyms.items():
        if k in variants:
            return canon
    return None

def _find_user_id_from_mention_or_id(raw: str):
    """Ищем user_id по строке: @username или строка с цифрами. Возвращает int или None."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    username = raw.lstrip("@")
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT user_id FROM users WHERE username=?", (username,)).fetchone()
            return row[0] if row else None
    except Exception as e:
        log.exception(f"_find_user_id_from_mention_or_id error: {e}")
        return None

def add_prop_handler(bot, message):
    """
    /add_prop @username <property_key>  -- только OWNER, добавить недвижимость пользователю
    Можно использовать reply: ответьте командой на сообщение пользователя и укажите ключ: /add_prop hut
    """
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return

    register_user(message)  # безопасно — гарантирует наличие пользователя в БД

    # извлекаем цель и ключ
    target_id = None
    parts = (message.text or "").split()
    if getattr(message, "reply_to_message", None) and message.reply_to_message.from_user:
        # если reply — /add_prop hut  или /add_prop  hut (в reply)
        if len(parts) >= 2:
            key_raw = parts[1]
        else:
            bot.reply_to(message, "❗ В reply-режиме: укажите ключ свойства: /add_prop <ключ>")
            return
        target_id = message.reply_to_message.from_user.id
    else:
        if len(parts) < 3:
            bot.reply_to(message, "❗ Использование: /add_prop @username <ключ> (например: /add_prop @ivan hut)")
            return
        target_raw = parts[1]
        key_raw = parts[2]
        target_id = _find_user_id_from_mention_or_id(target_raw)
        if not target_id:
            bot.reply_to(message, "❌ Пользователь не найден в базе. Попросите написать боту /start.")
            return

    key = _normalize_property_key(key_raw)
    if not key:
        bot.reply_to(message, "❗ Неизвестный ключ недвижимости. Доступно: " + ", ".join(PROPERTIES.keys()))
        return

    # проверка — есть ли уже
    owned = _get_properties(target_id)
    if key in owned:
        bot.reply_to(message, f"ℹ️ У {_display_name(target_id)} уже есть {PROPERTIES[key]['name']}.")
        return

    # записываем
    try:
        _buy_property_record(target_id, key)
        bot.reply_to(message, f"✅ {PROPERTIES[key]['name']} добавлена пользователю {_display_name(target_id)}.")
    except Exception as e:
        log.exception(f"add_prop_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при добавлении недвижимости.")

def remove_prop_handler(bot, message):
    """
    /remove_prop @username <property_key>  -- только OWNER, удалить недвижимость у пользователя
    Можно использовать reply: ответ на сообщение пользователя и указать ключ: /remove_prop hut
    """
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return

    register_user(message)

    parts = (message.text or "").split()
    if getattr(message, "reply_to_message", None) and message.reply_to_message.from_user:
        if len(parts) >= 2:
            key_raw = parts[1]
        else:
            bot.reply_to(message, "❗ В reply-режиме: укажите ключ свойства: /remove_prop <ключ>")
            return
        target_id = message.reply_to_message.from_user.id
    else:
        if len(parts) < 3:
            bot.reply_to(message, "❗ Использование: /remove_prop @username <ключ>")
            return
        target_raw = parts[1]
        key_raw = parts[2]
        target_id = _find_user_id_from_mention_or_id(target_raw)
        if not target_id:
            bot.reply_to(message, "❌ Пользователь не найден в базе.")
            return

    key = _normalize_property_key(key_raw)
    if not key:
        bot.reply_to(message, "❗ Неизвестный ключ недвижимости. Доступно: " + ", ".join(PROPERTIES.keys()))
        return

    # проверка наличия и удаление
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT 1 FROM properties WHERE user_id=? AND property_key=?", (target_id, key)).fetchone()
            if not row:
                bot.reply_to(message, f"ℹ️ У {_display_name(target_id)} нет {PROPERTIES[key]['name']}.")
                return
            conn.execute("DELETE FROM properties WHERE user_id=? AND property_key=?", (target_id, key))
            conn.commit()
        bot.reply_to(message, f"✅ {PROPERTIES[key]['name']} удалена у {_display_name(target_id)}.")
    except Exception as e:
        log.exception(f"remove_prop_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при удалении недвижимости.")
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
                pct = random.randint(0.1, 3)
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
            amount = max(1, int(tre_bal * 0.0001))
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

# --- Slave management helpers (вставить перед ensl_handler) ---
# ---------------- PSYCH handlers ----------------
def psychs_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    data = _get_psych(uid)
    stage = data["stage"]
    next_stage = max(0, stage - 1)
    now = int(time.time())
    can_upgrade = _can_upgrade_psych(uid)
    token_cost_or_bubl = _psych_upgrade_cost(stage)
    if token_cost_or_bubl[0]:
        cost_descr = f"{token_cost_or_bubl[1]} Окак-Токенов"
    else:
        cost_descr = f"{token_cost_or_bubl[1]} бублей"
    text = (
        f"🧠 Текущее состояние: {PSYCH_STAGES.get(stage, str(stage))} (уровень {stage})\n"
        f"Следующее состояние: {PSYCH_STAGES.get(next_stage, str(next_stage))} (уровень {next_stage})\n\n"
        f"Цена перехода: {cost_descr}\n"
        f"Кулдаун между походами: {int(PSYCH_COOLDOWN/60)} минут\n"
    )
    markup = types.InlineKeyboardMarkup()
    btn_text = "Пойти к психологу" if can_upgrade else "Пойти к психологу (еще не готов)"
    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"psych_upgrade_{uid}"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

def psych_callback_handler(bot, call):
    try:
        parts = call.data.split("_")
        if parts[0] != "psych" or parts[1] != "upgrade":
            return
        uid = int(parts[2])
        if call.from_user.id != uid:
            bot.answer_callback_query(call.id, "❌ Эта кнопка не для вас", show_alert=True)
            return
        # start process
        data = _get_psych(uid)
        stage = data["stage"]
        if stage <= 0:
            bot.answer_callback_query(call.id, "ℹ️ У вас уже максимальное состояние (Счастье).", show_alert=True)
            return
        if not _can_upgrade_psych(uid):
            bot.answer_callback_query(call.id, "⏳ Кулдаун ещё не прошёл", show_alert=True)
            return
        is_token_cost, cost = _psych_upgrade_cost(stage)
        if is_token_cost:
            # требуются токены
            tokens = _get_tokens(uid)
            if tokens < cost:
                bot.answer_callback_query(call.id, f"❌ Нужно {cost} Окак-Токенов. У вас: {tokens}", show_alert=True)
                return
            _update_tokens(uid, -cost)
        else:
            bal = _get_balance(uid)
            if bal < cost:
                bot.answer_callback_query(call.id, f"❌ Нужно {cost} бублей. Баланс: {bal}", show_alert=True)
                return
            _update_balance(uid, -cost)
            # при расходе бублей ничего дополнительно
        # апгрейд
        new_stage = stage - 1
        _set_psych(uid, new_stage)
        bot.answer_callback_query(call.id, f"✅ Вы улучшили состояние: {PSYCH_STAGES.get(new_stage)}", show_alert=True)
    except Exception as e:
        log.exception(f"psych_callback_handler error: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass


# ---------------- CLAN handlers ----------------
def clan_create_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    # только игроки с состоянием "Обычное состояние" (stage == 2)
    psych = _get_psych(uid)
    if psych["stage"] != 2:
        bot.reply_to(message, "❌ Создавать клан может только игрок в состоянии 'Обычное состояние'.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_create <название> (макс 30 символов, только одна раскладка)")
        return
    name = parts[1].strip()
    if len(name) > 30:
        bot.reply_to(message, "❗ Название слишком длинное (макс 30 символов).")
        return
    # проверка раскладки: все русские или все латинские
    def _is_all_ru(s):
        return all('а' <= c <= 'я' or 'А' <= c <= 'Я' or c == 'ё' or c == 'Ё' or not c.isalpha() for c in s)
    def _is_all_en(s):
        return all('a' <= c.lower() <= 'z' or not c.isalpha() for c in s)
    if not (_is_all_ru(name) or _is_all_en(name)):
        bot.reply_to(message, "❗ Название должно состоять только из русских или только из латинских букв (без смешения).")
        return
    chat_id = message.chat.id
    if _count_clans_in_chat(chat_id) >= 4:
        bot.reply_to(message, "❌ В этом чате уже 4 клана — больше нельзя создать.")
        return
    now = int(time.time())
    with db.get_connection() as conn:
        conn.execute("INSERT INTO clans (chat_id, name, don_id, created_at) VALUES (?, ?, ?, ?)", (chat_id, name, uid, now))
        clan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)", (clan_id, uid, "don", now))
        conn.execute("INSERT OR IGNORE INTO clan_goods (clan_id, goods) VALUES (?, ?)", (clan_id, 0))
        conn.commit()
    bot.reply_to(message, f"✅ Клан '{name}' создан. Ты — Дон.")

def clan_join_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_join <название>")
        return
    name = parts[1].strip()
    chat_id = message.chat.id
    clan = _get_clan_by_name(chat_id, name)
    if not clan:
        bot.reply_to(message, "❌ Клан не найден.")
        return
    clan_id = clan[0]
    uid = message.from_user.id
    # требование: в него как минимум Упадок (stage >=4)
    psych = _get_psych(uid)
    if psych["stage"] > 4:
        bot.reply_to(message, "❌ Вступать можно только если у тебя состояние лучше или равно 'Упадок' (слабаков не берут).")
        return
    # провека бана
    if _is_banned_from_clan(clan_id, uid):
        bot.reply_to(message, "❌ Ты безвозвратно исключён в этом клане.")
        return
    _add_member(clan_id, uid, "member")
    bot.reply_to(message, f"✅ Ты вступил в клан '{clan[1]}'.")

def clan_kick_handler(bot, message):
    # формат: /clan_kick @user (только Дон)
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_kick @user")
        return
    target_raw = parts[1]
    chat_id = message.chat.id
    uid = message.from_user.id
    # найдем клан, где юзер дон
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id, name FROM clans WHERE chat_id=? AND don_id=?", (chat_id, uid)).fetchone()
    if not row:
        bot.reply_to(message, "❌ Ты не Дон ни одного клана в этом чате.")
        return
    clan_id, cname = row
    # find target id
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден.")
        return
    # confirm via button
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("Подтвердить", callback_data=f"clan_kick_confirm_{clan_id}_{target_id}_{uid}"),
        types.InlineKeyboardButton("Отмена", callback_data=f"clan_kick_cancel_{clan_id}_{target_id}_{uid}")
    )
    bot.send_message(chat_id, f"⚠️ Дон {_display_name(uid)} предлагает исключить {_display_name(target_id)} из клана '{cname}'. Подтверждаете?", reply_markup=markup)

def clan_kick_callback(bot, call):
    try:
        parts = call.data.split("_")
        if parts[0] != "clan" or parts[1] not in ("kick",):
            return
        action = parts[1]
        sub = parts[2]  # confirm/cancel
        clan_id = int(parts[3])
        target_id = int(parts[4])
        initiator = int(parts[5])
        # only initiator or owner can press
        if call.from_user.id != initiator:
            bot.answer_callback_query(call.id, "❌ Только инициатор может нажать", show_alert=True)
            return
        if sub == "confirm":
            _remove_member(clan_id, target_id)
            bot.send_message(call.message.chat.id, f"✅ {_display_name(target_id)} исключён из клана.")
        else:
            bot.send_message(call.message.chat.id, "ℹ️ Операция отменена.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.exception(f"clan_kick_callback err: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass

def clan_ban_handler(bot, message):
    # /clan_ban @user  (аналогично kick, но в таблице ban)
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_ban @user")
        return
    target_raw = parts[1]
    chat_id = message.chat.id
    uid = message.from_user.id
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id, name FROM clans WHERE chat_id=? AND don_id=?", (chat_id, uid)).fetchone()
    if not row:
        bot.reply_to(message, "❌ Ты не Дон клана.")
        return
    clan_id, cname = row
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден.")
        return
    with db.get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO clan_bans (clan_id, user_id, banned_at) VALUES (?, ?, ?)", (clan_id, target_id, int(time.time())))
        conn.commit()
    _remove_member(clan_id, target_id)
    bot.reply_to(message, f"✅ {_display_name(target_id)} забанен в клане '{cname}'.")

def clan_unban_handler(bot, message):
    # /clan_unban @user
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_unban @user")
        return
    target_raw = parts[1]
    chat_id = message.chat.id
    uid = message.from_user.id
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id FROM clans WHERE chat_id=? AND don_id=?", (chat_id, uid)).fetchone()
    if not row:
        bot.reply_to(message, "❌ Ты не Дон клана.")
        return
    clan_id = row[0]
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден.")
        return
    with db.get_connection() as conn:
        conn.execute("DELETE FROM clan_bans WHERE clan_id=? AND user_id=?", (clan_id, target_id))
        conn.commit()
    bot.reply_to(message, f"✅ {_display_name(target_id)} разбанен.")

def clans_handler(bot, message):
    chat_id = message.chat.id
    with db.get_connection() as conn:
        rows = conn.execute("SELECT clan_id, name, don_id FROM clans WHERE chat_id=?", (chat_id,)).fetchall()
    if not rows:
        bot.reply_to(message, "ℹ️ В этом чате нет кланов.")
        return
    lines = []
    with db.get_connection() as conn:
        for clan_id, name, don_id in rows:
            count = conn.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id=?", (clan_id,)).fetchone()[0] or 0
            total_money = 0
            # сумма балансов участников
            members = conn.execute("SELECT user_id FROM clan_members WHERE clan_id=?", (clan_id,)).fetchall()
            for (muid,) in members:
                total_money += _get_balance(muid)
            lines.append(f"{name} — участников: {count}, дон: {_display_name(don_id)}, сумма бублей участников: {total_money}")
    bot.send_message(message.chat.id, "📜 Список кланов:\n\n" + "\n".join(lines))

def clan_grind_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    chat_id = message.chat.id
    # find clan where user is member
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id FROM clan_members WHERE user_id=?", (uid,)).fetchone()
    if not row:
        bot.reply_to(message, "❗ Ты не состоишь в клане.")
        return
    clan_id = row[0]
    # cooldown per-user 40 sec — используем simple memory dict
    if not hasattr(clan_grind_handler, "_last_grind"): clan_grind_handler._last_grind = {}
    now = time.time()
    last = clan_grind_handler._last_grind.get(uid, 0)
    if now - last < 40:
        bot.reply_to(message, f"⏳ Подожди {int(40 - (now - last))} сек.")
        return
    clan_grind_handler._last_grind[uid] = now
    gained = random.randint(2,5)
    _clan_goods_add(clan_id, gained)
    bot.reply_to(message, f"📦 С вылазки ты добыл запретных {gained} товар(ов) для склада клана. Текущий склад: {_clan_goods_get(clan_id)}")

def clan_up_handler(bot, message):
    # /clan_up @user — Дон повышает до Капо. Кулдаун 36 часов на повышение для Дона
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_up @user")
        return
    target_raw = parts[1]
    chat_id = message.chat.id
    caller = message.from_user.id
    with db.get_connection() as conn:
        clan = conn.execute("SELECT clan_id FROM clans WHERE chat_id=? AND don_id=?", (chat_id, caller)).fetchone()
    if not clan:
        bot.reply_to(message, "❌ Ты не Дон.")
        return
    clan_id = clan[0]
    # find target id
    if target_raw.isdigit():
        target_id = int(target_raw)
    else:
        with db.get_connection() as conn:
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден.")
        return
    # find last promote time for this clan donor: stored in clan_members.last_promote_ts for donor
    with db.get_connection() as conn:
        donor_row = conn.execute("SELECT last_promote_ts FROM clan_members WHERE clan_id=? AND user_id=?", (clan_id, caller)).fetchone()
        last_promote = donor_row[0] if donor_row else 0
    if time.time() - last_promote < 36*3600:
        bot.reply_to(message, "⏳ Ты недавно повышал — подожди.")
        return
    # promote
    with db.get_connection() as conn:
        conn.execute("UPDATE clan_members SET role='capo', last_promote_ts=? WHERE clan_id=? AND user_id=?", (int(time.time()), clan_id, target_id))
        # update donor last_promote_ts
        conn.execute("UPDATE clan_members SET last_promote_ts=? WHERE clan_id=? AND user_id=?", (int(time.time()), clan_id, caller))
        conn.commit()
    bot.reply_to(message, f"✅ {_display_name(target_id)} повышен до Капо в клане.")

def clan_war_handler(bot, message):
    # /clan_war <clan_name> — only Don
    register_user(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_war <название>")
        return
    target_name = parts[1].strip()
    chat_id = message.chat.id
    caller = message.from_user.id
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id, name, created_at, last_war_ts FROM clans WHERE chat_id=? AND don_id=?", (chat_id, caller)).fetchone()
    if not row:
        bot.reply_to(message, "❌ Ты не Дон.")
        return
    clan_id, name, created_at, last_war_ts = row
    # check target clan
    target = _get_clan_by_name(chat_id, target_name)
    if not target:
        bot.reply_to(message, "❌ Клан-цель не найден.")
        return
    target_id = target[0]
    # can't war itself
    if target_id == clan_id:
        bot.reply_to(message, "❌ Нельзя объявить войну самому себе.")
        return
    # cannot declare war within 2 hours of creating clan
    if time.time() - created_at < 2*3600:
        bot.reply_to(message, "❌ Ваш клан слишком молод для объявления войны (меньше 2 часов после создания).")
        return
    # clan cooldown 4 hours
    if time.time() - last_war_ts < 4*3600:
        bot.reply_to(message, "⏳ Ваш клан недавно объявлял войну — подождите.")
        return
    # compute HPs: HP каждого участника (base 100 + property bonuses) * (sum of tokens of don+capo)
    def clan_total_hp_and_tokens(cid):
        total_hp = 0
        tokens = 0
        with db.get_connection() as conn:
            members = conn.execute("SELECT user_id, role FROM clan_members WHERE clan_id=?", (cid,)).fetchall()
        for uid, role in members:
            # compute HP as in duels
            props = _get_properties(uid)
            base = 100
            if 'hut' in props: base += 15
            if 'communal' in props: base += 25
            if 'country' in props: base += 35
            helpers = _get_helpers(uid)
            if helpers.get("defender",0):
                base += 30 * helpers.get("defender",0)
            total_hp += base
            if role in ("don","capo"):
                tokens += _get_tokens(uid)
        return total_hp, tokens

    hp_a, tokens_a = clan_total_hp_and_tokens(clan_id)
    hp_b, tokens_b = clan_total_hp_and_tokens(target_id)
    # attack strength random between goods/2 and goods
    goods_a = _clan_goods_get(clan_id)
    goods_b = _clan_goods_get(target_id)
    atk_a = random.randint(max(1, goods_a//2), max(1, goods_a))
    atk_b = random.randint(max(1, goods_b//2), max(1, goods_b))
    # multiply attack by token factor (don+capo tokens)
    atk_a = int(atk_a * (1 + tokens_a/100.0))
    atk_b = int(atk_b * (1 + tokens_b/100.0))

    # resolve
    # a_score = hp_a + atk_a, b_score = hp_b + atk_b
    score_a = hp_a + atk_a
    score_b = hp_b + atk_b
    # texts
    bot.send_message(chat_id, f"⚔️ Война: {_display_name(caller)} объявил войну клану {_display_name(target[2]) if len(target)>2 else target_name}!\nАтака: {atk_a}/{atk_b} — HP: {hp_a}/{hp_b}")
    if score_a == score_b:
        bot.send_message(chat_id, "⚖️ Ничья — война не принесла изменений.")
    elif score_a > score_b:
        # a wins
        stolen = int(_clan_goods_get(target_id) * 0.8)
        _clan_goods_subtract(target_id, stolen)
        _clan_goods_add(clan_id, stolen)
        # record wins
        with db.get_connection() as conn:
            conn.execute("UPDATE clans SET wins = wins + 1, last_war_ts=? WHERE clan_id=?", (int(time.time()), clan_id))
            conn.execute("UPDATE clan_stats SET wars_won = COALESCE(wars_won,0) + 1 WHERE clan_id=?", (clan_id,))
            conn.commit()
        bot.send_message(chat_id, f"🏆 Победа! Ваш клан захватил {stolen} товаров.")
    else:
        # b wins
        stolen = int(_clan_goods_get(clan_id) * 0.8)
        _clan_goods_subtract(clan_id, stolen)
        _clan_goods_add(target_id, stolen)
        with db.get_connection() as conn:
            conn.execute("UPDATE clans SET last_war_ts=? WHERE clan_id=?", (int(time.time()), clan_id))
            conn.commit()
        bot.send_message(chat_id, f"💥 Поражение. Противник отобрал {stolen} товаров.")

def clan_sell_handler(bot, message):
    # /clan_sell — Don или Capo every 10 hours, needs goods > 80
    register_user(message)
    uid = message.from_user.id
    chat_id = message.chat.id
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id, name, don_id FROM clans WHERE chat_id=? AND (don_id=? OR EXISTS(SELECT 1 FROM clan_members WHERE clan_id=clans.clan_id AND user_id=? AND role='capo'))", (chat_id, uid, uid)).fetchone()
    if not row:
        bot.reply_to(message, "❌ Ты не Дон и не Капо в клане.")
        return
    clan_id = row[0]
    role = _get_member_role(clan_id, uid)
    goods = _clan_goods_get(clan_id)
    if goods < 80:
        bot.reply_to(message, "❗ Товаров меньше 80 — нельзя продавать.")
        return
    # cooldown per role: store last_war_ts reused? better to do per-member cooldown; for brevity: simple per-clan last sell stored in clans.last_war_ts (repurposed)
    with db.get_connection() as conn:
        last_sell = conn.execute("SELECT last_war_ts FROM clans WHERE clan_id=?", (clan_id,)).fetchone()[0] or 0
    if time.time() - last_sell < 10*3600:
        bot.reply_to(message, "⏳ Клан недавно продавал товары — подождите.")
        return
    # compute sold percent
    if role == "don":
        percent = 0.70
    else:
        percent = 0.55
    sold = int(goods * percent)
    # each good sells for random between 1400 and 14000
    total = 0
    for _ in range(sold):
        total += random.randint(1400, 14000)
    # add entire total to treasury
    _treasury_add(total)
    # distribute: 30% to Don, 30% to Capo(s) (equally), 40% to other members
    share_don = int(total * 0.30)
    share_capo = int(total * 0.30)
    share_members = int(total * 0.40)
    # pay Don
    with db.get_connection() as conn:
        don_row = conn.execute("SELECT don_id FROM clans WHERE clan_id=?", (clan_id,)).fetchone()
        don_id = don_row[0] if don_row else None
        if don_id:
            _update_balance(don_id, share_don)
        capos = conn.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND role='capo'", (clan_id,)).fetchall()
        capo_count = len(capos)
        if capo_count:
            per_capo = share_capo // capo_count
            for (cid,) in capos:
                _update_balance(cid, per_capo)
        members = conn.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND role='member'", (clan_id,)).fetchall()
        member_count = len(members)
        if member_count:
            per_member = share_members // member_count
            for (mid,) in members:
                _update_balance(mid, per_member)
        # reduce goods
        _clan_goods_subtract(clan_id, sold)
        # update last_war_ts used as last_sell_ts now
        conn.execute("UPDATE clans SET last_war_ts=? WHERE clan_id=?", (int(time.time()), clan_id))
        conn.commit()
    bot.reply_to(message, f"💰 Продано {sold} товаров на сумму {total} бублей. Деньги распределены. Склад: {_clan_goods_get(clan_id)}")

def clan_top_handler(bot, message):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT c.name, cs.wars_won, (SELECT COUNT(*) FROM clan_members m WHERE m.clan_id=c.clan_id) as members FROM clans c LEFT JOIN clan_stats cs ON c.clan_id=cs.clan_id WHERE c.chat_id=? ORDER BY cs.wars_won DESC LIMIT 10", (message.chat.id,)).fetchall()
    if not rows:
        bot.reply_to(message, "ℹ️ Кланов нет.")
        return
    lines = []
    for i, (name, wins, members) in enumerate(rows, 1):
        lines.append(f"{i}. {name} — побед: {wins or 0}, участников: {members}")
    bot.send_message(message.chat.id, "🏆 Топ кланов:\n" + "\n".join(lines))

def clan_delete_handler(bot, message):
    # only Don, confirmation
    register_user(message)
    uid = message.from_user.id
    chat_id = message.chat.id
    with db.get_connection() as conn:
        row = conn.execute("SELECT clan_id, name FROM clans WHERE chat_id=? AND don_id=?", (chat_id, uid)).fetchone()
    if not row:
        bot.reply_to(message, "❌ Ты не Дон.")
        return
    clan_id, cname = row
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Подтвердить удаление", callback_data=f"clan_delete_confirm_{clan_id}_{uid}"),
               types.InlineKeyboardButton("Отмена", callback_data=f"clan_delete_cancel_{clan_id}_{uid}"))
    bot.send_message(chat_id, f"⚠️ Подтвердите удаление клана '{cname}' (действие необратимо).", reply_markup=markup)

def clan_delete_callback(bot, call):
    try:
        parts = call.data.split("_")
        if parts[0] != "clan" or parts[1] != "delete":
            return
        action = parts[2]  # confirm/cancel
        clan_id = int(parts[3])
        initiator = int(parts[4])
        if call.from_user.id != initiator:
            bot.answer_callback_query(call.id, "❌ Только Дон может подтвердить", show_alert=True)
            return
        if action == "confirm":
            with db.get_connection() as conn:
                conn.execute("DELETE FROM clan_members WHERE clan_id=?", (clan_id,))
                conn.execute("DELETE FROM clan_goods WHERE clan_id=?", (clan_id,))
                conn.execute("DELETE FROM clans WHERE clan_id=?", (clan_id,))
                conn.execute("DELETE FROM clan_bans WHERE clan_id=?", (clan_id,))
                conn.commit()
            bot.send_message(call.message.chat.id, "✅ Клан удалён.")
        else:
            bot.send_message(call.message.chat.id, "ℹ️ Отмена удаления.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.exception(f"clan_delete_callback err: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass

def clan_reset_handler(bot, message):
    # only OWNER: reset all clans (confirmation)
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("Подтвердить сброс", callback_data=f"clan_reset_confirm_{OWNER_ID}"),
               types.InlineKeyboardButton("Отмена", callback_data=f"clan_reset_cancel_{OWNER_ID}"))
    bot.send_message(message.chat.id, "⚠️ Подтвердите полную очистку системы кланов.", reply_markup=markup)

def clan_reset_callback(bot, call):
    try:
        parts = call.data.split("_")
        if parts[0] != "clan" or parts[1] != "reset":
            return
        action = parts[2]
        initiator = int(parts[3])
        if call.from_user.id != initiator:
            bot.answer_callback_query(call.id, "❌ Только владелец может подтвердить", show_alert=True)
            return
        if action == "confirm":
            with db.get_connection() as conn:
                conn.execute("DELETE FROM clan_members")
                conn.execute("DELETE FROM clans")
                conn.execute("DELETE FROM clan_goods")
                conn.execute("DELETE FROM clan_bans")
                conn.execute("DELETE FROM clan_stats")
                conn.commit()
            bot.send_message(call.message.chat.id, "✅ Система кланов полностью очищена.")
        else:
            bot.send_message(call.message.chat.id, "ℹ️ Отмена.")
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.exception(f"clan_reset_callback err: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass

def clan_help_handler(bot, message):
    text = (
        "📜 Команды кланов:\n\n"
        "/clan_create <название> — создать клан (только при состоянии 'Обычное состояние')\n"
        "/clan_join <название> — вступить в клан (только если у тебя не лучше чем 'Упадок')\n"
        "/clan_kick @user — Дон исключает участника (подтверждение)\n"
        "/clan_ban @user — Дон банит навсегда\n"
        "/clan_unban @user — Дон разбанивает\n"
        "/clan_transfer @user – Дон передаёт своё Донство какому-нибудь Капо и становится участником\n"
        "/clan_rename <название> – Дон меняет название клана\n"
        "/clans — список кланов в чате\n"
        "/clan – информация о своём клане\n"
        "/clan_grind — на вылазке добыть 2-5 запретных товаров (кулдаун 40 сек)\n"
        "/clan_up @user — Дон повышает до Капо (кулдаун 36 часов)\n"
        "/clan_war <название> — Дон объявляет войну (кулдаун 4 часа, нельзя в первые 2 часа после создания клана)\n"
        "/clan_sell — Дон/Капо продаёт товары (только при >80 товаров, кулдаун 10 часов)\n"
        "/clan_top — топ кланов по победам\n"
    )
    bot.send_message(message.chat.id, text)
# ---------------- /clan (информация о клане пользователя) ----------------
def clan_info_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    chat_id = message.chat.id
    try:
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT c.clan_id, c.name, c.don_id, c.created_at, c.wins "
                "FROM clans c JOIN clan_members m ON c.clan_id = m.clan_id "
                "WHERE m.user_id = ? AND c.chat_id = ?",
                (uid, chat_id)
            ).fetchone()
        if not row:
            bot.reply_to(message, "ℹ️ Ты не состоишь в клане в этом чате.")
            return

        clan_id, name, don_id, created_at, wins = row
        # members count
        with db.get_connection() as conn:
            members_count = conn.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id=?", (clan_id,)).fetchone()[0] or 0
        goods = _clan_goods_get(clan_id)
        role = _get_member_role(clan_id, uid) or "member"
        role_text = "Дон" if role == "don" else "Капо" if role == "capo" else "Участник"
        don_display = _display_name(don_id)

        created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at)) if created_at else "—"
        text = (
            f"🏷️ Название: {name}\n"
            f"👑 Дон: {don_display}\n"
            f"🧭 Твоя роль: {role_text}\n"
            f"👥 Участников: {members_count}\n"
            f"📦 Склад (товары): {goods}\n"
            f"🏆 Побед клана: {wins or 0}\n"
            f"🕒 Создан: {created_str}\n"
        )
        bot.send_message(message.chat.id, text)
    except Exception as e:
        log.exception(f"clan_info_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при получении информации о клане.")

# ---------------- /clan_rename <название> (только Дон, кулдаун 8 часов) ----------------
def clan_rename_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /clan_rename <новое название>")
        return
    new_name = parts[1].strip()
    if len(new_name) == 0 or len(new_name) > 30:
        bot.reply_to(message, "❗ Название должно быть от 1 до 30 символов.")
        return

    # проверка раскладки — все русские или все латинские (без смешения)
    def _is_all_ru(s):
        # допускаем пробелы/цифры, но буквы — только кириллица
        for ch in s:
            if ch.isalpha() and not ('\u0400' <= ch <= '\u04FF'):
                return False
        return True
    def _is_all_en(s):
        for ch in s:
            if ch.isalpha() and not ('a' <= ch.lower() <= 'z'):
                return False
        return True
    if not (_is_all_ru(new_name) or _is_all_en(new_name)):
        bot.reply_to(message, "❗ Название должно содержать либо только русские буквы, либо только латинские (без смешения).")
        return

    chat_id = message.chat.id
    uid = message.from_user.id
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT clan_id, don_id, created_at, last_war_ts FROM clans WHERE chat_id=? AND don_id=?", (chat_id, uid)).fetchone()
        if not row:
            bot.reply_to(message, "❌ Ты не Дон ни одного клана в этом чате.")
            return
        clan_id = row[0]

        # Убедимся, что колонка last_rename_ts есть (иначе добавим)
        cols = []
        with db.get_connection() as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(clans)").fetchall()]
        if "last_rename_ts" not in cols:
            with db.get_connection() as conn:
                conn.execute("ALTER TABLE clans ADD COLUMN last_rename_ts INTEGER DEFAULT 0")
                conn.commit()

        with db.get_connection() as conn:
            last_rename = conn.execute("SELECT last_rename_ts FROM clans WHERE clan_id=?", (clan_id,)).fetchone()
            last_rename_ts = last_rename[0] if last_rename and last_rename[0] else 0

        COOLDOWN = 8 * 3600
        now = int(time.time())
        if now - last_rename_ts < COOLDOWN:
            bot.reply_to(message, f"⏳ Название уже меняли недавно. Подожди ещё {int((COOLDOWN - (now - last_rename_ts))/60)} минут.")
            return

        # поменять имя
        with db.get_connection() as conn:
            conn.execute("UPDATE clans SET name=?, last_rename_ts=? WHERE clan_id=?", (new_name, now, clan_id))
            conn.commit()
        bot.reply_to(message, f"✅ Название клана изменено на: {new_name}")
    except Exception as e:
        log.exception(f"clan_rename_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при смене названия клана.")
        
def clan_leave_handler(bot, message):
    """
    /clan_leave  — выход из клана (role member/capo). Дон выйти не может.
    Кулдаун между выходами одного пользователя: 1 час (реализован в памяти).
    """
    try:
        register_user(message)
        uid = message.from_user.id
        chat_id = message.chat.id

        # Найдём запись о членстве в клане в текущем чате
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT m.clan_id, m.role, c.name FROM clan_members m "
                "JOIN clans c ON m.clan_id = c.clan_id "
                "WHERE m.user_id = ? AND c.chat_id = ? LIMIT 1",
                (uid, chat_id)
            ).fetchone()

        if not row:
            bot.reply_to(message, "ℹ️ Ты не состоишь в клане в этом чате.")
            return

        clan_id, role, clan_name = row

        # Дон не может просто уйти
        if role == "don":
            bot.reply_to(message, "❗ Дон не может покинуть клан. Передай донство другому или используй /clan_delete.")
            return

        # Инициализация memory cooldown
        if not hasattr(clan_leave_handler, "_last_leave"):
            clan_leave_handler._last_leave = {}

        now = time.time()
        last = clan_leave_handler._last_leave.get(uid, 0)
        COOLDOWN = 60 * 60  # 1 час

        if now - last < COOLDOWN:
            wait = int(COOLDOWN - (now - last))
            bot.reply_to(message, f"⏳ Не торопись. Подожди {wait} сек.")
            return

        # Удаляем участника из клана
        with db.get_connection() as conn:
            conn.execute("DELETE FROM clan_members WHERE clan_id=? AND user_id=?", (clan_id, uid))
            conn.commit()

        # Сохраняем таймстамп выхода в памяти
        clan_leave_handler._last_leave[uid] = now

        bot.reply_to(message, f"✅ Ты покинул клан '{clan_name}'. Теперь ты не состояшь в нём.")
    except Exception as e:
        log.exception(f"clan_leave_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при попытке покинуть клан.")
        
# ---------------- /clan_transfer (дон передаёт донство капо) ----------------
def clan_transfer_handler(bot, message):
    """
    /clan_transfer @nick
    Только Дон может начать. Цель должна быть Капо в том же клане.
    Создаёт сообщение с кнопками Подтвердить/Отмена (callback).
    """
    try:
        register_user(message)
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.reply_to(message, "❗ Формат: /clan_transfer @ник")
            return

        target_raw = parts[1]
        chat_id = message.chat.id
        initiator = message.from_user.id

        # Найти клан, где инициатор — Дон
        with db.get_connection() as conn:
            row = conn.execute("SELECT clan_id, name FROM clans WHERE chat_id=? AND don_id=?", (chat_id, initiator)).fetchone()
        if not row:
            bot.reply_to(message, "❌ Ты не Дон ни одного клана в этом чате.")
            return
        clan_id, clan_name = row

        # Найти target_id по @username или цифре
        if target_raw.isdigit():
            target_id = int(target_raw)
        else:
            with db.get_connection() as conn:
                r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
                target_id = r[0] if r else None

        if not target_id:
            bot.reply_to(message, "❌ Пользователь не найден в базе. Попроси его написать боту /start.")
            return

        # Проверить, что target — член этого клана и имеет роль capo
        role = _get_member_role(clan_id, target_id)
        if not role:
            bot.reply_to(message, "❌ Цель не состоит в твоём клане.")
            return
        if role != "capo":
            bot.reply_to(message, "❌ Донство можно передать только игроку с ролью Капо.")
            return

        # Подготовить подтверждение
        markup = types.InlineKeyboardMarkup()
        confirm_data = f"clan_transfer_confirm_{clan_id}_{target_id}_{initiator}"
        cancel_data = f"clan_transfer_cancel_{clan_id}_{target_id}_{initiator}"
        markup.row(
            types.InlineKeyboardButton("✅ Подтвердить передачу донства", callback_data=confirm_data),
            types.InlineKeyboardButton("❌ Отмена", callback_data=cancel_data)
        )

        bot.send_message(chat_id,
                         f"⚠️ Дон {_display_name(initiator)} предлагает передать донство {_display_name(target_id)} в клане '{clan_name}'.\n\n"
                         f"Подтвердите действие (подтвердить может только инициатор).",
                         reply_markup=markup)
    except Exception as e:
        log.exception(f"clan_transfer_handler error: {e}")
        bot.reply_to(message, "❌ Ошибка при попытке начать передачу донства.")
        
# ---------------- Callback для подтверждения передачи донства ----------------
def clan_transfer_callback(bot, call):
    """
    Обработчик callback'ов от кнопок передачи донства.
    callback_data формата:
      clan_transfer_confirm_{clan_id}_{target_id}_{initiator}
      clan_transfer_cancel_{clan_id}_{target_id}_{initiator}
    """
    try:
        data = (call.data or "")
        if not data.startswith("clan_transfer_"):
            return

        parts = data.split("_")
        if len(parts) < 5:
            bot.answer_callback_query(call.id, "❌ Неверные данные.", show_alert=True)
            return

        action = parts[2]  # confirm / cancel
        clan_id = int(parts[3])
        target_id = int(parts[4])
        initiator = int(parts[5]) if len(parts) > 5 else None

        # Разрешено нажимать только инициатору (дон)
        if call.from_user.id != initiator:
            bot.answer_callback_query(call.id, "❌ Только инициатор (дон) может подтвердить/отменить.", show_alert=True)
            return

        # Проверим, что инициатор всё ещё дон клана
        with db.get_connection() as conn:
            row = conn.execute("SELECT don_id, name FROM clans WHERE clan_id=?", (clan_id,)).fetchone()
        if not row:
            bot.answer_callback_query(call.id, "❌ Клан не найден.", show_alert=True)
            return
        current_don, clan_name = row
        if current_don != initiator:
            bot.answer_callback_query(call.id, "❌ Ты больше не дон этого клана.", show_alert=True)
            return

        # Проверим, что target всё ещё капо в том же клане
        target_role = _get_member_role(clan_id, target_id)
        if not target_role or target_role != "capo":
            bot.answer_callback_query(call.id, "❌ Цель больше не Капо или не в клане.", show_alert=True)
            return

        if action == "cancel":
            # Отмена
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except:
                pass
            bot.send_message(call.message.chat.id, "ℹ️ Передача донства отменена.")
            bot.answer_callback_query(call.id)
            return

        # Подтверждение: присвоить target роль don, а инициатору роль member
        with db.get_connection() as conn:
            conn.execute("UPDATE clan_members SET role = 'member' WHERE clan_id=? AND user_id=?", (clan_id, initiator))
            conn.execute("UPDATE clan_members SET role = 'don' WHERE clan_id=? AND user_id=?", (clan_id, target_id))
            conn.execute("UPDATE clans SET don_id = ? WHERE clan_id=?", (target_id, clan_id))
            conn.commit()

        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass

        bot.send_message(call.message.chat.id,
                         f"✅ Донство передано: {_display_name(initiator)} теперь обычный участник, {_display_name(target_id)} — новый Дон клана '{clan_name}'.")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.exception(f"clan_transfer_callback error: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка при обработке подтверждения.", show_alert=True)
        except: pass
        
        
        
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
    clan_lines = []
    try:
        with db.get_connection() as conn:
            row = conn.execute(
            "SELECT c.name, m.role FROM clans c JOIN clan_members m ON c.clan_id = m.clan_id "
            "WHERE m.user_id = ? AND c.chat_id = ?",
            (uid, message.chat.id)
        ).fetchone()
        if row:
            clan_name, clan_role = row
            role_text = "Дон" if clan_role == "don" else "Капо" if clan_role == "capo" else "Участник"
        # добавляем в текст osebe, например:
            clan_lines.append(f"🏛️ Клан: {clan_name} (твоя роль: {role_text})")
    except Exception as e:
            log.exception(f"osebe clan fetch error: {e}")
    # не прерываем показ остальной информации
    bot.reply_to(message,
                 f"👤 О себе:\n📝Имя: {nick}\n💰Баланс: {_get_balance(uid)} бублей\n☢️Окак-Токены: {tokens}\n🏘️Недвижимость: {', '.join(props)}\n🙋Помощники: {', '.join(helper_lines) if helper_lines else 'Нет'}\n💳В банке: {bank['bank_balance']} (инвестировано: {bank['invested']})\n{', '.join(clan_lines)}")

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
            "👮 Охранник — 4 Окак-Токена: временно бессмысленно\n"
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
        bot.send_message(call.message.chat.id, f"✅ Покупка успешна: {item}. Окак-Токенов осталось: {_get_tokens(uid)}")
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
    bot.send_message(message.chat.id, "🔮Эзотерик тебе даёт шанс испытать свою удачу!\n\n Выбери шкатулку:", reply_markup=markup)

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
            amount = random.randint(40000, 80000)
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

# --- Wipe all bubl balances (admin only) ---
def wipe_bubl_handler(bot, message):
    """
    Обнуляет все балансы в базе в таблице balances и/или в колонке users.balance.
    Доступ только для владельца (ID 5758264503).
    """
    log.warning("🚨 Wipe_bubl_handler вызван!")
    ADMIN_ID = 5758264503
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ У вас нет прав использовать эту команду.")
        return

    try:
        with db.get_connection() as conn:
            # Проверяем наличие таблицы balances
            t = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='balances'"
            ).fetchone()
            if t:
                # количество строк в balances до обновления
                count_balances = conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] or 0
                conn.execute("UPDATE balances SET balance = 0")
            else:
                count_balances = 0

            # Проверяем, есть ли в users колонка balance
            cols = conn.execute("PRAGMA table_info(users)").fetchall()
            has_users_balance = any(c[1] == "balance" for c in cols) if cols else False
            if has_users_balance:
                count_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0
                conn.execute("UPDATE users SET balance = 0")
            else:
                count_users = 0

            conn.commit()

        # Ответ пользователю
        if count_balances == 0 and count_users == 0:
            bot.reply_to(
                message,
                "ℹ️ Ничего не изменено: не найдены таблица `balances` и колонка `users.balance`."
            )
        else:
            bot.reply_to(
                message,
                f"✅ Все балансы обнулены.\n"
                f"rows affected — balances: {count_balances}, users: {count_users}"
            )
    except Exception as e:
        log.error(f"/wipe_bubl error: {e}")
        bot.reply_to(message, f"⚠️ Ошибка при очистке балансов: {e}")
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
        bet_game_handler(bot, m, 0.65, 2,
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
    
    # Регистрация хэндлера (вставь рядом с другими регистрациями)
    @bot.message_handler(commands=['wipe_bubl', 'wipebubl'])
    def _wipe_bubl(message):log.warning("🚨 /wipe_bubl вызван!");wipe_bubl_handler(bot, message)

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
    
    @bot.message_handler(commands=['add_prop'])
    def _h_add_prop(m): add_prop_handler(bot, m)

    @bot.message_handler(commands=['remove_prop'])
    def _h_remove_prop(m): remove_prop_handler(bot, m)

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

    # bank
    @bot.message_handler(commands=['bbank'])
    def _h_bbank(m): bbank_handler(bot, m)

    @bot.message_handler(commands=['invest'])
    def _h_invest(m): invest_handler(bot, m)

    @bot.message_handler(commands=['withdraw'])
    def _h_withdraw(m): withdraw_handler(bot, m)
        
                # ---- Регистрация PSYCH ----
    @bot.message_handler(commands=['psychs'])
    def _psychs(message): psychs_handler(bot, message)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("psych_"))
    def _psych_cb(call): psych_callback_handler(bot, call)

# ---- Регистрация CLANS ----
    @bot.message_handler(commands=['clan_create'])
    def _clan_create(message): clan_create_handler(bot, message)

    @bot.message_handler(commands=['clan_join'])
    def _clan_join(message): clan_join_handler(bot, message)

    @bot.message_handler(commands=['clan_kick'])
    def _clan_kick(message): clan_kick_handler(bot, message)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("clan_kick_"))
    def _clan_kick_cb(call): clan_kick_callback(bot, call)

    @bot.message_handler(commands=['clan_ban'])
    def _clan_ban(message): clan_ban_handler(bot, message)

    @bot.message_handler(commands=['clan_unban'])
    def _clan_unban(message): clan_unban_handler(bot, message)

    @bot.message_handler(commands=['clans'])
    def _clans(message): clans_handler(bot, message)

    @bot.message_handler(commands=['clan_grind'])
    def _clan_grind(message): clan_grind_handler(bot, message)

    @bot.message_handler(commands=['clan_up'])
    def _clan_up(message): clan_up_handler(bot, message)

    @bot.message_handler(commands=['clan_war'])
    def _clan_war(message): clan_war_handler(bot, message)

    @bot.message_handler(commands=['clan_sell'])
    def _clan_sell(message): clan_sell_handler(bot, message)

    @bot.message_handler(commands=['clan_top'])
    def _clan_top(message): clan_top_handler(bot, message)

    @bot.message_handler(commands=['clan_delete'])
    def _clan_delete(message): clan_delete_handler(bot, message)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("clan_delete_"))
    def _clan_delete_cb(call): clan_delete_callback(bot, call)

    @bot.message_handler(commands=['clan_reset'])
    def _clan_reset(message): clan_reset_handler(bot, message)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("clan_reset_"))
    def _clan_reset_cb(call): clan_reset_callback(bot, call)

    @bot.message_handler(commands=['clan_help'])
    def _clan_help(message): clan_help_handler(bot, message)
    
    @bot.message_handler(commands=['clan'])
    def _clan_info(message): clan_info_handler(bot, message)

    @bot.message_handler(commands=['clan_rename'])
    def _clan_rename(message): clan_rename_handler(bot, message)
    
    @bot.message_handler(commands=['clan_leave'])
    def _clan_leave(message): clan_leave_handler(bot, message)
    
    @bot.message_handler(commands=['clan_transfer'])
    def _clan_transfer(message): clan_transfer_handler(bot, message)

    @bot.callback_query_handler(func=lambda c: isinstance(c.data, str) and c.data.startswith("clan_transfer_"))
    def _clan_transfer_cb(call): clan_transfer_callback(bot, call)

    # shkatulka callback already registered above via 'shk_'
    # chests callback registered above

    # register bubl callback already added above

# === Конец файла extra_handlers.py ===