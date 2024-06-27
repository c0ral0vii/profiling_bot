import asyncio
import time
import aiofiles
from aiogram.types import user
from selenium import webdriver


async def get_source_html(user: int, url: str = 'https://www.google.com/'):
    options = webdriver.FirefoxOptions()
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--incognito')
    options.add_argument('--headless')
    driver = webdriver.Firefox(options=options)

    print('Запустил')

    try:
        driver.get(url=url)
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        await asyncio.sleep(1)

        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')

        await asyncio.sleep(1)
        html_path = f'/map/generate_map/{user}/index.html'

        async with aiofiles.open(html_path, 'w', encoding='utf-8') as f:
            await f.write(driver.page_source)

    except Exception as _ex:
        print(_ex)

    finally:
        driver.close()
        driver.quit()
        return html_path

asyncio.run(get_source_html(user=123))