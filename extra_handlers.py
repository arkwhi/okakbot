# extra_handlers.py — полный обновлённый файл
import random, re, logging, time, threading, math, unicodedata
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
BET_COOLDOWN = 7            # кулдаун на любые ставки
STREET_COOLDOWN = 15        # кулдаун /bomj
OWNER_ID = 5758264503       # твой ID (админ)

# PROPERTIES (добавил country)
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
        "message": "🍕Ты поработал курьером пиццы и выполнил доставку, за которую тебе заплатили {money} бублей.\n\n Баланс: {balance} бублей"
    },
    "cottage": {
    "name": "Стандартный коттедж",
    "price": 950000,
    "command": "waiter",
    "cooldown": 120,
    "income": (6500, 16500),
    "message": "🧑‍💼🍽️Ты подработал, разнося блюда в ресторане. Тебе не заплатили, но чаевые оставили хорошие! В конце смены ты увидел {money} бублей в своём конверте. \n💰 Баланс: {balance} бублей."
    }, 
    "villa": {
    "name": "Вилла у моря",
    "price": 2000000,
    "command": "lawyer",
    "cooldown": 240,
    "income": (15000, 35000),
    "message": "🧑‍⚖️Ты помог тем, кем ты раньше был. Беднякам. Честный юрист, плата от государства и подполья: {money} бублей.\n 💰 Баланс: {balance} бублей."
    }
}
# === Инициализация таблиц (при первом импорте) ===
def _ensure_tables():
    with db.get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_seen_chat INTEGER
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
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_nick_unique ON nicknames (nickname COLLATE NOCASE)""")
        
        conn.commit()
# ======= Начало блока: сокровищница (DB) =======
def _ensure_treasure_table():
    """
    Создаёт таблицу treasure и инициализирует стартовый баланс (100000) если записи нет.
    Вставлять рядом с другими _ensure_* функциями, вызвать один раз при старте: _ensure_treasure_table()
    """
    try:
        with db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS treasure (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance INTEGER NOT NULL
                )
            """)
            # установить начальное значение, если нет
            row = conn.execute("SELECT balance FROM treasure WHERE id = 1").fetchone()
            if not row:
                conn.execute("INSERT INTO treasure (id, balance) VALUES (1, ?)", (100000,))
            conn.commit()
    except Exception as e:
        # log должен быть уже определён в файле
        try:
            log.error(f"_ensure_treasure_table error: {e}")
        except:
            pass

def _get_treasure_balance() -> int:
    """Возвращает целое — текущий баланс сокровищницы."""
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT balance FROM treasure WHERE id = 1").fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        try:
            log.error(f"_get_treasure_balance error: {e}")
        except:
            pass
        return 0

def _update_treasure_balance(delta: int) -> None:
    """
    Плюс/минус к балансу сокровищницы. При delta отрицательном баланс может уйти в 0 (мы не разрешаем отриц. сокровищницу).
    Если нужно разрешить отрицательный баланс — можно убрать проверку.
    """
    try:
        with db.get_connection() as conn:
            # гарантируем, что запись существует
            row = conn.execute("SELECT balance FROM treasure WHERE id = 1").fetchone()
            if not row:
                conn.execute("INSERT INTO treasure (id, balance) VALUES (1, ?)", (0,))
            # обновляем: не позволяем уйти в отрицательное значение
            conn.execute("UPDATE treasure SET balance = MAX(0, balance + ?) WHERE id = 1", (delta,))
            conn.commit()
    except Exception as e:
        try:
            log.error(f"_update_treasure_balance error: {e}")
        except:
            pass
def _treasury_add(amount: int) -> None:
    """Добавляет бубли в сокровищницу."""
    _update_treasure_balance(amount)

# ======= Конец блока: сокровищница (DB) =======
        
_ensure_tables()
_ensure_treasure_table()

# ----------------- БЛОК A: миграции -----------------
# Вставить после db = Database() и после вызова _ensure_tables()

# 1) Убедимся, что в таблице users есть колонка last_seen_chat (если БД — старая).
def _ensure_users_last_seen_column():
    try:
        with db.get_connection() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
            if 'last_seen_chat' not in cols:
                try:
                    conn.execute("ALTER TABLE users ADD COLUMN last_seen_chat INTEGER")
                    conn.commit()
                    log.info("Добавлен столбец users.last_seen_chat")
                except Exception as e:
                    # если ALTER не поддерживается или другая причина — логируем
                    log.warning(f"Не удалось добавить last_seen_chat: {e}")
    except Exception as e:
        log.error(f"_ensure_users_last_seen_column error: {e}")

