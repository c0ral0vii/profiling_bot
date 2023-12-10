import os
import uuid

from dotenv import load_dotenv

load_dotenv()


# Допустимые файлообменники
filesharings = ['postimg', 'files']

# Генерация имён у фотографий
filename = 'image_' + str(uuid.uuid4()) + '.jpg'

# Путь к фотографиям
imgs_dir = 'map/temp/imgs/'

# Путь к фотографиям
file_path = os.path.join(imgs_dir, filename)


BOT_API_TOKEN = os.getenv('BOT_API_TOKEN')