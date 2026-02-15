import asyncio
import json
import logging
import re
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, html
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
DATA_FILE = Path("data.json")
BLOCKED_FILE = Path("blocked.json")
LOG_FILE = Path("bot.log")
EXCEL_EXPORT_DIR = Path("exports")

bot: Optional[Bot] = None
file_lock = asyncio.Lock()
spam_protection = {}
blocked_users: Dict[int, Any] = {}

COOLDOWN_TIME = 3600

EXCEL_EXPORT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class Survey(StatesGroup):
    full_name = State()
    military_unit = State()
    company_battalion = State()
    personal_number = State()
    room = State()
    military_id = State()
    lost_military_id_reason = State()
    veteran_certificate = State()
    salary = State()
    salary_problems = State()
    contract_payments = State()
    contract_problems = State()
    more_questions = State()
    more_questions_details = State()
    phone_number = State()


class AdminStates(StatesGroup):
    block_user = State()
    unblock_user = State()


def load_blocked_users():
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
    if re.match(r'^\d{5}$', unit):
        return True, ""
    return False, "В/ч должна содержать ровно 5 цифр! Пример: 12345"


def validate_phone_number(phone: str) -> tuple[bool, str]:
    """Валидация номера телефона в формате +7XXXXXXXXXX или 8XXXXXXXXXX"""
    cleaned = re.sub(r'[^\d+]', '', phone)

    if re.match(r'^\+7\d{10}$', cleaned):
        return True, ""

    if re.match(r'^8\d{10}$', cleaned):
        return True, ""

    if re.match(r'^7\d{10}$', cleaned):
        return True, ""

    return False, "❌ Неверный формат!\n\nДопустимые форматы:\n+79991234567\n89991234567\n79991234567"


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
            return True, f"⏳ Подождите {minutes} мин"
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
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📥 Выгрузить данные")],
            [KeyboardButton(text="🚫 Заблокировать пользователя")],
            [KeyboardButton(text="✅ Разблокировать пользователя")],
            [KeyboardButton(text="📋 Список заблокированных")]
        ],
        resize_keyboard=True
    )


def yes_no_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")]
        ],
        resize_keyboard=True
    )


async def save_data(data: dict):
    async with file_lock:
        records = []
        if DATA_FILE.exists():
            try:
                with DATA_FILE.open("r", encoding="utf-8") as f:
                    records = json.load(f)
            except:
                records = []
        records.append(data)
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)


# === HANDLERS ===

async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if is_admin(message.from_user.id):
        await message.answer(
            "👋 Добро пожаловать, администратор!\n\n"
            "Выберите действие:",
            reply_markup=admin_kb()
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в бот для подачи заявок!\n\n"
            "Нажмите кнопку ниже, чтобы начать:",
            reply_markup=main_kb()
        )


async def start_survey(message: Message, state: FSMContext):
    spam, msg = is_spam(message.from_user.id)
    if spam:
        await message.answer(msg)
        return

    await state.set_state(Survey.full_name)
    await message.answer(
        "📝 Начинаем заполнение заявки\n\n"
        "Введите ФИО (Фамилия Имя Отчество):",
        reply_markup=ReplyKeyboardRemove()
    )


async def process_full_name(message: Message, state: FSMContext):
    valid, error = validate_fio(message.text)
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(full_name=message.text.strip())
    await state.set_state(Survey.military_unit)
    await message.answer("Введите номер войсковой части (5 цифр):")


async def process_military_unit(message: Message, state: FSMContext):
    valid, error = validate_military_unit(message.text.strip())
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(military_unit=message.text.strip())
    await state.set_state(Survey.company_battalion)
    await message.answer("Введите вашу роту / батальон:")


async def process_company_battalion(message: Message, state: FSMContext):
    await state.update_data(company_battalion=message.text.strip())
    await state.set_state(Survey.personal_number)
    await message.answer("Введите личный номер (формат: А-123456 или АБ-123456):")


async def process_personal_number(message: Message, state: FSMContext):
    valid, error = validate_personal_number(message.text.strip())
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(personal_number=message.text.strip().upper())
    await state.set_state(Survey.room)
    await message.answer("Введите номер этажа / комнаты / кровати:")


async def process_room(message: Message, state: FSMContext):
    await state.update_data(room=message.text.strip())
    await state.set_state(Survey.military_id)
    await message.answer(
        "Имеется ли у Вас военный билет?",
        reply_markup=yes_no_kb()
    )


