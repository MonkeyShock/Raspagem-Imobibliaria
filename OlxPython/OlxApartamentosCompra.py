# ApartamentosCompra.py
import os
import json
import time
import random
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

# --- Configurações ---
START_PAGE = 1
END_PAGE = 100         # ajuste conforme necessidade
PAGE_DELAY = (3, 8)    # intervalo aleatório entre páginas
OUTPUT_DIR = "olx_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

URL_COMPRA = "https://www.olx.com.br/imoveis/venda/estado-go/grande-goiania-e-anapolis?o={}"

def parse_price(text):
    if not text: return None
    cleaned = text.replace("R$", "").replace(".", "").replace(",", ".").strip()
    m = re.search(r"[\d\.]+", cleaned)
    return float(m.group()) if m else None

def parse_number(text):
    if not text: return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None

def parse_area(text):
    if not text: return None
    m = re.search(r"(\d+)\s*m", text)
    return int(m.group(1)) if m else None

class OlxScraper:
    # (A classe OlxScraper permanece a mesma, sem alterações)
    def __init__(self, url_template):
        self.url_template = url_template
        self.driver = None

    def _init_driver(self):
        opts = uc.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument(f"--user-agent={random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        ])}")
        self.driver = uc.Chrome(options=opts)
        self.driver.implicitly_wait(10)

    def scrape(self, start, end):
        if not self.driver:
            self._init_driver()
        results = []
        # ... (o resto da classe é igual)
        for page in range(start, end + 1):
            url = self.url_template.format(page)
            print(f"[Page {page}] Acessando {url}")
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='adcard-link']"))
                )
            except TimeoutException:
                print(f"  → Timeout na página {page}, pulando.")
                continue
            time.sleep(random.uniform(*PAGE_DELAY))
            soup = BeautifulSoup(self.driver.page_source, "lxml")
            links = soup.select("a[data-testid='adcard-link']")
            print(f"  → Encontrados {len(links)} anúncios na página")
            for link_el in links:
                card = link_el.find_parent(['li','section'])
                if not card: card = link_el
                titulo = link_el.get("title", "").strip()
                link   = link_el.get("href")
                if link and not link.startswith("http"):
                    link = "https://www.olx.com.br" + link
                price_el = card.select_one(".olx-adcard__price, [data-testid='price']")
                preco = parse_price(price_el.get_text()) if price_el else None
                loc_el = card.select_one(".olx-adcard__location, [data-testid='location']")
                localizacao = loc_el.get_text(strip=True) if loc_el else None
                date_el = card.select_one(".olx-adcard__date, [data-testid='date']")
                data = date_el.get_text(strip=True) if date_el else None
                details = card.select(".olx-adcard__detail, [data-testid*='property-card__detail']")
                quartos_str  = details[0].get_text(strip=True) if len(details)>0 else None
                detalhe2_str = details[1].get_text(strip=True) if len(details)>1 else None
                results.append({
                    "titulo": titulo, "link": link, "preco": preco, "localizacao": localizacao,
                    "data": data, "quartos": parse_number(quartos_str), "area_m2": parse_area(detalhe2_str)
                })
        self.driver.quit()
        return results


if __name__ == "__main__":
    print("\n=== Iniciando Scraper de APARTAMENTOS PARA COMPRA ===")
    output_file = os.path.join(OUTPUT_DIR, "apartamentos_compra.json")

    if os.path.exists(output_file):
        print(f"  → Arquivo '{output_file}' já existe. Pulando execução.")
    else:
        scraper = OlxScraper(URL_COMPRA)
        all_listings = scraper.scrape(START_PAGE, END_PAGE)

        # Filtra apenas por apartamentos
        aptos = [listing for listing in all_listings if re.search(r"\bapartamento\b", listing["titulo"], re.I)]

        # Salva o arquivo
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(aptos, f, ensure_ascii=False, indent=2)

        print(f"  → Salvo {len(aptos)} apartamentos em '{output_file}'")

    print("\nProcesso finalizado.")