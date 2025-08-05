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
OUTPUT_DIR = "investt_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

CATEGORIES = {
    "casas_compra":        "https://www.investt.com.br/imoveis/a-venda/casa?finalidade=residencial",
    "apartamentos_compra": "https://www.investt.com.br/imoveis/a-venda/apartamento?finalidade=residencial",
    "casas_aluguel":       "https://www.investt.com.br/imoveis/para-alugar/casa?finalidade=residencial",
    "apartamentos_aluguel":"https://www.investt.com.br/imoveis/para-alugar/apartamento?finalidade=residencial",
    "terrenos_compra":     "https://www.investt.com.br/imoveis/a-venda/terreno?finalidade=residencial",
}

PAGE_DELAY = (2, 5)

def parse_money(text):
    if not text:
        return None
    n = text.replace("R$", "").replace(".", "").replace("/mês", "").strip()
    try:
        return float(n.replace(",", "."))
    except:
        return None

def scrape_category(name, url, max_clicks=20):
    # configura o Chrome "não detectável"
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
    time.sleep(2)

    # Clica em "Ver mais" até não haver mais ou atingir max_clicks
    clicks = 0
    while clicks < max_clicks:
        try:
            btn = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-next"))
            )
            driver.execute_script("arguments[0].scrollIntoView()", btn)
            btn.click()
            clicks += 1
            print(f"  → Clicou em Ver mais ({clicks}/{max_clicks})")
            time.sleep(random.uniform(2, 4))
        except TimeoutException:
            print("  → Botão 'Ver mais' não encontrado ou timeout, parando.")
            break

# obtém o HTML
    soup = BeautifulSoup(driver.page_source, "lxml")
    driver.quit()

    # pega todos os <a> de imóvel
    cards = soup.select("a.card-with-buttons.borderHover")
    print(f"  → Encontrados {len(cards)} imóveis em '{name}'")

    results = []  # <— Não esqueça!

    for card in cards:
        header    = card.select_one("div.card-with-buttons__header")
        container = card.select_one("div.card-with-buttons__container-footer")
        if not header or not container:
            print("    • Estrutura inesperada, ignorando cartão.")
            continue

        # código
        codigo_el = header.select_one("p.card-with-buttons__code")
        codigo    = codigo_el.get_text(strip=True) if codigo_el else None

        # tipo e localização
        tipo_el   = card.select_one("p.card-with-buttons__title")
        tipo      = tipo_el.get_text(strip=True) if tipo_el else None

        local_el  = card.select_one("h2.card-with-buttons__heading")
        local     = local_el.get_text(strip=True) if local_el else None

        # detalhes
        itens = card.select("ul > li")
        area    = itens[0].get_text(strip=True) if len(itens)>0 else None
        quartos = itens[1].get_text(strip=True) if len(itens)>1 else None

        # suíte / banheiros / vagas
        suite = banhs = vagas = None
        if len(itens) >= 3 and "Suíte" in itens[2].get_text():
            suite  = itens[2].get_text(strip=True)
            banhs  = itens[3].get_text(strip=True) if len(itens)>3 else None
            vagas  = itens[4].get_text(strip=True) if len(itens)>4 else None
        else:
            banhs  = itens[2].get_text(strip=True) if len(itens)>2 else None
            vagas  = itens[3].get_text(strip=True) if len(itens)>3 else None

        # valores: iteramos os blocos e checamos o título
        venda = locacao = None
        for bloc in container.select("div.card-with-buttons__value-container"):
            title = bloc.select_one("p.card-with-buttons__value-title")
            val   = bloc.select_one("p.card-with-buttons__value")
            if title and val:
                text = title.get_text(strip=True).lower()
                if "venda" in text:
                    venda = parse_money(val.get_text(strip=True))
                elif "locação" in text or "aluguel" in text:
                    locacao = parse_money(val.get_text(strip=True))

        results.append({
            "codigo":    codigo,
            "tipo":      tipo,
            "local":     local,
            "area":      area,
            "quartos":   quartos,
            "suite":     suite,
            "banheiros": banhs,
            "vagas":     vagas,
            "venda":     venda,
            "locacao":   locacao,
        })

    # salva JSON
    path = os.path.join(OUTPUT_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  → Salvo {len(results)} registros em {path}\n")


if __name__ == "__main__":
    for name, url in CATEGORIES.items():
        json_path = os.path.join(OUTPUT_DIR, f"{name}.json")
        if os.path.exists(json_path):
            print(f"Arquivo {json_path} já existe. Pulando...")
            continue
        scrape_category(name, url)
    print("Todos os scrapes concluídos.")