async def process_military_id(message: Message, state: FSMContext):
    answer = norm_yes_no(message.text)
    if answer is None:
        await message.answer("❌ Пожалуйста, выберите Да или Нет", reply_markup=yes_no_kb())
        return

    await state.update_data(military_id=answer)

    if not answer:
        await state.set_state(Survey.lost_military_id_reason)
        await message.answer(
            "Опишите причину отсутствия военного билета:",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await state.set_state(Survey.veteran_certificate)
        await message.answer(
            "Имеется ли у Вас удостоверение ветерана боевых действий?",
            reply_markup=yes_no_kb()
        )


async def process_lost_military_id_reason(message: Message, state: FSMContext):
    valid, error = validate_text_length(message.text, 10)
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(lost_military_id_reason=message.text.strip())
    await state.set_state(Survey.veteran_certificate)
    await message.answer(
        "Имеется ли у Вас удостоверение ветерана боевых действий?",
        reply_markup=yes_no_kb()
    )


async def process_veteran_certificate(message: Message, state: FSMContext):
    answer = norm_yes_no(message.text)
    if answer is None:
        await message.answer("❌ Пожалуйста, выберите Да или Нет", reply_markup=yes_no_kb())
        return

    await state.update_data(veteran_certificate=answer)
    await state.set_state(Survey.salary)
    await message.answer("Выплачивается ли вам денежное довольствие?", reply_markup=yes_no_kb())


async def process_salary(message: Message, state: FSMContext):
    answer = norm_yes_no(message.text)
    if answer is None:
        await message.answer("❌ Пожалуйста, выберите Да или Нет", reply_markup=yes_no_kb())
        return

    await state.update_data(salary=answer)

    if not answer:
        await state.set_state(Survey.salary_problems)
        await message.answer(
            "Опишите проблему с денежным довольствием:",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await state.set_state(Survey.contract_payments)
        await message.answer(
            "Выплачены ли все выплаты за контракт (подъёмные, ежемесячные)?",
            reply_markup=yes_no_kb()
        )


async def process_salary_problems(message: Message, state: FSMContext):
    valid, error = validate_text_length(message.text, 10)
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(salary_problems=message.text.strip())
    await state.set_state(Survey.contract_payments)
    await message.answer(
        "Выплачены ли все выплаты за контракт (подъёмные, ежемесячные)?",
        reply_markup=yes_no_kb()
    )


async def process_contract_payments(message: Message, state: FSMContext):
    answer = norm_yes_no(message.text)
    if answer is None:
        await message.answer("❌ Пожалуйста, выберите Да или Нет", reply_markup=yes_no_kb())
        return

    await state.update_data(contract_payments=answer)

    if not answer:
        await state.set_state(Survey.contract_problems)
        await message.answer(
            "Опишите проблему с выплатами:",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await state.set_state(Survey.more_questions)
        await message.answer(
            "Остались ли у Вас ещё вопросы?",
            reply_markup=yes_no_kb()
        )


async def process_contract_problems(message: Message, state: FSMContext):
    valid, error = validate_text_length(message.text, 10)
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(contract_problems=message.text.strip())
    await state.set_state(Survey.more_questions)
    await message.answer("Есть ли у Вас ещё вопросы?", reply_markup=yes_no_kb())


async def process_more_questions(message: Message, state: FSMContext):
    answer = norm_yes_no(message.text)
    if answer is None:
        await message.answer("❌ Пожалуйста, выберите Да или Нет", reply_markup=yes_no_kb())
        return

    await state.update_data(more_questions=answer)

    if answer:
        await state.set_state(Survey.more_questions_details)
        await message.answer(
            "Опишите ваши вопросы:",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await state.update_data(more_questions_details="Нет")
        await state.set_state(Survey.phone_number)
        await message.answer(
            "Введите ваш номер телефона\n\n"
            "Формат: +79991234567 или 89991234567",
            reply_markup=ReplyKeyboardRemove()
        )


async def process_more_questions_details(message: Message, state: FSMContext):
    valid, error = validate_text_length(message.text, 10)
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(more_questions_details=message.text.strip())
    await state.set_state(Survey.phone_number)
    await message.answer(
        "Введите ваш номер телефона\n\n"
        "Формат: +79991234567 или 89991234567"
    )


async def process_phone_number(message: Message, state: FSMContext):
    valid, error = validate_phone_number(message.text.strip())
    if not valid:
        await message.answer(f"{error}\n\nПопробуйте ещё раз:")
        return

    await state.update_data(phone_number=message.text.strip())
    data = await state.get_data()

    try:
        # Экранируем все пользовательские данные
        full_name = html.quote(data['full_name'])
        military_unit = html.quote(data['military_unit'])
        company_battalion = html.quote(data['company_battalion'])
        personal_number = html.quote(data['personal_number'])
        room = html.quote(data['room'])
        phone_number = html.quote(data['phone_number'])

        # Формируем статусы для emoji
        military_id_status = "✅ Да" if data['military_id'] else "❌ Нет"
        veteran_cert_status = "✅ Да" if data['veteran_certificate'] else "❌ Нет"
        salary_status = "✅ Выплачивается" if data['salary'] else "❌ Не выплачивается"
        contract_status = "✅ Выплачены" if data['contract_payments'] else "❌ Не выплачены"
        more_questions_status = "✅ Да" if data['more_questions'] else "❌ Нет"

        # Формируем текст заявки
        report = f"""📋 <b>НОВАЯ ЗАЯВКА</b>

👤 <b>ФИО:</b> {full_name}
🏢 <b>Войсковая часть:</b> {military_unit}
🪖 <b>Рота/батальон:</b> {company_battalion}
🆔 <b>Личный номер:</b> {personal_number}
🚪 <b>Комната:</b> {room}

📱 <b>Телефон:</b> {phone_number}

📄 <b>Военный билет:</b> {military_id_status}
"""

        if not data['military_id']:
            lost_reason = html.quote(data.get('lost_military_id_reason', 'Не указана'))
            report += f"   └ <b>Причина:</b> {lost_reason}\n"

        report += f"\n🎖 <b>Удостоверение ветерана:</b> {veteran_cert_status}\n"
        report += f"\n💰 <b>Денежное довольствие:</b> {salary_status}\n"

        if not data['salary']:
            salary_prob = html.quote(data.get('salary_problems', 'Не указана'))
            report += f"   └ <b>Проблема:</b> {salary_prob}\n"

        report += f"\n💵 <b>Контрактные выплаты:</b> {contract_status}\n"

        if not data['contract_payments']:
            contract_prob = html.quote(data.get('contract_problems', 'Не указана'))
            report += f"   └ <b>Проблема:</b> {contract_prob}\n"

        report += f"\n❓ <b>Дополнительные вопросы:</b> {more_questions_status}\n"

        if data['more_questions']:
            more_details = html.quote(data.get('more_questions_details', 'Не указаны'))
            report += f"   └ {more_details}\n"

        username = message.from_user.username or 'Нет username'
        report += f"\n👤 <b>От пользователя:</b> @{username} (ID: {message.from_user.id})"
        report += f"\n📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        # Сохраняем данные
        save_record = {
            **data,
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "timestamp": datetime.now().isoformat()
        }
        await save_data(save_record)

        # Отправляем всем администраторам
        logger.info(f"Отправка заявки всем администраторам: {ADMINS}")

        success_count = 0
        for admin_id in ADMINS:
            try:
                await bot.send_message(admin_id, report, parse_mode=ParseMode.HTML)
                success_count += 1
                logger.info(f"Заявка успешно отправлена администратору {admin_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки администратору {admin_id}: {e}")

        if success_count > 0:
            logger.info(f"Заявка отправлена {success_count} из {len(ADMINS)} администраторам")
            await message.answer(
                "✅ Ваша заявка успешно отправлена!\n\n"
                "Спасибо за обращение. С вами свяжутся в ближайшее время.",
                reply_markup=restart_kb()
            )
        else:
            logger.error("Не удалось отправить заявку ни одному администратору")
            await message.answer(
                "⚠️ Заявка сохранена, но не удалось отправить уведомление администраторам.\n\n"
                "С вами свяжутся позже.",
                reply_markup=restart_kb()
            )

    except Exception as e:
        logger.error(f"ОШИБКА при обработке заявки: {type(e).__name__}: {str(e)}")
        logger.error(f"Данные заявки: {data}")

        await message.answer(
            f"❌ Произошла ошибка при обработке заявки\n\n"
            f"Тип ошибки: {type(e).__name__}\n"
            f"Данные сохранены. Попробуйте позже или обратитесь к администратору.",
            reply_markup=restart_kb()
        )

    await state.clear()


# === ADMIN HANDLERS ===

async def show_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    records = []
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                records = json.load(f)
        except:
            pass

    total = len(records)
    blocked_count = len(blocked_users)

    await message.answer(
        f"📊 <b>Статистика бота</b>\n\n"
        f"📝 Всего заявок: {total}\n"
        f"🚫 Заблокировано пользователей: {blocked_count}",
        parse_mode=ParseMode.HTML
    )


async def export_data(message: Message):
    if not is_admin(message.from_user.id):
        return

    if not DATA_FILE.exists():
        await message.answer("❌ Нет данных для выгрузки")
        return

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = EXCEL_EXPORT_DIR / f"export_{timestamp}.csv"

        with DATA_FILE.open("r", encoding="utf-8") as f:
            records = json.load(f)

        if not records:
            await message.answer("❌ Нет данных для выгрузки")
            return

        with csv_file.open("w", encoding="utf-8-sig", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)

        await message.answer_document(
            FSInputFile(csv_file),
            caption="📥 Выгрузка данных"
        )

        csv_file.unlink()

    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}")
        await message.answer(f"❌ Ошибка экспорта: {e}")


async def start_block_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminStates.block_user)
    await message.answer(
        "Введите ID пользователя для блокировки:",
        reply_markup=ReplyKeyboardRemove()
    )


async def process_block_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        if user_id in ADMINS:
            await message.answer("❌ Нельзя заблокировать администратора!")
            await state.clear()
            return

        blocked_users[user_id] = {
            "blocked_at": datetime.now().isoformat(),
            "blocked_by": message.from_user.id
        }
        save_blocked_users()

        await message.answer(
            f"✅ Пользователь {user_id} заблокирован",
            reply_markup=admin_kb()
        )
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    await state.clear()


async def start_unblock_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminStates.unblock_user)
    await message.answer(
        "Введите ID пользователя для разблокировки:",
        reply_markup=ReplyKeyboardRemove()
    )


async def process_unblock_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        if user_id in blocked_users:
            del blocked_users[user_id]
            save_blocked_users()
            await message.answer(
                f"✅ Пользователь {user_id} разблокирован",
                reply_markup=admin_kb()
            )
        else:
            await message.answer(
                f"❌ Пользователь {user_id} не был заблокирован",
                reply_markup=admin_kb()
            )
    except ValueError:
        await message.answer("❌ Неверный формат ID. Введите число:")
        return

    await state.clear()


async def show_blocked_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    if not blocked_users:
        await message.answer("✅ Нет заблокированных пользователей")
        return

    text = "🚫 <b>Заблокированные пользователи:</b>\n\n"
    for user_id, info in blocked_users.items():
        blocked_at = datetime.fromisoformat(info['blocked_at']).strftime("%d.%m.%Y %H:%M")
        text += f"• ID: {user_id}\n  Заблокирован: {blocked_at}\n\n"

    await message.answer(text, parse_mode=ParseMode.HTML)


async def main():
    global bot

    load_blocked_users()

    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Регистрация хендлеров
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(start_survey, F.text == "🚀 Начать заявку")
    dp.message.register(start_survey, F.text == "📤 Отправить заявку заново")

    # Survey handlers
    dp.message.register(process_full_name, Survey.full_name)
    dp.message.register(process_military_unit, Survey.military_unit)
    dp.message.register(process_company_battalion, Survey.company_battalion)
    dp.message.register(process_personal_number, Survey.personal_number)
    dp.message.register(process_room, Survey.room)
    dp.message.register(process_military_id, Survey.military_id)
    dp.message.register(process_lost_military_id_reason, Survey.lost_military_id_reason)
    dp.message.register(process_veteran_certificate, Survey.veteran_certificate)
    dp.message.register(process_salary, Survey.salary)
    dp.message.register(process_salary_problems, Survey.salary_problems)
    dp.message.register(process_contract_payments, Survey.contract_payments)
    dp.message.register(process_contract_problems, Survey.contract_problems)
    dp.message.register(process_more_questions, Survey.more_questions)
    dp.message.register(process_more_questions_details, Survey.more_questions_details)
    dp.message.register(process_phone_number, Survey.phone_number)

    # Admin handlers
    dp.message.register(show_stats, F.text == "📊 Статистика")
    dp.message.register(export_data, F.text == "📥 Выгрузить данные")
    dp.message.register(start_block_user, F.text == "🚫 Заблокировать пользователя")
    dp.message.register(process_block_user, AdminStates.block_user)
    dp.message.register(start_unblock_user, F.text == "✅ Разблокировать пользователя")
    dp.message.register(process_unblock_user, AdminStates.unblock_user)
    dp.message.register(show_blocked_list, F.text == "📋 Список заблокированных")

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
