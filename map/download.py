import asyncio
import logging
from pathlib import Path

import aiofiles
from playwright.async_api import async_playwright


async def get_source_html(user: int, url: str = "https://www.google.com/"):
    html_path = f"./map/generate_map/{user}/index.html"

    try:
        # Создаем директорию, если ее нет
        Path(f"./map/generate_map/{user}").mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            logging.info("Запускаем браузер Firefox")
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(
                ignore_https_errors=True,
                viewport={'width': 1920, 'height': 1080}  # Устанавливаем размер окна
            )
            page = await context.new_page()

            logging.info(f"Открываем страницу: {url}")
            await page.goto(url, wait_until="networkidle", timeout=60000)

            # Прокручиваем страницу несколько раз
            for _ in range(15):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

            # Получаем HTML так же, как в Selenium
            html_content = await page.content()

            # Сохраняем с тем же форматированием
            async with aiofiles.open(html_path, "w", encoding="utf-8") as f:
                await f.write(html_content)

            logging.info(f"Страница успешно сохранена в {html_path}")

            return html_path

    except Exception as e:
        logging.error(f"Ошибка при получении страницы: {str(e)}")
        # Удаляем файл, если он был частично создан
        if Path(html_path).exists():
            Path(html_path).unlink()
        return None
    finally:
        try:
            await browser.close()
        except:
            pass
