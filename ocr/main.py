import asyncio
import re
import ssl
from io import BytesIO

import aiohttp
import numpy as np
from easyocr import Reader
from PIL import Image
from typing import List, Dict, Union, Tuple

ssl._create_default_https_context = ssl._create_unverified_context

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

pool_instance = None
reader = Reader(["en"], gpu=False)


def preprocess_image(img: Image.Image) -> np.ndarray:
    """Предобработка изображения для улучшения распознавания"""
    # Конвертация в grayscale
    img = img.convert("L")
    
    # Увеличение контраста
    img_array = np.array(img)
    
    # Нормализация яркости
    mean = img_array.mean()
    if mean < 100:  # Если изображение слишком темное
        img_array = np.clip(img_array * 1.5, 0, 255)
    elif mean > 200:  # Если изображение слишком светлое
        img_array = np.clip(img_array * 0.8, 0, 255)
    
    return img_array.astype(np.uint8)


def is_valid_coordinate(coord: str) -> bool:
    """Проверка, является ли строка валидной координатой"""
    try:
        num = float(coord)
        # Проверяем разумный диапазон для координат
        return 0.1 <= abs(num) <= 180.0
    except ValueError:
        return False


def filter_false_positives(coords: List[str]) -> List[str]:
    """Фильтрация ложных срабатываний"""
    filtered = []
    
    for coord in coords:
        # Игнорируем очевидные даты
        if re.match(r'^\d{1,2}\.\d{1,2}\.20\d{2}$', coord):
            continue
        # Игнорируем версии ПО (например, 1.2.3)
        if coord.count('.') >= 2 and len(coord) < 10:
            continue
        # Игнорируем слишком короткие "координаты"
        if len(coord) < 5:
            continue
            
        filtered.append(coord)
    
    return filtered


def extract_coordinates_from_text(text: str, coord_status: bool = False) -> List[str]:
    """Извлечение координат из текста с улучшенной логикой"""
    
    # Основной паттерн для координат
    if coord_status:
        # Более строгий паттерн
        patterns = [
            r'\b(\d{1,3}[.,]\d{4,8})\b',  # 30.1234, 123.456789
        ]
    else:
        # Более гибкий паттерн
        patterns = [
            r'\b(\d{1,3}[.,]\d{4,8})\b',  # Основной паттерн
            r'\b(\d{1,3}\s*[.,]\s*\d{4,8})\b',  # С пробелами вокруг точки
        ]
    
    all_coords = []
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            # Нормализация формата
            coord = match.replace(',', '.').replace(' ', '')
            if is_valid_coordinate(coord):
                all_coords.append(coord)
    
    # Удаление дубликатов с сохранением порядка
    seen = set()
    unique_coords = []
    for coord in all_coords:
        if coord not in seen:
            seen.add(coord)
            unique_coords.append(coord)
    
    return filter_false_positives(unique_coords)


async def process_img(
    img_link: str,
    reader: Reader,
    semaphore: asyncio.Semaphore,
    coord_status: bool = False,
) -> Union[Dict, str, None]:
    async with semaphore:
        try:
            if "%IMAGE_EXT%" in img_link:
                img_link = img_link.replace("%IMAGE_EXT%", "jpg")

            async with aiohttp.ClientSession() as session:
                async with session.get(img_link, ssl=ctx, timeout=30) as response:
                    if response.status == 200:
                        img_data = await response.read()
                    else:
                        return f"Ошибка загрузки - {img_link}"

            img = Image.open(BytesIO(img_data))
            img_processed = preprocess_image(img)
            
            # Распознавание текста с улучшенными параметрами
            result = reader.readtext(
                img_processed,
                detail=1,
                paragraph=False,
                contrast_ths=0.1,
                adjust_contrast=0.5,
                text_threshold=0.7
            )

            all_detected_coords = []
            
            for line in result:
                bbox, text, confidence = line
                
                # Пропускаем низкокачественные распознавания
                if confidence < 0.5:
                    continue
                    
                print(f"Распознано: '{text}' (уверенность: {confidence:.2f})")
                
                # Извлекаем координаты из текста
                coords = extract_coordinates_from_text(text, coord_status)
                all_detected_coords.extend(coords)
            
            # Фильтрация и группировка координат
            valid_coords = []
            for coord in all_detected_coords:
                if is_valid_coordinate(coord) and coord not in valid_coords:
                    valid_coords.append(coord)
            
            print(f"Найдено координат для {img_link}: {valid_coords}")
            
            if len(valid_coords) >= 2:
                # Возвращаем все найденные координаты
                return {img_link: valid_coords}
            elif valid_coords:
                # Если координат меньше 2, но они есть
                return {img_link: valid_coords}
            else:
                return None
                
        except asyncio.TimeoutError:
            return f"Таймаут - {img_link}"
        except Exception as e:
            return f"Ошибка обработки - {img_link}: {str(e)}"


