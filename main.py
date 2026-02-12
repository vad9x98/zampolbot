import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# === НАСТРОЙКИ ===
API_TOKEN = "TOKEN"
ADMINS = [7753983073, 1414261920]
GROUP_CHAT_ID = -1003728047688
DATA_FILE = Path("data.json")
LOG_FILE = Path("bot.log")

bot: Optional[Bot] = None
file_lock = asyncio.Lock()
spam_protection = {}
COOLDOWN_TIME = 300

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
    uvbd = State()
    salary = State()
    salary_problems = State()
    contract_payments = State()
    contract_problems = State()
    more_questions = State()
    more_questions_details = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def validate_fio(fio: str) -> tuple[bool, str]:
    parts = [p.strip() for p in fio.split()]
    if len(parts) != 3:
        return False, "Нужно Фамилия Имя Отчество, через пробел"
    if any(len(part) < 3 or not part.replace(' ', '').isalpha() for part in parts):
        return False, "Каждая часть минимум 3 буквы, только буквы"
    return True, ""


def norm_yes_no(text: str) -> Optional[bool]:
    t = (text or "").strip().lower()
    if t in ("✅ да", "да", "yes", "y", "1", "+"):
        return True
    if t in ("❌ нет", "нет", "no", "n", "0", "-"):
        return False
    return None


def is_spam(user_id: int) -> tuple[bool, str]:
    loop = asyncio.get_event_loop()
    now = loop.time()
    if user_id in spam_protection:
        if now - spam_protection[user_id] < COOLDOWN_TIME:
            remaining = COOLDOWN_TIME - (now - spam_protection[user_id])
            return True, f"⏳ Подожди {remaining:.0f} сек (5 мин между заявками)"
    spam_protection[user_id] = now
    return False, ""


def yes_no_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")]],
        resize_keyboard=True, one_time_keyboard=True
    )


async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if await state.get_state() is not None:
        await state.clear()
    
    is_spam_flag, spam_msg = is_spam(user_id)
    if is_spam_flag:
        await message.answer(spam_msg)
        return
    
    await state.clear()
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


async def process_full_name(message: Message, state: FSMContext):
    fio = message.text.strip()
    valid, error = validate_fio(fio)
    
    if not valid:
        await message.answer(f"❌ {error}\n\nПопробуйте ещё раз:")
        return
    
    await state.update_data(full_name=fio)
    await message.answer("🏛️ Укажите воинскую часть (в/ч)")
    await state.set_state(Survey.military_unit)


async def process_military_unit(message: Message, state: FSMContext):
    await state.update_data(military_unit=message.text.strip())
    await message.answer("🆔 Укажите личный номер")
    await state.set_state(Survey.personal_number)


async def process_personal_number(message: Message, state: FSMContext):
    await state.update_data(personal_number=message.text.strip())
    await message.answer("🏠 Укажите этаж и палата/кровать\nПример: 2 этаж, палата 15 / кровать 3")
    await state.set_state(Survey.room)


async def process_room(message: Message, state: FSMContext):
    await state.update_data(room=message.text.strip())
    await message.answer("📄 Есть ли на руках военный билет?", reply_markup=yes_no_kb())
    await state.set_state(Survey.military_id)


async def process_military_id(message: Message, state: FSMContext):
    ans = norm_yes_no(message.text)
    if ans is None:
        await message.answer("❌ Выберите кнопку: ✅ Да / ❌ Нет")
        return
    
    await state.update_data(military_id="✅ Да" if ans else "❌ Нет")
    
    if ans:
        await message.answer("📋 Есть ли у вас УВБД?", reply_markup=yes_no_kb())
        await state.set_state(Survey.uvbd)
    else:
        await message.answer("При каких обстоятельствах утерян военный билет?")
        await state.set_state(Survey.lost_military_id_reason)


async def process_lost_military_id(message: Message, state: FSMContext):
    await state.update_data(lost_military_id_reason=message.text.strip())
    await message.answer("📋 Есть ли у вас УВБД?", reply_markup=yes_no_kb())
    await state.set_state(Survey.uvbd)


