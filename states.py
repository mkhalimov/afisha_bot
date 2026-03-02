from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    title = State()
    category = State()
    event_date = State()
    time_start = State()
    time_end = State()
    location = State()
    description = State()
    organizer = State()
    image = State()
    done = State()


class AdminReject(StatesGroup):
    waiting_reason = State()
