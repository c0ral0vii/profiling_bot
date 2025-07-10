from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


async def main_menu_keyboard(status: bool = False) -> ReplyKeyboardMarkup:
    """
    Creates a main menu keyboard with buttons for 'Start', 'Help', and 'Settings'.
    """
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Изменить тип")], [KeyboardButton(text=f"Координаты с одной цифрой: {'✅' if status else '❌'}")]], resize_keyboard=True)
    
    
    return kb