async def process_uvbd(message: Message, state: FSMContext):
    ans = norm_yes_no(message.text)
    if ans is None:
        await message.answer("❌ Выберите кнопку: ✅ Да / ❌ Нет")
        return
    await state.update_data(uvbd="✅ Да" if ans else "❌ Нет")
    await message.answer("💰 <b>Получаешь ли ты денежное довольствие в полном объеме?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.salary)


async def process_salary(message: Message, state: FSMContext):
    ans = norm_yes_no(message.text)
    if ans is None:
        await message.answer("❌ Выберите кнопку: ✅ Да / ❌ Нет")
        return
    await state.update_data(salary="✅ Да" if ans else "❌ Нет")
    
    if ans:
        await message.answer("💸 <b>Получил ли ты выплаты после подписания контракта в полном объеме?</b>", reply_markup=yes_no_kb())
        await state.set_state(Survey.contract_payments)
    else:
        await message.answer("💰 <b>Укажите какой вид денежного довольствия и за какой период вы НЕ получали</b>")
        await state.set_state(Survey.salary_problems)


async def process_salary_problems(message: Message, state: FSMContext):
    await state.update_data(salary_problems=message.text.strip())
    await message.answer("💸 <b>Получил ли ты выплаты после подписания контракта в полном объеме?</b>", reply_markup=yes_no_kb())
    await state.set_state(Survey.contract_payments)


async def process_contract_payments(message: Message, state: FSMContext):
    ans = norm_yes_no(message.text)
    if ans is None:
        await message.answer("❌ Выберите кнопку: ✅ Да / ❌ Нет")
        return
    await state.update_data(contract_payments="✅ Да" if ans else "❌ Нет")
    
    if ans:
        kb = yes_no_kb()
        await message.answer("<b>Имеются ли еще какие-либо проблемные вопросы?</b>", reply_markup=kb)
        await state.set_state(Survey.more_questions)
    else:
        await message.answer("💸 <b>С какими выплатами возникли проблемы (региональные / федеральные)?</b>")
        await state.set_state(Survey.contract_problems)


async def process_contract_problems(message: Message, state: FSMContext):
    await state.update_data(contract_problems=message.text.strip())
    kb = yes_no_kb()
    await message.answer("<b>Имеются ли еще какие-либо проблемные вопросы?</b>", reply_markup=kb)
    await state.set_state(Survey.more_questions)


async def process_more_questions(message: Message, state: FSMContext):
    ans = norm_yes_no(message.text)
    if ans is None:
        await message.answer("❌ Выберите кнопку: ✅ Да / ❌ Нет")
        return
    await state.update_data(more_questions="✅ Да" if ans else "❌ Нет")
    
    if ans:
        await message.answer("Какие вопросы?", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Survey.more_questions_details)
    else:
        await finish_and_send(message, state)


async def process_more_questions_details(message: Message, state: FSMContext):
    await state.update_data(more_questions_details=message.text.strip())
    await finish_and_send(message, state)


async def cmd_cancel(message: Message, state: FSMContext):
    cur_state = await state.get_state()
    if cur_state is None:
        await message.answer("Нечего отменять. /start — начать", reply_markup=ReplyKeyboardRemove())
        return
    await state.clear()
    await message.answer("✅ Отменено. /start — начать заново", reply_markup=ReplyKeyboardRemove())


async def cmd_help(message: Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        help_text = """📋 <b>Команды:</b>
/start — начать заявку
/cancel — отменить
/help — это меню
/stats — статистика
/clear — очистить базу
/broadcast — рассылка админам

<i>Заявки идут всем админам + в группу</i>"""
    else:
        help_text = """📋 <b>Команды:</b>
/start — начать заявку
/cancel — отменить
/help — помощь"""
    
    await message.answer(help_text, parse_mode=ParseMode.HTML)


async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with file_lock:
        try:
            if DATA_FILE.exists():
                with DATA_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                count = len(data)
                latest = data[-1]["timestamp"] if data else "нет"
                await message.answer(f"📊 <b>Статистика:</b>\nВсего заявок: {count}\nПоследняя: {latest}", parse_mode=ParseMode.HTML)
            else:
                await message.answer("📊 Заявок: 0")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")


async def cmd_clear(message: Message):
    if not is_admin(message.from_user.id):
        return
    if DATA_FILE.exists():
        DATA_FILE.unlink()
        await message.answer("🗑️ <b>База очищена</b>", parse_mode=ParseMode.HTML)
    else:
        await message.answer("База пуста")


async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return
    if len(message.text.split()) < 2:
        await message.answer("❌ /broadcast ТЕКСТ_СООБЩЕНИЯ")
        return
    
    text = message.text.replace("/broadcast ", "", 1)
    sent = 0
    
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, f"📢 <b>Рассылка от админа:</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
        except:
            pass
    
    await message.answer(f"✅ Отправлено {sent}/{len(ADMINS)} админам")


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
        "uvbd": data.get("uvbd"),
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

📋 <b>УВБД:</b> {record['uvbd']}

💰 <b>Денежное довольствие:</b> {record['salary']}
{'' if record['salary'] == '✅ Да' else f"⚠️ <b>Проблемы:</b> {record['salary_problems']}"}

💸 <b>Выплаты после контракта:</b> {record['contract_payments']}
{'' if record['contract_payments'] == '✅ Да' else f"🔧 <b>Проблемы:</b> {record['contract_problems']}"}

❓ <b>Имеются ли еще проблемные вопросы:</b> {record['more_questions']}
{record['more_questions_details'] or ''}

🆔 <code>{record['user_id']}</code> | @{record['username']}
⏰ {record['timestamp']}"""
    
    try:
        # Всем админам
        for admin_id in ADMINS:
            await bot.send_message(admin_id, report, parse_mode=ParseMode.HTML)
            logger.info(f"Заявка #{form_no} отправлена админу {admin_id}")
        
        # В группу
        group_report = f"📢 <b>Новая заявка #{form_no}</b>\n\n{report}"
        await bot.send_message(chat_id=GROUP_CHAT_ID, text=group_report, parse_mode=ParseMode.HTML)
        logger.info(f"Заявка #{form_no} отправлена в группу")
        
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
    
    await message.answer("✅ <b>Спасибо! Заявка отправлена админам + в группу</b>", 
                        reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.HTML)
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
    
    bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_cancel, Command("cancel"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_stats, Command("stats"))
    dp.message.register(cmd_clear, Command("clear"))
    dp.message.register(cmd_broadcast, Command("broadcast"))
    
    dp.message.register(process_full_name, StateFilter(Survey.full_name))
    dp.message.register(process_military_unit, StateFilter(Survey.military_unit))
    dp.message.register(process_personal_number, StateFilter(Survey.personal_number))
    dp.message.register(process_room, StateFilter(Survey.room))
    dp.message.register(process_military_id, StateFilter(Survey.military_id))
    dp.message.register(process_lost_military_id, StateFilter(Survey.lost_military_id_reason))
    dp.message.register(process_uvbd, StateFilter(Survey.uvbd))
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

