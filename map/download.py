import requests
import os
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.action_chains import ActionChains
from selenium import webdriver


def get_source_html(url: str, user: int):

    driver = webdriver.Chrome()
    options = webdriver.ChromeOptions()
    options.add_argument('--ignore-certificate-errors')

    try:
        driver.get(url=url)
        time.sleep(1)
        
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(1)
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')

        time.sleep(1)
        html_path = f'C:/Users/Administrator/Desktop/profiling_bot-main/map/generate_map/{user}/index.html'

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)

    except Exception as _ex:
        print(_ex)

    finally:
        driver.close()
        driver.quit()
        return html_path
