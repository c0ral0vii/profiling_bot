import re

from config.config import filesharings, imgs_dir
from .parsing import get_imgs


async def check_filesharing(text: str, user):
    '''Проверка является ли текст файлообменником'''

    regular = r'\b(?:{})\b'.format('|'.join(filesharings))
    result = re.search(regular, text)

    if result:
        await get_imgs(url=text)

        url = 'Готово'
        return url
    else:
        return 'Ссылка указана неверно'



async def generate_link():
    '''Генерация ссылки на карту'''
    
    ...


async def generate_map():
    '''Генерация карты'''

    ...