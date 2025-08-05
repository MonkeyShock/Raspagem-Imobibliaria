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

# --- Configurações Globais ---
START_PAGE = 1
END_PAGE = 100       # ajuste conforme necessidade
PAGE_DELAY = (5, 15)    # intervalo aleatório entre páginas
OUTPUT_DIR = "vivareal_data"

# --- Configurações Específicas para esta Categoria ---
CATEGORY_NAME = "apartamentos_aluguel"
CATEGORY_URL_TEMPLATE = (
    "https://www.vivareal.com.br/aluguel/goias/goiania/apartamento_residencial/"
    "?transacao=aluguel&onde=,Goi%C3%A1s,Goi%C3%A2nia,,,,,city,"  
    "BR%3EGoias%3ENULL%3EGoiania,-16.686891,-49.264794,"
    "&tipos=apartamento_residencial&pagina={}"
)
TIPO_IMOVEL_VAL = 'Apartamento'
FINALIDADE_VAL = 'Aluguel'

# Cria pasta de saída
os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_price(text):
    if not text:
        return None
    cleaned = text.replace("R$", "").replace(".", "").replace(",", ".").strip()
    m = re.search(r"[\d\.]+", cleaned)
    return float(m.group()) if m else None


def parse_area(text):
    if not text:
        return None
    m = re.search(r"(\d+)\s*m", text)
    return int(m.group(1)) if m else None


class VivaRealScraper:
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
        records = []
        for page in range(start, end + 1):
            url = self.url_template.format(page)
            print(f"[{CATEGORY_NAME} - Página {page}] Acessando {url}")
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cy='rp-cardProperty-location-txt']"))
                )
            except TimeoutException:
                print(f"  → Timeout na página {page} para {CATEGORY_NAME}, pulando.")
                continue

            time.sleep(random.uniform(2, 5))
            soup = BeautifulSoup(self.driver.page_source, "lxml")
            cards = soup.select("div.flex.flex-col.grow.min-w-0.content-stretch.border-neutral-90")
            print(f"  → Encontrados {len(cards)} cards em {CATEGORY_NAME} - Página {page}")

            for c in cards:
                a = c.find_parent("a") or c.select_one("a[data-cy='card-link']")
                link = a["href"] if a and a.has_attr("href") else None
                if link and not link.startswith("http"):
                    link = "https://www.vivareal.com.br" + link

                loc_elem = c.select_one("[data-cy='rp-cardProperty-location-txt']")
                location = loc_elem.get_text(strip=True) if loc_elem else None

                street_elem = c.select_one("[data-cy='rp-cardProperty-street-txt']")
                street = street_elem.get_text(strip=True) if street_elem else None

                if street and location:
                    endereco = f"{street}, {location}, Goiânia, Brasil"
                elif location:
                    endereco = f"{location}, Goiânia, Brasil"
                else:
                    endereco = None

                p = c.select_one("div[data-cy='rp-cardProperty-price-txt'] p.font-semibold")
                price = parse_price(p.get_text()) if p else None

                a2 = c.select_one("li[data-cy='rp-cardProperty-propertyArea-txt'] h3")
                area = parse_area(a2.get_text()) if a2 else None

                records.append({
                    "tipo_imovel": TIPO_IMOVEL_VAL,
                    "finalidade": FINALIDADE_VAL,
                    "endereco": endereco,
                    "preco": price,
                    "area_m2": area,
                    "quartos": None,
                    "banheiros": None,
                    "vagas": None,
                    "link": link,
                    "geolocalizacao": None,
                    "fonte": "vivareal"
                })

            delay = random.uniform(*PAGE_DELAY)
            print(f"  → Aguardando {delay:.1f}s após página {page} de {CATEGORY_NAME}")
            time.sleep(delay)

        if self.driver:
            self.driver.quit()
        return records


def save_json(data, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → Salvo {len(data)} registros em {path}")


if __name__ == "__main__":
    json_path = os.path.join(OUTPUT_DIR, f"{CATEGORY_NAME}.json")
    all_items = []  # Initialize list to hold all items (existing + new)

    # Check if the JSON file already exists and load its content
    if os.path.exists(json_path):
        print(f"Arquivo {json_path} já existe. Carregando dados existentes...")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    all_items = loaded_data  # Assign loaded data to all_items
                    print(f"  → {len(all_items)} registros carregados de {json_path}.")
                else:
                    print(f"  → Aviso: O conteúdo de {json_path} não é uma lista JSON válida. Novos dados irão sobrescrever o conteúdo atual se algum item for raspado.")
                    all_items = [] # Reset if not a list, to start fresh or be overwritten
        except json.JSONDecodeError:
            # Handle empty or malformed JSON file
            print(f"  → Erro ao decodificar JSON do arquivo {json_path}. O arquivo pode estar vazio ou corrompido. Novos dados irão sobrescrever o conteúdo atual se algum item for raspado.")
            all_items = [] # Reset if JSON is invalid
        except Exception as e:
            print(f"  → Erro inesperado ao carregar {json_path}: {e}. Novos dados irão sobrescrever o conteúdo atual se algum item for raspado.")
            all_items = [] # Reset on other errors
    else:
        print(f"Arquivo {json_path} não encontrado. Um novo arquivo será criado se itens forem raspados.")

    # Proceed with scraping
    print(f"\n=== Iniciando scraping para: {CATEGORY_NAME} ===")
    scraper = VivaRealScraper(CATEGORY_URL_TEMPLATE)
    new_items = scraper.scrape(START_PAGE, END_PAGE)

    if new_items:
        print(f"  → {len(new_items)} novos itens raspados para {CATEGORY_NAME}.")
        all_items.extend(new_items)  # Add new items to the list

        save_json(all_items, f"{CATEGORY_NAME}.json") # Save the combined list
        print(f"\nScrape para {CATEGORY_NAME} concluído. Total de {len(all_items)} registros agora em {json_path}.")
    elif all_items: # No new items were scraped, but existing items were loaded
        print(f"Nenhum item novo foi raspado para {CATEGORY_NAME}. O arquivo {json_path} com {len(all_items)} registros permanece inalterado (nenhuma nova escrita).")
    else: # No existing items loaded and no new items scraped
        print(f"Nenhum item novo foi raspado para {CATEGORY_NAME} e nenhum item existente foi carregado. Nenhum arquivo será salvo.")