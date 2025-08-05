# CasasCompra.py
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
END_PAGE = 10          # ajuste conforme necessidade (menor para testes)
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

# ===== BLOCO MODIFICADO =====
if __name__ == "__main__":
    print("\n=== Iniciando Scraper de CASAS PARA COMPRA (Modo: Adicionar/Atualizar) ===")
    output_file = os.path.join(OUTPUT_DIR, "casas_compra.json")

    # 1. Tenta carregar dados existentes do arquivo JSON
    existing_data = []
    existing_links = set()
    if os.path.exists(output_file):
        print(f"  → Arquivo '{output_file}' encontrado. Lendo dados existentes...")
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                if isinstance(existing_data, list):
                    # Cria um conjunto de links para verificação rápida de duplicados
                    existing_links = {item.get('link') for item in existing_data if item.get('link')}
                    print(f"  → {len(existing_data)} anúncios carregados.")
                else:
                    print("  → Aviso: O arquivo não continha uma lista válida. Começando do zero.")
                    existing_data = []
        except (json.JSONDecodeError, IOError) as e:
            print(f"  → Erro ao ler o arquivo: {e}. Começando do zero.")
            existing_data = []

    # 2. Executa o scraper para buscar todos os anúncios da categoria
    scraper = OlxScraper(URL_COMPRA)
    all_new_listings = scraper.scrape(START_PAGE, END_PAGE)

    # 3. Filtra os anúncios novos por 'casa'
    newly_found_casas = [
        listing for listing in all_new_listings
        if re.search(r"\bcasa\b", listing["titulo"], re.I)
    ]
    print(f"\n  → Scraper encontrou {len(newly_found_casas)} anúncios de casas.")

    # 4. Adiciona apenas os anúncios que não são duplicados
    unique_new_items = []
    for item in newly_found_casas:
        if item.get("link") not in existing_links:
            unique_new_items.append(item)
    
    print(f"  → Adicionando {len(unique_new_items)} novos anúncios únicos.")

    # 5. Combina a lista existente com os novos itens e salva no arquivo
    final_data = existing_data + unique_new_items
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

    print(f"  → Salvo! O arquivo '{output_file}' agora contém {len(final_data)} anúncios no total.")
    print("\nProcesso finalizado.")