async def check_img(img_urls: List[str], coord_status: bool = False) -> List:
    """Улучшенный EasyOCR для поиска координат на фотографиях"""
    
    semaphore = asyncio.Semaphore(4)
    tasks = [
        asyncio.create_task(process_img(img_link, reader, semaphore, coord_status))
        for img_link in img_urls
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    coordinates = {}
    stats = {
        'success': 0,
        'with_coords': 0,
        'errors': 0
    }

    for result in results:
        if isinstance(result, Exception):
            print(f"Ошибка: {result}")
            stats['errors'] += 1
        elif isinstance(result, dict):
            coordinates.update(result)
            stats['with_coords'] += 1
            stats['success'] += 1
        elif isinstance(result, str) and result.startswith('Ошибка'):
            print(result)
            stats['errors'] += 1
        else:
            stats['success'] += 1

    total_found = sum(len(coords) for coords in coordinates.values())
    
    return [
        coordinates, 
        f"Найдено: {total_found} координат на {stats['with_coords']}/{len(img_urls)} изображений",
        stats
    ]


# Дополнительная функция для тестирования на локальных изображениях
async def test_local_images(image_paths: List[str], coord_status: bool = False) -> List:
    """Тестирование на локальных файлах"""
    
    async def process_local_image(img_path: str, semaphore: asyncio.Semaphore) -> Union[Dict, str, None]:
        async with semaphore:
            try:
                img = Image.open(img_path)
                img_processed = preprocess_image(img)
                
                result = reader.readtext(
                    img_processed,
                    detail=1,
                    paragraph=False,
                    contrast_ths=0.1,
                    adjust_contrast=0.5
                )

                all_detected_coords = []
                
                for line in result:
                    bbox, text, confidence = line
                    if confidence < 0.5:
                        continue
                        
                    print(f"Распознано: '{text}' (уверенность: {confidence:.2f})")
                    coords = extract_coordinates_from_text(text, coord_status)
                    all_detected_coords.extend(coords)
                
                valid_coords = []
                for coord in all_detected_coords:
                    if is_valid_coordinate(coord) and coord not in valid_coords:
                        valid_coords.append(coord)
                
                print(f"Найдено координат для {img_path}: {valid_coords}")
                
                if valid_coords:
                    return {img_path: valid_coords}
                else:
                    return None
                    
            except Exception as e:
                return f"Ошибка обработки - {img_path}: {str(e)}"

    semaphore = asyncio.Semaphore(4)
    tasks = [
        asyncio.create_task(process_local_image(img_path, semaphore))
        for img_path in image_paths
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    coordinates = {}
    for result in results:
        if isinstance(result, dict):
            coordinates.update(result)
    
    return [coordinates, f"{len(coordinates)}/{len(image_paths)}"]


task_list = []


async def stop() -> str:
    """Остановка обработки фотографий"""
    if len(task_list) > 0:
        for task in task_list:
            task.cancel()
        return "Остановлено"
    else:
        return "Никаких задач сейчас нет"