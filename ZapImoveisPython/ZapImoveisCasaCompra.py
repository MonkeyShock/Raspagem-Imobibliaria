import os
import json
import time
import random
import re

# Importa undetected_chromedriver em vez de selenium padrão
import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

# --- Configurações ---
START_PAGE = 1
END_PAGE   = 100    # ajuste conforme necessidade
PAGE_DELAY = (5, 15)  # intervalo aleatório entre páginas
OUTPUT_DIR = "zapimoveis_data"

# Cria diretório de saída se não existir e mostra o caminho completo
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_PATH = os.path.abspath(OUTPUT_DIR)
print(f"Os dados serão salvos em: {OUTPUT_PATH}")

# --- Parsers auxiliares ---
def parse_price(text):
    """Parses price string into a float."""
    if not text:
        return None
    cleaned = text.replace("R$", "").replace(".", "").replace(",", ".").strip()
    m = re.search(r"(\d+(\.\d+)?)", cleaned)
    try:
        return float(m.group(1)) if m else None
    except (ValueError, AttributeError):
        return None

def parse_area(text):
    """Parses area string (e.g., '120 m²') into an integer."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*m", text)
    try:
        return int(m.group(1)) if m else None
    except (ValueError, AttributeError):
        return None

def parse_integer(text):
    """Parses integer string (e.g., '3') into an integer."""
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    try:
        return int(m.group(1)) if m else None
    except (ValueError, AttributeError):
        return None

# --- Scraper ZapImoveis usando undetected_chromedriver ---
class ZapImoveisScraper:
    def __init__(self, url_template):
        self.url_template = url_template
        self.driver = None
        self._init_driver()

    def _init_driver(self):
        print("Inicializando driver com undetected_chromedriver...")
        opts = uc.ChromeOptions()
        # opts.add_argument("--headless=new") # Mantenha comentado para ver o navegador
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument(f"--user-agent={random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/120.0',
        ])}")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-infobars")
       
        try:
            self.driver = uc.Chrome(options=opts)
            self.driver.implicitly_wait(15)
            print("Driver inicializado com sucesso.")
        except WebDriverException as e:
            print(f"ERRO: Falha ao inicializar o driver: {e}")
            print("Verifique se o Google Chrome está instalado, se a versão é compatível com o undetected_chromedriver, e se não há processos de Chrome/WebDriver pendurados.")
            self.driver = None

    def scrape(self, start, end):
        if not self.driver:
            return []

        records = []
        for page in range(start, end + 1):
            url = self.url_template.format(page)
            print(f"\n[Página {page}] Acessando {url}")
            try:
                self.driver.get(url)
                print("  → Página carregada. Aguardando elementos...")
                WebDriverWait(self.driver, 35).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[data-cy='rp-cardProperty-location-txt'] span")
                    )
                )
                print("  → Elementos da página encontrados.")
                time.sleep(random.uniform(2, 5))
            except TimeoutException:
                print(f"  → Timeout ao carregar a página {page}. Pulando.")
                continue

            try:
                soup = BeautifulSoup(self.driver.page_source, "lxml")
                cards = soup.select("div.flex.flex-col.grow.min-w-0.content-stretch.border-neutral-90")
                print(f"  → {len(cards)} cards encontrados.")

                if not cards and page == start:
                    print("  → Sem resultados na primeira página. Verifique seletores, URL ou bloqueio.")
                    break

                for c in cards:
                    a = c.find_parent("a") or c.select_one("a[data-cy='card-link']")
                    link = a["href"] if a and a.has_attr("href") else None
                    if link and not link.startswith("http"):
                        link = "https://www.zapimoveis.com.br" + link

                    loc_elem    = c.select_one("[data-cy='rp-cardProperty-location-txt'] span")
                    street_elem = c.select_one("[data-cy='rp-cardProperty-street-txt']")
                    location    = loc_elem.get_text(strip=True) if loc_elem else None
                    street_txt  = street_elem.get_text(strip=True) if street_elem else None

                    if street_txt and location:
                        endereco = f"{street_txt}, {location}, Goiânia, Brasil"
                    elif location:
                        endereco = f"{location}, Goiânia, Brasil"
                    else:
                        endereco = None

                    price_elem = c.select_one("div[data-cy='rp-cardProperty-price-txt'] p.font-semibold")
                    area_elem  = c.select_one("li[data-cy='rp-cardProperty-propertyArea-txt'] h3")
                    bed_elem   = c.select_one("li[data-cy='rp-cardProperty-bedroomQuantity-txt'] h3")
                    bath_elem  = c.select_one("li[data-cy='rp-cardProperty-bathroomQuantity-txt'] h3")
                    park_elem  = c.select_one("li[data-cy='rp-cardProperty-parkingSpacesQuantity-txt'] h3")

                    records.append({
                        "tipo_imovel": None,
                        "finalidade": None,
                        "endereco": endereco,
                        "preco": parse_price(price_elem.get_text()) if price_elem else None,
                        "area_m2": parse_area(area_elem.get_text()) if area_elem else None,
                        "quartos": parse_integer(bed_elem.get_text()) if bed_elem else None,
                        "banheiros": parse_integer(bath_elem.get_text()) if bath_elem else None,
                        "vagas": parse_integer(park_elem.get_text()) if park_elem else None,
                        "link": link,
                        "geolocalizacao": None,
                        "fonte": "zapimoveis"
                    })
            except Exception as page_e:
                print(f"  → Erro inesperado ao processar o HTML da página {page}: {page_e}")
                continue
            delay = random.uniform(*PAGE_DELAY)
            print(f"  → Aguardando {delay:.1f}s...")
            time.sleep(delay)

        if self.driver:
             print("Fechando driver...")
             try:
                self.driver.quit()
                print("Driver fechado.")
             except Exception as e:
                print(f"Erro ao fechar driver: {e}")
             self.driver = None
        return records

# --- Função para salvar JSON ---
def save_json(data, filename_base):
    if not filename_base.lower().endswith('.json'):
        filename = filename_base + '.json'
    else:
        filename = filename_base
    path = os.path.join(OUTPUT_DIR, filename)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  → Salvo {len(data)} registros em {path}")
    except IOError as e:
        print(f"  → ERRO ao salvar o arquivo {path}: {e}")

# --- Execução Principal ---
if __name__ == '__main__':
    # --- DEFINIÇÕES ESPECÍFICAS DO SEU SCRIPT (substitua conforme necessário) ---
    # Coloque o nome da categoria para este script (ex: "casas_compra")
    SCRIPT_CATEGORY_NAME = "casas_compra" 
    # Coloque o template da URL para este script, com "{}" para o número da página
    SCRIPT_URL_TEMPLATE = (
        "https://www.zapimoveis.com.br/venda/casas/go+goiania/"
        "?transacao=venda&onde=,Goi%C3%A1s,Goi%C3%A2nia,,,,,city,"
        "BR%3EGoias%3ENULL%3EGoiania,-16.686891,-49.264794,"
        "&tipos=casa_residencial&pagina={}"
    )
    # -------------------------------------------------------------------------

    json_filename = f"{SCRIPT_CATEGORY_NAME}.json"
    json_file_path = os.path.join(OUTPUT_DIR, json_filename)
    
    existing_records = []
    # Tenta carregar dados existentes se o arquivo JSON já existir
    if os.path.exists(json_file_path):
        print(f"\n--- Arquivo '{json_filename}' encontrado em '{OUTPUT_DIR}'. Tentando carregar dados existentes...")
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    existing_records = loaded_data
                    print(f"  → {len(existing_records)} registros existentes carregados de '{json_filename}'.")
                else:
                    print(f"  → AVISO: O conteúdo de '{json_filename}' não é uma lista JSON. O arquivo será sobrescrito se novos dados forem coletados (os dados antigos não-lista serão perdidos).")
                    # Opcional: fazer backup do arquivo corrompido/inválido antes de prosseguir
                    # import shutil
                    # shutil.copyfile(json_file_path, json_file_path + f".invalid_backup_{int(time.time())}")
        except json.JSONDecodeError:
            print(f"  → AVISO: O arquivo '{json_filename}' contém JSON inválido. Será sobrescrito se novos dados forem coletados (os dados antigos inválidos serão perdidos).")
        except IOError as e:
            print(f"  → ERRO ao ler o arquivo '{json_filename}': {e}. O arquivo pode ser sobrescrito se novos dados forem coletados.")
    else:
        print(f"\n--- Arquivo '{json_filename}' não encontrado em '{OUTPUT_DIR}'. Um novo arquivo será criado se dados forem coletados.")

    # Inicializa o scraper e coleta novos dados
    print(f"\n=== Iniciando Scraping para: {SCRIPT_CATEGORY_NAME} (Páginas {START_PAGE} a {END_PAGE}) ===")
    scraper = ZapImoveisScraper(SCRIPT_URL_TEMPLATE) 
    
    newly_scraped_items = []
    novos_registros_coletados_nesta_execucao = 0

    if scraper.driver:
        newly_scraped_items = scraper.scrape(START_PAGE, END_PAGE)
        novos_registros_coletados_nesta_execucao = len(newly_scraped_items)

        # Processa os itens recém-coletados
        for rec in newly_scraped_items:
            tipo_part, finalidade_part = SCRIPT_CATEGORY_NAME.split('_')
            
            if 'apartamento' in tipo_part:
                rec['tipo_imovel'] = 'Apartamento'
            elif 'casa' in tipo_part: 
                rec['tipo_imovel'] = 'Casa'
            elif 'lote' in tipo_part:
                rec['tipo_imovel'] = 'Lote'
            else:
                rec['tipo_imovel'] = tipo_part.capitalize() 

            if 'aluguel' in finalidade_part:
                rec['finalidade']  = 'Aluguel'
            elif 'compra' in finalidade_part:
                rec['finalidade']  = 'Venda'
            else:
                rec['finalidade'] = finalidade_part.capitalize()
        
        if novos_registros_coletados_nesta_execucao > 0:
            print(f"  → {novos_registros_coletados_nesta_execucao} novos registros coletados para '{SCRIPT_CATEGORY_NAME}'.")
        else:
            print(f"  → Nenhum novo registro foi coletado para '{SCRIPT_CATEGORY_NAME}' nesta execução.")

    else: # scraper.driver é None
        print(f"Scraping para '{SCRIPT_CATEGORY_NAME}' não pôde ser realizado (falha na inicialização do driver).")

    # Combina registros existentes (se eram uma lista) com os recém-coletados
    # Se existing_records não for uma lista (devido a erro de carga ou arquivo malformado), começamos do zero com os novos.
    if not isinstance(existing_records, list):
        print(f"  AVISO: Dados existentes de '{json_filename}' não eram uma lista ou não puderam ser carregados corretamente; apenas os novos dados (se houver) serão salvos.")
        final_records_to_save = newly_scraped_items
    else:
        final_records_to_save = existing_records + newly_scraped_items

    # Salva a lista combinada de registros
    # (Isso acontecerá mesmo se o scraping não coletar novos itens, mas havia itens existentes)
    if final_records_to_save:
        print(f"\n--- Salvando dados combinados para '{SCRIPT_CATEGORY_NAME}' ---")
        save_json(final_records_to_save, SCRIPT_CATEGORY_NAME) # Passa o nome base para save_json
        print(f"  Total de {len(final_records_to_save)} registros agora constam em '{json_file_path}'.")
        if novos_registros_coletados_nesta_execucao > 0 and scraper.driver : # Informa sobre os novos adicionados
             print(f"  ({novos_registros_coletados_nesta_execucao} registros foram recém-coletados e adicionados/atualizados).")
    elif not newly_scraped_items and not existing_records:
        # Se não havia nada existente e nada foi raspado.
        print(f"\n--- Nenhum dado (existente ou novo) para salvar para '{SCRIPT_CATEGORY_NAME}'. Arquivo não modificado ou não criado.")
    
    # Mensagem final do processo
    print(f"\n=== Processo para '{SCRIPT_CATEGORY_NAME}' Concluído ===")
    if os.path.exists(json_file_path):
        print(f"  Arquivo '{json_file_path}' atualizado ou mantido.")
    else:
        print(f"  Arquivo '{json_file_path}' não foi criado (nenhum dado para salvar).")
    print(f"  Verifique o diretório de saída: {OUTPUT_PATH}")