# 2) Таблица рабства (slaves)
def _ensure_slaves_table():
    try:
        with db.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS slaves (
                    slave_id INTEGER PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    enslaved_at INTEGER NOT NULL,
                    last_tax_ts INTEGER NOT NULL
                )
            """)
            conn.commit()
    except Exception as e:
        log.error(f"_ensure_slaves_table error: {e}")

# Вызываем миграции/создание таблиц один раз при старте
try:
    _ensure_users_last_seen_column()
    _ensure_slaves_table()
except Exception as e:
    log.error(f"Ошибка при инициализации миграций: {e}")
# ----------------- конец блока A -----------------
# === Баланс / accounts ===
def _get_balance(user_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT balance FROM balances WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else 0

def _update_balance(user_id: int, delta: int):
    """
    Обновляет баланс. Теперь допускается уход в минус (если delta отрицательный и средств не хватает).
    """
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
# === Базовый хендлер для /balance ===
def balance_handler(bot, message):
    register_user(message)
    user_id = message.from_user.id
    balance = _get_balance(user_id)
    bot.reply_to(message, f"💰 Твой баланс: {balance} бублей")

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

# --- Compatibility wrapper: фикс для опечатки buy_property_handler vs property_buy_handler ---
# Некоторые места в коде вызывают buy_property_handler(...), а реальная функция называется property_buy_handler.
# Чтобы избежать ошибки "name 'buy_property_handler' is not defined", добавляем простой wrapper.

def buy_property_handler(bot, message):
    """
    Compatibility wrapper — вызывает property_buy_handler (реальная логика покупки).
    Оставляем, чтобы регистрация команд, которая использует buy_property_handler, работала корректно.
    """
    # Если у тебя реальная функция называется иначе, поменяй сюда имя.
    try:
        return property_buy_handler(bot, message)
    except NameError:
        # Если property_buy_handler отсутствует, пробуем альтернативы
        try:
            return buy_command_handler(bot, message)
        except NameError:
            # В крайнем случае — ответим об ошибке, но такого не должно быть
            bot.reply_to(message, "❌ Ошибка: обработчик покупки не найден (notify admin).")
            return
            

def _get_properties(user_id):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT property_key FROM properties WHERE user_id=?", (user_id,)).fetchall()
        return [r[0] for r in rows]

# ----------------- БЛОК B: утилиты для рабства -----------------
import math

def _is_slave(user_id: int):
    """Возвращает owner_id если пользователь раб, иначе None"""
    with db.get_connection() as conn:
        row = conn.execute("SELECT owner_id FROM slaves WHERE slave_id=?", (user_id,)).fetchone()
        return row[0] if row else None

def _is_owner(user_id: int) -> bool:
    with db.get_connection() as conn:
        row = conn.execute("SELECT 1 FROM slaves WHERE owner_id=? LIMIT 1", (user_id,)).fetchone()
        return bool(row)

def _enslave(owner_id: int, slave_id: int):
    now = int(time.time())
    with db.get_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO slaves (slave_id, owner_id, enslaved_at, last_tax_ts) VALUES (?,?,?,?)",
                     (slave_id, owner_id, now, now))
        conn.commit()

def _release_slave(slave_id: int):
    with db.get_connection() as conn:
        conn.execute("DELETE FROM slaves WHERE slave_id=?", (slave_id,))
        conn.commit()

def _get_slaves_of(owner_id: int):
    with db.get_connection() as conn:
        rows = conn.execute("SELECT slave_id, enslaved_at, last_tax_ts FROM slaves WHERE owner_id=?", (owner_id,)).fetchall()
        return rows

def _get_owner_slaves_count(owner_id: int) -> int:
    with db.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM slaves WHERE owner_id=?", (owner_id,)).fetchone()
        return row[0] if row else 0

def _apply_hourly_tax_for_slave(slave_id: int):
    """
    Применяет начисление налогов для одного раба.
    Вычисляет сколько целых часов прошло с last_tax_ts, и на каждый час снимает 30% от текущего баланса раба
    и переводит владельцу. Обновляет last_tax_ts.
    Возвращает total_transferred.
    """
    with db.get_connection() as conn:
        r = conn.execute("SELECT owner_id, last_tax_ts FROM slaves WHERE slave_id=?", (slave_id,)).fetchone()
        if not r:
            return 0
        owner_id, last_ts = r
    now = int(time.time())
    hours = (now - last_ts) // 3600
    if hours <= 0:
        return 0
    total_transferred = 0
    for _ in range(int(hours)):
        bal = _get_balance(slave_id)
        if bal == 0:
            break
        tax = int(math.floor(abs(bal) * 0.30))
        if tax <= 0:
            break
        _update_balance(slave_id, -tax)
        _update_balance(owner_id, tax)
        total_transferred += tax
    # обновим last_tax_ts на now
    with db.get_connection() as conn:
        conn.execute("UPDATE slaves SET last_tax_ts=? WHERE slave_id=?", (now, slave_id))
        conn.commit()
    return total_transferred

def _apply_hourly_tax_for_owner(owner_id: int):
    """Применяет налог для всех рабов владельца. Возвращает суммарную сумму."""
    total = 0
    rows = _get_slaves_of(owner_id)
    for slave_id, _, _ in rows:
        total += _apply_hourly_tax_for_slave(slave_id)
    return total
# ----------------- конец блока B -----------------
# ======= Начало блока: сокровищница (handlers) =======
# Зависимости: register_user(message), _get_balance(uid), _update_balance(uid, delta), _display_name(uid)
# Убедись, что импортирован: from telebot import types
# Кулдаун на каждую операцию:
TRE_ACTION_COOLDOWN = 30 * 60  # 30 минут

# память кулдаунов (user_id, action) -> ts
try:
    _tre_action_last
except NameError:
    _tre_action_last = {}

def tre_show_handler(bot, message):
    """
    Показывает баланс сокровищницы и кнопки:
    'Ограбить', 'Положить', 'Попросить', 'Закрыть'
    """
    try:
        register_user(message)  # сохраняет пользователя в БД (желаемо обновлять last_seen_chat)
        bal = _get_treasure_balance()
        markup = types.InlineKeyboardMarkup()
        # первая строка
        markup.row(
            types.InlineKeyboardButton("🦹 Ограбить", callback_data="tre_rob"),
            types.InlineKeyboardButton("📥 Положить", callback_data="tre_put")
        )
        # вторая строка
        markup.row(
            types.InlineKeyboardButton("🙏 Попросить", callback_data="tre_ask"),
            types.InlineKeyboardButton("❌ Закрыть", callback_data="tre_close")
        )
        bot.reply_to(message, f"💎 Баланс сокровищницы: {bal} бублей", reply_markup=markup)
    except Exception as e:
        try:
            log.error(f"tre_show_handler error: {e}")
        except:
            pass
        bot.reply_to(message, "❌ Ошибка при открытии сокровищницы")

def tre_callback_handler(bot, call):
    """
    Обработка нажатий. callback_data: tre_rob | tre_put | tre_ask | tre_close
    Правила:
      - Ограбить: шанс 20% успешно украсть 5-15% от баланса сокровищницы (если баланс > 0).
      - Положить: положить 1% от баланса игрока в сокровищницу.
      - Попросить: получить 0.1% от баланса сокровищницы (если есть).
      - Закрыть: удалить сообщение (close).
    Кулдаун на каждую операцию: TRE_ACTION_COOLDOWN (30 минут).
    """
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

        # Обновлённый баланс сокровищницы
        tre_bal = _get_treasure_balance()

        # Ограбить
        if action == "rob":
            chance = 0.20
            if tre_bal <= 0:
                bot.answer_callback_query(call.id, "❗ В сокровищнице пусто", show_alert=True)
                return
            if random.random() < chance:
                pct = random.randint(5, 15)  # проценты
                amount = max(1, int(tre_bal * pct / 100.0))
                # списываем из сокровищницы и даём игроку
                _update_treasure_balance(-amount)
                _update_balance(uid, amount)
                bot.send_message(call.message.chat.id, f"🕵️ {_display_name(uid)}, удачная кража! Ты забрал {amount} бублей из сокровищницы.\n💎 Баланс сокровищницы: {_get_treasure_balance()}\n💰 Твой баланс: {_get_balance(uid)}")
            else:
                bot.send_message(call.message.chat.id, f"🚫 {_display_name(uid)}, попытка ограбления не удалась.")
            _tre_action_last[key] = now
            bot.answer_callback_query(call.id)
            return

        # Положить 1% от баланса игрока в сокровищницу
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

        # Попросить 0.1% от сокровищницы
        if action == "ask":
            tre_bal = _get_treasure_balance()
            amount = max(1, int(tre_bal * 0.001))  # 0.1%
            if amount <= 0:
                bot.send_message(call.message.chat.id, f"❗ {_display_name(uid)}, в сокровищнице сейчас нечего попросить.")
                _tre_action_last[key] = now
                bot.answer_callback_query(call.id)
                return
            # выдаём (уменьшаем сокровищницу)
            _update_treasure_balance(-amount)
            _update_balance(uid, amount)
            bot.send_message(call.message.chat.id, f"🙏 {_display_name(uid)}, тебе выдали {amount} бублей из сокровищницы.\n💰 Твой баланс: {_get_balance(uid)}\n💎 Сокровищница: {_get_treasure_balance()}")
            _tre_action_last[key] = now
            bot.answer_callback_query(call.id)
            return

        # Закрыть
        if action == "close":
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.answer_callback_query(call.id)
            return

        # Неизвестное действие
        bot.answer_callback_query(call.id, "❗ Неизвестная команда", show_alert=True)

    except Exception as e:
        try:
            log.error(f"tre_callback_handler error: {e}")
        except:
            pass
        try:
            bot.answer_callback_query(call.id, "❌ Ошибка при обработке", show_alert=True)
        except:
            pass
# ======= Конец блока: сокровищница (handlers) =======
# === Кулдауны (в памяти) ===
_last_bet = {}     # user_id -> ts
_last_income = {}  # (user_id, property_key) -> ts
_last_street = {}  # user_id -> ts
_last_luck = {}    # user_id -> ts
_last_chests = {}  # user_id -> ts

# === Утилиты ===
def _delayed_delete_message(bot, chat_id, message_id, delay=8):
    def _del():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Timer(delay, _del).start()

# === Базовые хендлеры ===
def id_handler(bot, message):
    bot.reply_to(message, f"🆔 Твой Telegram ID: {message.from_user.id}")

def whoami_handler(bot, message):
    u = message.from_user
    bot.reply_to(message, f"👤 Инфо о тебе:\nИмя: {u.first_name or ''} {u.last_name or ''}\n"
                          f"Username: @{u.username if u.username else '—'}\nID: {u.id}")

def thanks_handler(bot, message):
    bot.reply_to(message, f"Пожалуйста, {message.from_user.first_name}! 🙌")

# === /bomj (street) ===
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

# === Игры — ядро (поддерживает send_reply=False) ===
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

    if random.random() < chance:
        win = int(round(bet * mult))
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

# Обёртка под старое имя
def _play_game(bot, message, *, chance, multiplier, win_texts, lose_texts):
    return bet_game_handler(bot, message, chance, multiplier, win_texts, lose_texts, send_reply=True)

# === /bubl (кнопки запускают игру) ===
def bubl_handler(bot, message):
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "❗ Используй так: /bubl 100")
        return

    bet = int(parts[1])
    if bet <= 0:
        bot.reply_to(message, "❗ Ставка должна быть положительной")
        return

    nick = _get_nickname(message.from_user.id)
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

        # фейковое сообщение для передачи в ядро игр
        fake = SimpleNamespace(
            text=f"/{game} {bet}",
            from_user=call.from_user,
            chat=call.message.chat,
            message_id=call.message.message_id
        )

        mapping = {
            "pocket": (0.6, 2,
                       ["😎Молодец, воришка. Ты потерял свои деньги на ходу, но получил больше - аж {win} бублей!",
                        "✨❄️Моя школа! {win} тебе начислено за твой проворот."],
                       ["🙄Ну ты и лоханулся... мало того, что ты ничего не украл, так у тебя украли {bet}!",
                        "🤵Мафия тобой разочарована. Мы оштрафовали тебя на {bet}, чтоб не втыкал."]),
            "casino": (0.35, 3.0,
                       ["🎰 Джекпот! {win} бублей за ставку {bet}.",
                        "🎲 Везёт! Забираешь {win} бублей (ставка {bet})."],
                       ["🃏 Крупье улыбается… Ставка {bet} ушла в дом.",
                        "💸 Рулетка безжалостна. Минус {bet}."]),
            "loto": (0.15, 10.0,
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
                # успешный результат — code=text, val=new_bal
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

# === Недвижимость/работы ===
_last_income = {}  # (user_id, property_key) -> ts

def property_buy_handler(bot, message):
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Используй: /buy hut | /buy communal | /buy country | /buy cottage | /buy villa")
        return
    key_raw = parts[1].lower()
    if key_raw in ("hut", "хижина", "хижина_на_отшибе"):
        key = "hut"
    elif key_raw in ("communal", "коммуналка", "коммуналка_в_гетто"):
        key = "communal"
    elif key_raw in ("country", "загородный", "загородный_дом"):
        key = "country"
    elif key_raw in ("cottage", "коттедж", "стандартный"):
        key = "cottage"
    elif key_raw in ("villa", "вилла", "моря"):
        key = "villa"
    else:
        bot.reply_to(message, "❗ Неизвестная недвижимость. Доступно: hut, communal, country")
        return
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

def property_income_handler(bot, message, key):
    register_user(message)
    uid = message.from_user.id
    p = PROPERTIES[key]
    if key not in _get_properties(uid):
        bot.reply_to(message, f"❌ У вас нет {p['name']} (стоит {p['price']} бублей)")
        return
    now = time.time()
    last = _last_income.get((uid, key), 0)
    if now - last < p["cooldown"]:
        bot.reply_to(message, f"⏳ Подожди {int(p['cooldown'] - (now - last))} сек")
        return
    _last_income[(uid, key)] = now
    money = random.randint(*p["income"])
    _update_balance(uid, money)
    # вставляем баланс в сообщение, если требуется
    try:
        msg = p["message"].format(money=money, balance=_get_balance(uid))
    except KeyError:
        msg = p["message"].format(money=money) + f"\n💰 Баланс: {_get_balance(uid)}"
    bot.reply_to(message, msg)

# Обёртки под команды
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

# === Ник/о себе ===

NICK_RE = re.compile(r'(?i)^окак\s+ник\s+(.+)$')

def nickname_handler(bot, message):
    register_user(message)
    text = (message.text or '').strip()
    m = NICK_RE.match(text)
    if not m:
        bot.reply_to(message, "❗ Используй: Окак ник <твой ник>")
        return

    raw_nick = m.group(1).strip()

    # Нормализация и сжатие пробелов
    nick = unicodedata.normalize('NFKC', raw_nick)
    nick = ' '.join(nick.split())  # удаляем лишние пробелы

    # Базовые проверки
    if not nick:
        bot.reply_to(message, "❗ Ник не может быть пустым.")
        return

    MAX_NICK_LEN = 25
    if len(nick) > MAX_NICK_LEN:
        bot.reply_to(message, f"❗ Ник слишком длинный ({len(nick)}/{MAX_NICK_LEN}). Максимум {MAX_NICK_LEN} символов.")
        return

    # Запрет переносов строк
    if '\n' in nick or '\r' in nick:
        bot.reply_to(message, "❗ Ник не должен содержать переносы строк.")
        return

    # Запрет "глитч"-символов: управляющие символы, combining marks, zero-width, variation selectors, приватные области
    for ch in nick:
        cat = unicodedata.category(ch)  # 'Ll','Mn','Cc' и т.д.
        code = ord(ch)

        # запрещаем управляющие символы и combining marks
        if cat.startswith('C') or cat.startswith('M'):
            bot.reply_to(message, "❗ Ник содержит недопустимые символы (управляющие / комбинирующие). Убери необычные символы и попробуй снова.")
            return

        # zero-width / invisible / directionals / BOM
        if (0x200B <= code <= 0x200F) or (0x202A <= code <= 0x202E) or code == 0xFEFF:
            bot.reply_to(message, "❗ Ник содержит невидимые символы (zero-width). Убери их и попробуй снова.")
            return

        # variation selectors (модификаторы эмодзи)
        if 0xFE00 <= code <= 0xFE0F:
            bot.reply_to(message, "❗ Ник содержит недопустимые модификаторы символов. Убери их и попробуй снова.")
            return

        # приватная область
        if (0xE000 <= code <= 0xF8FF) or (0xF0000 <= code <= 0xFFFFD) or (0x100000 <= code <= 0x10FFFD):
            bot.reply_to(message, "❗ Ник содержит запрещённые символы. Выбери другой ник.")
            return

    # Проверка уникальности (case-insensitive)
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

    # Всё ок — сохраняем
    try:
        _set_nickname(message.from_user.id, nick)
        bot.reply_to(message, f"✅ Теперь твой ник: {nick}")
    except Exception as e:
        log.exception(f"nickname save error: {e}")
        bot.reply_to(message, "❌ Не удалось сохранить ник — попробуй позже.")

def osebe_handler(bot, message):
    register_user(message)
    uid = message.from_user.id
    nick = _get_nickname(uid)
    props = [PROPERTIES[k]["name"] for k in _get_properties(uid)] or ["Нет"]
    bot.reply_to(message, f"👤 О себе:\nИмя: {nick or message.from_user.first_name}\n"
                          f"Баланс: {_get_balance(uid)} бублей\nНедвижимость: {', '.join(props)}")

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
    """
    /soo <текст>  -- только OWNER_ID
    Отправляет <текст> в личные сообщения всем пользователям из таблицы users
    и пытается отправить в каждый chat_id, сохранённый в users.last_seen_chat.
    Спит между отправками, чтобы минимизировать риск rate-limit.
    """
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
        # Отправляем в ЛС
        try:
            bot.send_message(user_id, text)
            sent_users += 1
        except Exception:
            failed_users += 1
        # Небольшая пауза, чтобы снизить риск временных лимитов
        time.sleep(0.05)

    # Попробуем отправить в чаты (last_seen_chat может быть NULL)
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

# === Luck (кнопки) ===
EMOJIS = [
    "😀","😎","🤡","👻","💀","🐵","🐸","🐱","🦊","🐼",
    "🐨","🐯","🦁","🐮","🐷","🐔","🐧","🐦","🐤","🐣",
    "🐥","🦆","🦅","🦉","🐺","🥰","🍎","😃","🙄","🎃","🤓","🤔"
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
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass

# === /chests ===
CHEST_COOLDOWN = 30
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
    bot.send_message(message.chat.id, "🗝️ По радио ты услышал легенду о счастливых сундуках. От отчаяния, ты пошёл в пещеру их искать. Легенда была права, хоть ей никто и не верил... \n\n Выбирай сундук:", reply_markup=markup)

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
            bot.send_message(call.message.chat.id, f"🎉 {name}, сундук, который ты открыл, оказался щедрым! Он тебя лично поблагодарил за приход и подарил +{amount} бублей.\n💰 Баланс: {_get_balance(uid)}")
        elif roll < 0.7:
            amount = random.randint(1000, 4000)
            _update_balance(uid, -amount)
            _treasury_add(amount)   # 100% в сокровищницу
            bot.send_message(call.message.chat.id, f"💀 {name}, сундук владеет чёрной магией. Вдруг, он уничтожил несколько купюр в твоём кошельке. Минус {amount} бублей.\n💰 Баланс: {_get_balance(uid)}")
        else:
            bot.send_message(call.message.chat.id, f"📦 {name}, сундук тебе ничего не дал... Может, он просто спит.")
        bot.answer_callback_query(call.id)
    except Exception as e:
        log.error(f"chests_callback_handler: {e}")
        try: bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        except: pass

# === Дуэли /sf, ставки /bet, топы ===
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
            if 'hut' in props:
                base += 15
            if 'communal' in props:
                base += 25
            if 'country' in props:
                base += 35   # <-- добавил +35 HP для country
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
            _delayed_delete_message(bot, sent.chat.id, sent.message_id, delay=8)

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

        # ==== распределение ставок: платим ВСЕМ, кто ставил на победителя (игроки и зрители) ====
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

        # Победитель получает бонус от выплат (твоя прежняя логика — оставить)
        winner_reward = int(total_bettors_payout * 2)
        if winner_reward > 0:
            _update_balance(winner, winner_reward)
            bot.send_message(chat_id, f"🏆 Победитель {_display_name(winner)} получает бонус от банка: {winner_reward} бублей!")

        # Проигравший теряет 32% своего баланса
        loser_balance_before = _get_balance(loser)
        penalty = int(math.floor(abs(loser_balance_before) * 0.32)) if loser_balance_before != 0 else 0
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

# === /wipebubl (обнулить балансы), /wipe_prop уже выше ===
def wipebubl_handler(bot, message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "❌ Нет доступа")
        return
    with db.get_connection() as conn:
        conn.execute("UPDATE balances SET balance=0")
        conn.commit()
    bot.send_message(message.chat.id, "⚠️ Все балансы обнулены.")

# ----------------- БЛОК C: хендлеры рабства -----------------
# Кулдауны (в памяти)
_last_ensl = {}    # user_id -> ts (когда пользователь последний раз пытался поработить)
_last_escape = {}  # slave_id -> ts (последняя попытка побега)

ENSL_COOLDOWN = 3 * 3600  # 3 часа
ESCAPE_COOLDOWN = 3600    # 1 час
ENS_SUCCESS_BASE = 0.5    # базовый шанс 50%
ESCAPE_SUCCESS = 0.35     # шанс удачи при побеге

def ensl_handler(bot, message):
    """
    /ensl @user  — попытка поработить другого игрока (развлекательная).
    Кулдаун — 3 часа у того, кто вызывает.
    Нельзя поработить того, кто уже раб; нельзя поработить человека, который уже является рабовладельцем (имеет собственных рабов).
    Шанс = 50% - 10% * количество собственности цели (hut/communal/country).
    """
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
            r = conn.execute("SELECT user_id FROM users WHERE username=?", (target_raw.lstrip("@"),)).fetchone()
            target_id = r[0] if r else None
    if not target_id:
        bot.reply_to(message, "❌ Пользователь не найден. Попроси его написать боту /start")
        return
    owner = message.from_user.id
    if owner == target_id:
        bot.reply_to(message, "❌ Дитя, себя в рабах держать нельзя")
        return
    # кулдаун
    now = time.time()
    last = _last_ensl.get(owner, 0)
    if now - last < ENSL_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int((ENSL_COOLDOWN - (now-last))/60)} минут перед новой попыткой.")
        return
    # цель — не уже раб
    if _is_slave(target_id):
        bot.reply_to(message, "❌ Берега попутал, дитя. Раба чужого воровать скверное дело.")
        _last_ensl[owner] = now
        return
    # цель — не рабовладелец
    if _is_owner(target_id):
        bot.reply_to(message, "❌ Нельзя поработить другого рабовладельца.")
        _last_ensl[owner] = now
        return

    # вычисляем шанс: 50% - 10% за каждую недвижимость цели
    props = _get_properties(target_id)
    chance = ENS_SUCCESS_BASE - 0.10 * len(props)
    if chance < 0.05:
        chance = 0.05  # нижний предел 5%
    roll = random.random()
    if roll < chance:
        _enslave(owner, target_id)
        bot.reply_to(message, f"✅ {_display_name(owner)} успешно поработил {_display_name(target_id)}! Теперь {_display_name(target_id)} — твой раб.")
    else:
        bot.reply_to(message, f"❌ Попытка поработить {_display_name(target_id)} не удалась.")
    _last_ensl[owner] = now

def sl_handler(bot, message):
    """/sl — показать своих рабов. Также при запросе — собираем налоги с рабов (если они накопились)."""
    register_user(message)
    owner = message.from_user.id
    if not _is_owner(owner):
        bot.reply_to(message, "❗ У тебя нет рабов.")
        return
    # сначала применим налоги, если есть (по требованию)
    total = _apply_hourly_tax_for_owner(owner)
    rows = _get_slaves_of(owner)
    lines = []
    for slave_id, enslaved_at, last_tax_ts in rows:
        lines.append(f"- {_display_name(slave_id)} (с {time.strftime('%Y-%m-%d %H:%M', time.localtime(enslaved_at))})")
    txt = f"👑 Твои рабы:\n" + "\n".join(lines)
    if total > 0:
        txt = f"💰 Собрано с рабов за время: {total} бублей\n\n" + txt
    bot.reply_to(message, txt)

def desl_handler(bot, message):
    """/desl @user — освободить своего раба (только владелец)."""
    register_user(message)
    parts = (message.text or "").split()
    if len(parts) < 2:
        bot.reply_to(message, "❗ Формат: /desl @user")
        return
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
    cur_owner = _is_slave(target_id)
    if cur_owner != owner:
        bot.reply_to(message, "❌ Этот пользователь не является твоим рабом.")
        return
    _release_slave(target_id)
    bot.reply_to(message, f"✅ {_display_name(target_id)} освобождён(а).")

def escape_handler(bot, message):
    """/escape — раб пытается сбежать (кулдаун 1 час)."""
    register_user(message)
    user = message.from_user.id
    owner = _is_slave(user)
    if not owner:
        bot.reply_to(message, "❗ Ты не раб.")
        return
    now = time.time()
    last = _last_escape.get(user, 0)
    if now - last < ESCAPE_COOLDOWN:
        bot.reply_to(message, f"⏳ Подожди {int((ESCAPE_COOLDOWN - (now-last))/60)} минут перед новой попыткой.")
        return
    if random.random() < ESCAPE_SUCCESS:
        _release_slave(user)
        bot.reply_to(message, f"🏃‍♂️ Ура! {_display_name(user)} сумел(а) сбежать и стал(а) свободен(на).")
    else:
        bot.reply_to(message, f"🚫 Попытка побега не удалась. Остаёшься рабом.")
    _last_escape[user] = now

def topsl_handler(bot, message):
    """/topsl — топ рабовладельцев по количеству рабов."""
    with db.get_connection() as conn:
        rows = conn.execute("SELECT owner_id, COUNT(*) as cnt FROM slaves GROUP BY owner_id ORDER BY cnt DESC LIMIT 10").fetchall()
    if not rows:
        bot.reply_to(message, "❗ Пока нет рабовладельцев.")
        return
    lines = []
    for i, (owner_id, cnt) in enumerate(rows, 1):
        lines.append(f"{i}. {_display_name(owner_id)} — {cnt} раб(ов)")
    bot.send_message(message.chat.id, "🏆 Топ рабовладельцев:\n" + "\n".join(lines))

def collect_handler(bot, message):
    """
    /collect — владелец собирает налоги со своих рабов (переносит все накопленные за прошедшие часы).
    """
    register_user(message)
    owner = message.from_user.id
    if not _is_owner(owner):
        bot.reply_to(message, "❗ У тебя нет рабов.")
        return
    total = _apply_hourly_tax_for_owner(owner)
    if total > 0:
        bot.reply_to(message, f"💰 Собрано {total} бублей с твоих рабов. Баланс: {_get_balance(owner)}")
    else:
        bot.reply_to(message, "ℹ️ Ничего нового для сбора (пока не прошёл полный час).")
# ----------------- конец блока C -----------------
# === Регистрация хэндлеров ===
def register_extra_handlers(bot):

    # ID / whoami
    @bot.message_handler(commands=['id'])
    def _h_id(m): id_handler(bot, m)

    @bot.message_handler(commands=['whoami'])
    def _h_whoami(m): whoami_handler(bot, m)

    # спасибо auto-reply
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower() == "спасибо")
    def _h_thanks(m): thanks_handler(bot, m)

    # баланс
    @bot.message_handler(commands=['balance'])
    def _h_balance(m): balance_handler(bot, m)

    # bomj
    @bot.message_handler(commands=['bomj'])
    def _h_bomj(m): street_handler(bot, m)

    # /bubl
    @bot.message_handler(commands=['bubl'])
    def _h_bubl(m): bubl_handler(bot, m)

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("bubl_"))
    def _h_bubl_cb(call): bubl_callback_handler(bot, call)

    # игры
    @bot.message_handler(commands=['pocket'])
    def _h_pocket(m): _play_game(
        bot, m,
        chance=0.6, multiplier=2,
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
        chance=0.4, multiplier=3.0,
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
        chance=0.2, multiplier=6.0,
        win_texts=[
            "🎟 Счастливый билет! +{win} бублей (ставка {bet}).",
            "🌟 Умный человек в очках выиграл {win} бублей скачать обои"
        ],
        lose_texts=[
            "🪙 Ой-ой-ой, не повезло. Ставка в аж {bet} бублей ушла в воздух.",
            "🙃 Сегодня не твой день. Минус {bet}."
        ]
    )

    # перевод
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("дать "))
    def _h_transfer(m): transfer_handler(bot, m)
    
    # cottage
    @bot.message_handler(commands=['buy_cottage'])
    def _h_buy_cottage(m): buy_cottage_handler(bot, m)

    @bot.message_handler(commands=['cottage'])
    def _h_cottage(m): cottage_handler(bot, m)

    # покупки / работы
    @bot.message_handler(commands=['buy'])
    def _h_buy(m): buy_property_handler(bot, m)

    @bot.message_handler(commands=['buy_hut'])
    def _h_buy_hut(m): buy_hut_handler(bot, m)

    @bot.message_handler(commands=['buy_communal'])
    def _h_buy_comm(m): buy_communal_handler(bot, m)

    @bot.message_handler(commands=['buy_country'])
    def _h_buy_country(m): buy_country_handler(bot, m)

    @bot.message_handler(commands=['mafia'])
    def _h_mafia(m): mafia_handler(bot, m)

    @bot.message_handler(commands=['clean'])
    def _h_clean(m): clean_handler(bot, m)

    @bot.message_handler(commands=['pizza'])
    def _h_pizza(m): pizza_handler(bot, m)
    
    # в register_extra_handlers должно быть нечто вроде
    @bot.message_handler(commands=['waiter'])
    def _h_waiter(m): waiter_handler(bot, m)

    @bot.message_handler(commands=['lawyer'])
    def _h_lawyer(m): lawyer_handler(bot, m)

    # ник
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and re.match(r"(?i)^окак\s+ник\s+(.+)$", (m.text or "").strip()))
    def _h_setnick(m): nickname_handler(bot, m)

    @bot.message_handler(commands=['osebe'])
    def _h_osebe(m): osebe_handler(bot, m)

    # топы
    @bot.message_handler(commands=['topbubl'])
    def _h_topbubl(m): topbubl_handler(bot, m)

    @bot.message_handler(commands=['topsf'])
    def _h_topsf(m): topsf_handler(bot, m)

    @bot.message_handler(commands=['topst'])
    def _h_topst(m): topst_handler(bot, m)

    # админ
    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("/add_bubl"))
    def _h_add(m): add_bubl_handler(bot, m)

    @bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.lower().startswith("/remove_bubl"))
    def _h_remove(m): remove_bubl_handler(bot, m)

    @bot.message_handler(commands=['xhp'])
    def _h_xhp(m): xhp_handler(bot, m)

    @bot.message_handler(commands=['wipebubl'])
    def _h_wipebubl(m): wipebubl_handler(bot, m)

    @bot.message_handler(commands=['wipe_prop'])
    def _h_wipeprop(m): wipe_prop_handler(bot, m)
    
    @bot.message_handler(commands=['soo'])
    def _h_soo(m): soo_handler(bot, m)

    # дуэли
    @bot.message_handler(commands=['sf'])
    def _h_sf(m): sf_command_handler(bot, m)

    @bot.message_handler(commands=['sf_accept'])
    def _h_sf_accept(m): sf_accept_handler(bot, m)

    @bot.message_handler(commands=['sf_decline'])
    def _h_sf_decline(m): sf_decline_handler(bot, m)

    @bot.message_handler(commands=['bet'])
    def _h_bet(m): bet_handler(bot, m)

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

# рабство
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
# === Конец файла ===