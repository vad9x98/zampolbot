import asyncio
import json
import logging
import re
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile

# === НАСТРОЙКИ ===
API_TOKEN = "8359372242:AAE1o4pHjFEHnnMsplqbSHAmOVbQQi-ub2A"
ADMINS = [7753983073, 1414261920]
GROUP_CHAT_ID = -1003728047688
DATA_FILE = Path("data.json")
BLOCKED_FILE = Path("blocked.json")
LOG_FILE = Path("bot.log")
EXCEL_EXPORT_DIR = Path("exports")

bot: Optional[Bot] = None
file_lock = asyncio.Lock()
spam_protection = {}
blocked_users: Dict[int, Any] = {}

COOLDOWN_TIME = 3600  # 1 час = 60 минут

# Создаем папку для экспорта
EXCEL_EXPORT_DIR.mkdir(exist_ok=True)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class Survey(StatesGroup):
    full_name = State()
    military_unit = State()
    personal_number = State()
    room = State()
    military_id = State()
    lost_military_id_reason = State()
    veteran_certificate = State()  # ✅ ИЗМЕНЕНО: было uvbd
    salary = State()
    salary_problems = State()
    contract_payments = State()
    contract_problems = State()
    more_questions = State()
    more_questions_details = State()


class AdminStates(StatesGroup):
    block_user = State()
    unblock_user = State()


def load_blocked_users():
    """Загрузка списка заблокированных пользователей"""
    global blocked_users
    if BLOCKED_FILE.exists():
        try:
            with BLOCKED_FILE.open("r", encoding="utf-8") as f:
                blocked_users = json.load(f)
        except:
            blocked_users = {}
    else:
        blocked_users = {}


def save_blocked_users():
    """Сохранение списка заблокированных пользователей"""
    with BLOCKED_FILE.open("w", encoding="utf-8") as f:
        json.dump(blocked_users, f, ensure_ascii=False, indent=2)


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def is_blocked(user_id: int) -> bool:
    return user_id in blocked_users


def validate_fio(fio: str) -> tuple[bool, str]:
    parts = [p.strip() for p in fio.split()]
    if len(parts) != 3:
        return False, "Нужно Фамилия Имя Отчество, через пробел"
    if any(len(part) < 3 or not part.replace(' ', '').isalpha() for part in parts):
        return False, "Каждая часть минимум 3 буквы, только буквы"
    return True, ""


def validate_personal_number(personal: str) -> tuple[bool, str]:
    pattern = r'^[А-Я]{1,2}-[0-9]{6}$'
    if re.match(pattern, personal.upper()):
        return True, ""
    return False, "Неверный формат! Должно быть: А-123456 или АБ-123456"


def validate_military_unit(unit: str) -> tuple[bool, str]:
    if re.match(r'^\d{5}$', unit):  # ИСПРАВЛЕНО: убрал лишний \\
        return True, ""
    return False, "В/ч должна содержать ровно 5 цифр! Пример: 12345"


def validate_text_length(text: str, min_length: int = 30) -> tuple[bool, str]:
    if len(text.strip()) >= min_length:
        return True, ""
    return False, "Опишите подробнее ситуацию"


def norm_yes_no(text: str) -> Optional[bool]:
    t = (text or "").strip().lower()
    if t in ("✅ да", "да", "yes", "y", "1", "+"):
        return True
    if t in ("❌ нет", "нет", "no", "n", "0", "-"):
        return False
    return None


def is_spam(user_id: int) -> tuple[bool, str]:
    if is_blocked(user_id):
        return True, "🚫 Вы заблокированы в боте"
    
    loop = asyncio.get_event_loop()
    now = loop.time()
    if user_id in spam_protection:
        if now - spam_protection[user_id] < COOLDOWN_TIME:
            remaining = COOLDOWN_TIME - (now - spam_protection[user_id])
            minutes = int(remaining / 60)
            return True, f"⏳ Подождите {minutes} мин, прежде чем оставить новую заявку"
    spam_protection[user_id] = now
    return False, ""


