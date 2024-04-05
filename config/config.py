import os
import uuid

from dotenv import load_dotenv

load_dotenv()


# Допустимые файлообменники
filesharings = ['postimg']

# Генерация имён у фотографий
filename = ('imlist'
            'age_') + str(uuid.uuid4()) + '.jpg'

# Путь к фотографиям
def generate_path(user):
    return f'map/generate_map/{user}/temp/imgs/'

# Путь к фотографиям
# file_path = os.path.join(imgs_dir, filename)

# Апи токен бота
BOT_API_TOKEN = os.getenv('BOT_API_TOKEN')

# Пользователи, которые могут работать с ботом
allowed_users = [944360812,]
