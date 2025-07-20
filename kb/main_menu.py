from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


async def main_menu_keyboard(status: bool = False) -> ReplyKeyboardMarkup:
    """
    Creates a main menu keyboard with buttons for 'Start', 'Help', and 'Settings'.
    """
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Включить/выключить проверку Тайланда")], [KeyboardButton(text=f"Тайланд: {'✅' if status else '❌'}")]], resize_keyboard=True)


    return kb