def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Начать заявку")]],
        resize_keyboard=True
    )


def restart_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📤 Отправить заявку заново")]],
        resize_keyboard=True
    )


def admin_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📈 Экспорт Excel")],
            [KeyboardButton(text="🚫 Блокировать"), KeyboardButton(text="✅ Разблокировать")],
            [KeyboardButton(text="🚀 Начать заявку")]
        ],
        resize_keyboard=True
    )


def yes_no_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")]],
        resize_keyboard=True, one_time_keyboard=True
    )


# ✅ ВСЕ НЕДОСТАЮЩИЕ ОБРАБОТЧИКИ СОСТОЯНИЙ
async def process_full_name(message: Message, state: FSMContext):
    fio = message.text.strip()
    valid, error = validate_fio(fio)
    
    if not valid:
        kb = admin_kb() if is_admin(message.from_user.id) else main_kb()
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:", reply_markup=kb)
        return
    
    await state.update_data(full_name=fio)
    await message.answer("🏛️ <b>Укажите воинскую часть (в/ч)</b>\n<i>Только 5 цифр! Пример: 12345</i>", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Survey.military_unit)


async def process_military_unit(message: Message, state: FSMContext):
    unit = message.text.strip()
    valid, error = validate_military_unit(unit)
    
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return
    
    await state.update_data(military_unit=unit)
    await message.answer("🆔 <b>Укажите личный номер</b>\n<i>Формат: А-123456 или АБ-123456</i>", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Survey.personal_number)


async def process_personal_number(message: Message, state: FSMContext):
    personal = message.text.strip()
    valid, error = validate_personal_number(personal)
    
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return
    
    await state.update_data(personal_number=personal)
    await message.answer("🏠 <b>Укажите комнату (этаж/палата)</b>\n<i>Пример: 3/15</i>", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Survey.room)


