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
                CREATE TABLE IF NOT EXISTS balances (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0
                )
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
                INSERT INTO balances (user_id, balance)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance
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
                "😎 Молодец, воришка. Забрал аж {win} бублей!",
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
    def _h_top(message): topbubl_handler(bot, message)
    
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