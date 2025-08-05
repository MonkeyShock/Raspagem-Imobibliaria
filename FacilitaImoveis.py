import os
import json
import time
import random
import re
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup

# --- Configurações ---
OUTPUT_DIR = "facilitaimoveis_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

CATEGORIES = {
    "casas_venda":    "https://www.facilitaimoveis.com/imovel/venda/casa",
    "apartamentos_venda": "https://www.facilitaimoveis.com/imovel/venda/apartamento",
    "apartamentos_locacao": "https://www.facilitaimoveis.com/imovel/locacao/apartamento",
    "casas_locacao":   "https://www.facilitaimoveis.com/imovel/locacao/casa",
    "terrenos_venda":  "https://www.facilitaimoveis.com/imovel/venda/lote",
}

PAGE_DELAY = (2, 5)

def parse_money(text):
    """Converte 'R$ 2.200' ou 'R$ 440.000' em float."""
    if not text:
        return None
    cleaned = text.replace("R$", "").replace(".", "").strip()
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except:
        return None

def parse_area(text):
    """Converte '248,96 m²' em float (248.96)."""
    if not text:
        return None
    m = re.search(r"([\d,]+)\s*m", text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None

def parse_int(text):
    """Extrai inteiro de '3 Dormitório', '2 Banheiros', etc."""
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None

def scrape_category(name, url):
    opts = uc.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={random.choice([
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
    ])}")
    driver = uc.Chrome(options=opts)
    driver.implicitly_wait(10)

    print(f"[{name}] Acessando {url}")
    driver.get(url)
    time.sleep(2 + random.random()*3)

    # opcional: implementar paginação clicando em "Próxima" se existir
    # while True:
    #     try:
    #         btn = driver.find_element(By.CSS_SELECTOR, "li.next a")
    #         btn.click()
    #         time.sleep(random.uniform(*PAGE_DELAY))
    #     except:
    #         break

    soup = BeautifulSoup(driver.page_source, "lxml")
    driver.quit()

    cards = soup.select("div.imovelcard__infocontainer")
    print(f"  → Encontrados {len(cards)} imóveis em '{name}'")

    results = []
    for card in cards:
        try:
            # tipo de negócio (Venda/Locação)
            negocio = card.select_one("h2.imovelcard__info__tag")
            negocio = negocio.get_text(strip=True) if negocio else None

            # endereço
            endereco = card.select_one("h2.imovelcard__info__local")
            endereco = endereco.get_text(strip=True) if endereco else None

            # referência e tipo (Casa/Apartamento)
            ref_tipo = card.select_one("p.imovelcard__info__ref")
            if ref_tipo:
                m = re.search(r"Ref:\s*\d+\s*-\s*(\w+)", ref_tipo.get_text())
                tipo_imovel = m.group(1) if m else None
            else:
                tipo_imovel = None

            # características
            feats = card.select("div.imovelcard__info__feature p")
            dormitorios = parse_int(feats[0].get_text()) if len(feats) > 0 else None
            banheiros  = parse_int(feats[1].get_text()) if len(feats) > 1 else None
            vagas      = parse_int(feats[2].get_text()) if len(feats) > 2 else None
            area       = parse_area(feats[3].get_text()) if len(feats) > 3 else None

            # preço
            val_p = card.select_one("p.imovelcard__valor__valor")
            preco = parse_money(val_p.get_text()) if val_p else None

            results.append({
                "negocio": negocio,           # "Venda" ou "Locação"
                "tipo": tipo_imovel,         # "Casa" ou "Apartamento"
                "endereco": endereco,        # endereço completo
                "dormitorios": dormitorios,
                "banheiros": banheiros,
                "vagas": vagas,
                "area_m2": area,
                "preco": preco
            })
        except Exception as e:
            print(f"  → Erro ao processar card: {e}")
            continue

    # salvar JSON
    path = os.path.join(OUTPUT_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  → Salvo {len(results)} registros em {path}")

if __name__ == "__main__":
    for name, url in CATEGORIES.items():
        json_path = os.path.join(OUTPUT_DIR, f"{name}.json")
        if os.path.exists(json_path):
            print(f"Arquivo {json_path} já existe. Pulando...")
            continue
        scrape_category(name, url)
    print("\nTodos os scrapes concluídos. Veja a pasta 'facilitaimoveis_data/'")