async def process_room(message: Message, state: FSMContext):
    await state.update_data(room=message.text.strip())
    await message.answer("📄 <b>Есть ли у вас военный билет?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.military_id)


async def process_military_id(message: Message, state: FSMContext):
    yes_no = norm_yes_no(message.text)
    if yes_no is None:
        await message.answer("❌ Выберите <b>✅ Да</b> или <b>❌ Нет</b>", reply_markup=yes_no_kb())
        return
    
    military_id_text = "✅ Да" if yes_no else "❌ Нет"
    await state.update_data(military_id=military_id_text)
    
    if not yes_no:
        await message.answer("📝 <b>Укажите причину утраты военного билета</b>", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.lost_military_id_reason)
    else:
        # ✅ ИЗМЕНЕНО: новый вопрос про удостоверение ветерана
        await message.answer("🎖️ <b>Имеете ли вы удостоверение ветерана боевых действий?</b>", reply_markup=yes_no_kb())
        await state.set_state(Survey.veteran_certificate)


async def process_lost_military_id_reason(message: Message, state: FSMContext):
    if not validate_text_length(message.text)[0]:
        await message.answer("❌ Опишите подробнее причину утраты:")
        return
    
    await state.update_data(lost_military_id_reason=message.text.strip())
    # ✅ ИЗМЕНЕНО: новый вопрос про удостоверение ветерана
    await message.answer("🎖️ <b>Имеете ли вы удостоверение ветерана боевых действий?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.veteran_certificate)


# ✅ ИЗМЕНЕНО: новый обработчик для удостоверения ветерана (было process_uvbd)
async def process_veteran_certificate(message: Message, state: FSMContext):
    yes_no = norm_yes_no(message.text)
    if yes_no is None:
        await message.answer("❌ Выберите <b>✅ Да</b> или <b>❌ Нет</b>", reply_markup=yes_no_kb())
        return
    
    await state.update_data(veteran_certificate="✅ Да" if yes_no else "❌ Нет")
    await message.answer("💰 <b>Получаете ли денежное довольствие вовремя?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.salary)


async def process_salary(message: Message, state: FSMContext):
    yes_no = norm_yes_no(message.text)
    if yes_no is None:
        await message.answer("❌ Выберите <b>✅ Да</b> или <b>❌ Нет</b>", reply_markup=yes_no_kb())
        return
    
    salary_text = "✅ Да" if yes_no else "❌ Нет"
    await state.update_data(salary=salary_text)
    
    if not yes_no:
        await message.answer("⚠️ <b>Опишите проблемы с зарплатой</b>", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.salary_problems)
    else:
        await message.answer("💸 <b>Получаете ли выплаты после подписания контракта?</b>", reply_markup=yes_no_kb())
        await state.set_state(Survey.contract_payments)


async def process_salary_problems(message: Message, state: FSMContext):
    if not validate_text_length(message.text)[0]:
        await message.answer("❌ Опишите подробнее проблемы с зарплатой:")
        return
    
    await state.update_data(salary_problems=message.text.strip())
    await message.answer("💸 <b>Получаете ли выплаты после подписания контракта?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.contract_payments)


async def process_contract_payments(message: Message, state: FSMContext):
    yes_no = norm_yes_no(message.text)
    if yes_no is None:
        await message.answer("❌ Выберите <b>✅ Да</b> или <b>❌ Нет</b>", reply_markup=yes_no_kb())
        return
    
    contract_text = "✅ Да" if yes_no else "❌ Нет"
    await state.update_data(contract_payments=contract_text)
    
    if not yes_no:
        await message.answer("🔧 <b>Опишите проблемы с выплатами по контракту</b>", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.contract_problems)
    else:
        await message.answer("❓ <b>Имеются ли еще проблемные вопросы?</b>", reply_markup=yes_no_kb())
        await state.set_state(Survey.more_questions)


async def process_contract_problems(message: Message, state: FSMContext):
    if not validate_text_length(message.text)[0]:
        await message.answer("❌ Опишите подробнее проблемы с выплатами:")
        return
    
    await state.update_data(contract_problems=message.text.strip())
    await message.answer("❓ <b>Имеются ли еще проблемные вопросы?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.more_questions)


async def process_more_questions(message: Message, state: FSMContext):
    yes_no = norm_yes_no(message.text)
    if yes_no is None:
        await message.answer("❌ Выберите <b>✅ Да</b> или <b>❌ Нет</b>", reply_markup=yes_no_kb())
        return
    
    more_text = "✅ Да" if yes_no else "❌ Нет"
    await state.update_data(more_questions=more_text)
    
    if yes_no:
        await message.answer("📝 <b>Опишите другие проблемные вопросы</b>", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.more_questions_details)
    else:
        await finish_and_send(message, state)


async def process_more_questions_details(message: Message, state: FSMContext):
    await state.update_data(more_questions_details=message.text.strip())
    await finish_and_send(message, state)


async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if await state.get_state() is not None:
        await state.clear()
    
    is_spam_flag, spam_msg = is_spam(user_id)
    if is_spam_flag:
        await message.answer(spam_msg, reply_markup=main_kb())
        return
    
    await state.clear()
    kb = admin_kb() if is_admin(user_id) else main_kb()
    await message.answer(
        "🆘 <b>ПОМОЩЬ В ПРОБЛЕМНЫХ ВОПРОСАХ ВОЕННОСЛУЖАЩИХ</b>\n\n"
        "Напишите ФИО в формате:\n"
        "<i>Фамилия Имя Отчество</i>\n\n"
        "Пример: Иванов Иван Иванович\n\n"
        "<i>/cancel — отменить</i>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(Survey.full_name)


async def handle_restart_button(message: Message, state: FSMContext):
    if message.text == "📤 Отправить заявку заново":
        await cmd_start(message, state)
        return
    if message.text == "🚀 Начать заявку":
        await cmd_start(message, state)
        return


async def handle_admin_buttons(message: Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    
    if message.text == "📊 Статистика":
        await cmd_stats(message)
    elif message.text == "📈 Экспорт Excel":
        await cmd_export_excel(message)
    elif message.text == "🚫 Блокировать":
        await message.answer("👤 Введите ID пользователя для блокировки:\n<code>/block 123456789</code>", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
    elif message.text == "✅ Разблокировать":
        await message.answer("👤 Введите ID пользователя для разблокировки:\n<code>/unblock 123456789</code>", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)


async def cmd_cancel(message: Message, state: FSMContext):
    cur_state = await state.get_state()
    if cur_state is None:
        kb = admin_kb() if is_admin(message.from_user.id) else main_kb()
        await message.answer("Нечего отменять. Нажмите кнопку ниже:", reply_markup=kb)
        return
    await state.clear()
    kb = admin_kb() if is_admin(message.from_user.id) else main_kb()
    await message.answer("✅ Отменено. Нажмите кнопку ниже:", reply_markup=kb)


async def cmd_help(message: Message):
    user_id = message.from_user.id
    kb = admin_kb() if is_admin(user_id) else main_kb()
    
    if is_admin(user_id):
        help_text = """📋 <b>Команды:</b>
/start — начать заявку
/cancel — отменить
/help — это меню
/stats — статистика
/export — экспорт в Excel
/block ID — заблокировать
/unblock ID — разблокировать
/clear — очистить базу
/broadcast — рассылка админам"""
    else:
        help_text = """📋 <b>Команды:</b>
/start — начать заявку
/cancel — отменить
/help — помощь"""
    
    await message.answer(help_text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ только админам", reply_markup=main_kb())
        return
    
    async with file_lock:
        try:
            blocked_count = len(blocked_users)
            if DATA_FILE.exists():
                with DATA_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                count = len(data)
                latest = data[-1]["timestamp"] if data else "нет"
                await message.answer(
                    f"📊 <b>Статистика:</b>\n"
                    f"Всего заявок: {count}\n"
                    f"Заблокировано: {blocked_count}\n"
                    f"Последняя: {latest}", 
                    reply_markup=admin_kb(), parse_mode=ParseMode.HTML
                )
            else:
                await message.answer(f"📊 Заявок: 0\n🚫 Заблокировано: {blocked_count}", reply_markup=admin_kb())
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}", reply_markup=admin_kb())


async def cmd_export_excel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ только админам", reply_markup=main_kb())
        return
    
    await message.answer("📈 Формирую Excel файл...", reply_markup=admin_kb())
    
    async with file_lock:
        try:
            if not DATA_FILE.exists():
                await message.answer("📊 Нет данных для экспорта", reply_markup=admin_kb())
                return
            
            with DATA_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not data:
                await message.answer("📊 Нет данных для экспорта", reply_markup=admin_kb())
                return
            
            # Создаем CSV файл (Excel читает CSV)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_file = EXCEL_EXPORT_DIR / f"заявки_{timestamp}.csv"
            
            fieldnames = [
                "Номер", "Дата", "ФИО", "В/Ч", "Личный номер", "Комната",
                "Военный билет", "Причина утраты", "Удостоверение ВБД", "Зарплата", "Проблемы зарплаты",  # ✅ ИЗМЕНЕНО
                "Выплаты контракт", "Проблемы выплат", "Другие вопросы", "Детали вопросов",
                "User ID", "Username"
            ]
            
            with csv_file.open("w", newline='', encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for i, record in enumerate(data, 1):
                    row = {
                        "Номер": i,
                        "Дата": record.get("timestamp", ""),
                        "ФИО": record.get("full_name", ""),
                        "В/Ч": record.get("military_unit", ""),
                        "Личный номер": record.get("personal_number", ""),
                        "Комната": record.get("room", ""),
                        "Военный билет": record.get("military_id", ""),
                        "Причина утраты": record.get("lost_military_id_reason", ""),
                        "Удостоверение ВБД": record.get("veteran_certificate", ""),  # ✅ ИЗМЕНЕНО
                        "Зарплата": record.get("salary", ""),
                        "Проблемы зарплаты": record.get("salary_problems", ""),
                        "Выплаты контракт": record.get("contract_payments", ""),
                        "Проблемы выплат": record.get("contract_problems", ""),
                        "Другие вопросы": record.get("more_questions", ""),
                        "Детали вопросов": record.get("more_questions_details", ""),
                        "User ID": record.get("user_id", ""),
                        "Username": f"@{record.get('username', 'нет')}"
                    }
                    writer.writerow(row)
            
            # Отправляем файл
            await message.answer_document(
                document=FSInputFile(csv_file),
                caption=f"📈 Экспорт заявок ({len(data)} записей)\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                reply_markup=admin_kb()
            )
            
            logger.info(f"Экспорт создан: {csv_file}")
            
        except Exception as e:
            logger.error(f"Ошибка экспорта: {e}")
            await message.answer(f"❌ Ошибка создания файла: {e}", reply_markup=admin_kb())


async def cmd_block(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.text.split()[1])
        blocked_users[user_id] = {"blocked_at": datetime.now().isoformat()}
        save_blocked_users()
        await message.answer(f"🚫 Пользователь <code>{user_id}</code> заблокирован", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
        logger.info(f"Заблокирован пользователь {user_id}")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /block 123456789", reply_markup=admin_kb())


async def cmd_unblock(message: Message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        user_id = int(message.text.split()[1])
        blocked_users.pop(user_id, None)
        save_blocked_users()
        await message.answer(f"✅ Пользователь <code>{user_id}</code> разблокирован", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
        logger.info(f"Разблокирован пользователь {user_id}")
    except (IndexError, ValueError):
        await message.answer("❌ Формат: /unblock 123456789", reply_markup=admin_kb())


async def cmd_clear(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ только админам", reply_markup=main_kb())
        return
    if DATA_FILE.exists():
        DATA_FILE.unlink()
        await message.answer("🗑️ <b>База очищена</b>", reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
    else:
        await message.answer("База пуста", reply_markup=admin_kb())


async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ только админам", reply_markup=main_kb())
        return
    if len(message.text.split()) < 2:
        await message.answer("❌ /broadcast ТЕКСТ_СООБЩЕНИЯ", reply_markup=admin_kb())
        return
    
    text = message.text.replace("/broadcast ", "", 1)
    sent = 0
    
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, f"📢 <b>Рассылка от админа:</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
        except:
            pass
    
    await message.answer(f"✅ Отправлено {sent}/{len(ADMINS)} админам", reply_markup=admin_kb())


async def finish_and_send(message: Message, state: FSMContext):
    global bot
    data = await state.get_data()
    
    record = {
        "user_id": message.from_user.id,
        "username": message.from_user.username or "нет",
        "full_name": data.get("full_name"),
        "military_unit": data.get("military_unit"),
        "personal_number": data.get("personal_number"),
        "room": data.get("room"),
        "military_id": data.get("military_id"),
        "lost_military_id_reason": data.get("lost_military_id_reason"),
        "veteran_certificate": data.get("veteran_certificate"),  # ✅ ИЗМЕНЕНО: было uvbd
        "salary": data.get("salary"),
        "salary_problems": data.get("salary_problems"),
        "contract_payments": data.get("contract_payments"),
        "contract_problems": data.get("contract_problems"),
        "more_questions": data.get("more_questions"),
        "more_questions_details": data.get("more_questions_details"),
        "timestamp": datetime.now().isoformat()
    }
    
    form_no = await save_record(record)
    
    report = f"""🆘 <b>НОВАЯ ЗАЯВКА #{form_no}</b>

👤 <b>ФИО:</b> {record['full_name']}
🏛️ <b>В/Ч:</b> {record['military_unit']}
🆔 <b>Личный №:</b> {record['personal_number']}
🏠 <b>Этаж/палата:</b> {record['room']}

📄 <b>Военный билет:</b> {record['military_id']}
{'' if record['military_id'] == '✅ Да' else f"📝 <b>Причина утраты:</b> {record['lost_military_id_reason']}"}

🎖️ <b>Удостоверение ВБД:</b> {record['veteran_certificate']}  # ✅ ИЗМЕНЕНО

💰 <b>Денежное довольствие:</b> {record['salary']}
{'' if record['salary'] == '✅ Да' else f"⚠️ <b>Проблемы:</b> {record['salary_problems']}"}

💸 <b>Выплаты после контракта:</b> {record['contract_payments']}
{'' if record['contract_payments'] == '✅ Да' else f"🔧 <b>Проблемы:</b> {record['contract_problems']}"}

❓ <b>Имеются ли еще проблемные вопросы:</b> {record['more_questions']}
{record['more_questions_details'] or ''}

🆔 <code>{record['user_id']}</code> | @{record['username']}
⏰ {record['timestamp']}"""
    
    try:
        for admin_id in ADMINS:
            await bot.send_message(admin_id, report, parse_mode=ParseMode.HTML)
            logger.info(f"Заявка #{form_no} отправлена админу {admin_id}")
        
        group_report = f"📢 <b>Новая заявка #{form_no}</b>\n\n{report}"
        await bot.send_message(chat_id=GROUP_CHAT_ID, text=group_report, parse_mode=ParseMode.HTML)
        logger.info(f"Заявка #{form_no} отправлена в группу")
        
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
    
    kb = admin_kb() if is_admin(message.from_user.id) else restart_kb()
    await message.answer(
        "✅ <b>Спасибо! Ваша заявка будет рассмотрена в ближайшее время</b>\n\n"
        "Нажмите кнопку ниже для новой заявки:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    await state.clear()


async def save_record(record: dict) -> int:
    async with file_lock:
        try:
            if DATA_FILE.exists():
                with DATA_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = []
            else:
                data = []
        except json.JSONDecodeError:
            data = []
        
        data.append(record)
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return len(data)


async def main():
    global bot
    load_blocked_users()
    
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    # ✅ РЕГИСТРАЦИЯ ВСЕХ ОБРАБОТЧИКОВ
    # Команды
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_cancel, Command("cancel"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_export_excel, Command("export"))
    dp.message.register(cmd_block, Command("block"))
    dp.message.register(cmd_unblock, Command("unblock"))
    dp.message.register(cmd_clear, Command("clear"))
    dp.message.register(cmd_broadcast, Command("broadcast"))
    
    # Кнопки
    dp.message.register(handle_restart_button, F.text.in_(["🚀 Начать заявку", "📤 Отправить заявку заново"]))
    dp.message.register(handle_admin_buttons, F.text.in_(["📊 Статистика", "📈 Экспорт Excel", "🚫 Блокировать", "✅ Разблокировать"]))
    
    # ✅ СОСТОЯНИЯ ОПРОСА - ОБНОВЛЕНО!
    dp.message.register(process_full_name, StateFilter(Survey.full_name))
    dp.message.register(process_military_unit, StateFilter(Survey.military_unit))
    dp.message.register(process_personal_number, StateFilter(Survey.personal_number))
    dp.message.register(process_room, StateFilter(Survey.room))
    dp.message.register(process_military_id, StateFilter(Survey.military_id))
    dp.message.register(process_lost_military_id_reason, StateFilter(Survey.lost_military_id_reason))
    dp.message.register(process_veteran_certificate, StateFilter(Survey.veteran_certificate))  # ✅ ИЗМЕНЕНО
    dp.message.register(process_salary, StateFilter(Survey.salary))
    dp.message.register(process_salary_problems, StateFilter(Survey.salary_problems))
    dp.message.register(process_contract_payments, StateFilter(Survey.contract_payments))
    dp.message.register(process_contract_problems, StateFilter(Survey.contract_problems))
    dp.message.register(process_more_questions, StateFilter(Survey.more_questions))
    dp.message.register(process_more_questions_details, StateFilter(Survey.more_questions_details))
    
    logger.info("🚀 Бот запущен!")
    print("🚀 Бот запущен! Админы:", ADMINS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
