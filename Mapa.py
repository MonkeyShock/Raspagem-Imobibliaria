# -*- coding: utf-8 -*-
import os
import json
import time
import logging
import folium
from folium.plugins import MarkerCluster
import tkinter as tk
# Removido filedialog pois não será mais usado para seleção interativa
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import re
import unicodedata

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Suas constantes e funções auxiliares (normalize_string, esta_na_regiao, etc.) ---
REGIAO_GOIANIA = {
    'lat_min': -17.2, 'lat_max': -15.8,
    'lon_min': -49.8, 'lon_max': -48.5
}
CIDADES_GRANDE_GOIANIA = [
    'goiania', 'aparecida de goiania', 'senador canedo', 'trindade',
    'goianira', 'abadia de goias', 'aragoiania', 'bela vista de goias',
    'bonfinopolis', 'brazabrantes', 'caldazinha', 'caturai', 'guapo',
    'hidrolandia', 'inhumas', 'neropolis', 'nova veneza', 'santo antonio de goias',
    'terezopolis de goias', 'anapolis'
]
CACHE_FILE = "geocode_cache.json"
BATCH_SIZE = 10
BATCH_PAUSE = 3

OUTPUT_DIR_NAME = "mapas_imoveis_gerados"
JSON_FILES_TO_PROCESS = [
    "resultados_terreno_venda.json",
    "resultados_apartamento_venda.json",
    "resultados_casa_venda.json",
    "resultados_apartamento_aluguel.json",
    "resultados_casa_aluguel.json"
]

def normalize_string(text):
    if not isinstance(text, str): return ""
    nfkd_form = unicodedata.normalize('NFD', text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)]).lower().strip()

def esta_na_regiao(lat, lon, regiao):
    try:
        lat, lon = float(lat), float(lon)
        return (regiao['lat_min'] <= lat <= regiao['lat_max'] and
                regiao['lon_min'] <= lon <= regiao['lon_max'])
    except (ValueError, TypeError): return False

def verifica_cidade_grande_goiania(endereco):
    endereco_normalizado = normalize_string(endereco)
    return any(normalize_string(cidade) in endereco_normalizado for cidade in CIDADES_GRANDE_GOIANIA)

def limpar_endereco_para_busca(address):
    if not isinstance(address, str): return ""
    addr_lower = normalize_string(address)
    termos_remover = [
        "à venda", "para venda", "terreno à venda", "casa à venda",
        "apartamento à venda", "imovel a venda", "venda", "comprar", "alugar", "aluguel",
        "residencial", "setor", "bairro", "vila", "jardim",
        "condominio", "edificio", "alameda", "quadra", "lote",
        "rua", "avenida", "av.", "goiania", "goias", "go", "brasil",
        "aparecida de goiania", "senador canedo", "trindade",
        ",", "-", ".", "(", ")"
    ]
    for term in termos_remover: addr_lower = addr_lower.replace(term, " ")
    return re.sub(r'\s+', ' ', addr_lower).strip()

def construir_query_busca(address):
    if not isinstance(address, str): return "Goiânia, GO, Brasil"
    addr_norm = normalize_string(address)
    query = address
    contem_cidade = any(city in addr_norm for city in CIDADES_GRANDE_GOIANIA)
    contem_estado = "go" in addr_norm or "goias" in addr_norm

    if not contem_cidade and not contem_estado: query = f"{address}, Goiânia, GO, Brasil"
    elif contem_cidade and not contem_estado: query = f"{address}, GO, Brasil"
    elif not contem_cidade and contem_estado and 'goiania' not in addr_norm: query = f"{address}, Goiânia"
    if "brasil" not in addr_norm: query = f"{query}, Brasil"
    query = re.sub(r'\s+', ' ', query).strip().replace(" ,", ",").replace(",,", ",")
    logger.debug(f"Query construída para '{address}': '{query}'")
    return query

def inicializar_driver():
    logger.info("Inicializando o WebDriver do Chrome...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument('--log-level=3')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logger.info("WebDriver inicializado com webdriver-manager.")
        return driver
    except Exception as e_manager:
        logger.warning(f"Falha ao usar webdriver-manager ({e_manager}). Tentando caminho manual...")
        try:
            driver_path = "./chromedriver"
            if not os.path.exists(driver_path) and os.name == 'nt':
                 driver_path += ".exe"
            if os.path.exists(driver_path):
                 service = Service(executable_path=driver_path)
            else:
                 logger.info("Tentando usar chromedriver do PATH do sistema.")
                 service = Service()
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info(f"WebDriver inicializado. Executable: {service.path}")
            return driver
        except Exception as e_manual:
            logger.error(f"Falha ao inicializar o WebDriver manualmente ou pelo PATH: {e_manual}")
            raise RuntimeError("Não foi possível inicializar o WebDriver.") from e_manual

def selenium_geocode(address, driver):
    if not address or not isinstance(address, str):
        logger.warning("Endereço inválido para geocodificação.")
        return None, None, address
    if not driver:
        logger.warning("Driver do Selenium não fornecido. Geocodificação online pulada.")
        return None, None, address
    search_query = construir_query_busca(address)
    logger.info(f"Tentando geocodificar: '{search_query}'")
    try:
        driver.get("https://maps.google.com/") # URL mais comum e estável
        search_box = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "searchboxinput"))
        )
        search_box.clear()
        search_box.send_keys(search_query)
        search_box.send_keys(Keys.ENTER)
        WebDriverWait(driver, 10).until(EC.url_contains("@"))
        current_url = driver.current_url
        logger.debug(f"URL após busca: {current_url}")
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+),(\d+)', current_url)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            logger.info(f"Coordenadas extraídas da URL: ({lat}, {lon})")
            return lat, lon, search_query
        else:
            logger.warning(f"Não foi possível extrair coordenadas da URL para '{search_query}'. URL: {current_url}")
            return None, None, search_query
    except (TimeoutException, NoSuchElementException) as e:
        logger.error(f"Erro de Selenium (Timeout/Não encontrado) ao geocodificar '{search_query}': {e}")
        return None, None, search_query
    except Exception as e:
        logger.error(f"Erro inesperado durante geocodificação de '{search_query}': {str(e)}")
        return None, None, search_query


def carregar_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f: cache = json.load(f)
            logger.info(f"Cache carregado de '{CACHE_FILE}' com {len(cache)} entradas.")
            return cache
        except Exception as e: logger.error(f"Erro ao carregar cache: {e}")
    logger.info(f"Arquivo de cache '{CACHE_FILE}' não encontrado ou erro. Criando novo cache.")
    return {}

def salvar_cache(cache):
    if not isinstance(cache, dict):
        logger.error("Tentativa de salvar cache que não é um dicionário.")
        return
    logger.debug(f"Salvando cache com {len(cache)} entradas.")
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"Cache salvo em '{CACHE_FILE}' com {len(cache)} entradas.")
    except Exception as e: logger.error(f"Erro ao salvar cache: {e}")

def verificar_cache(endereco, cache):
    if not endereco or not isinstance(endereco, str) or not cache: return False, None, None
    endereco_normalizado = normalize_string(endereco)
    endereco_limpo = limpar_endereco_para_busca(endereco)
    for key in [endereco_normalizado, endereco_limpo, endereco]:
        if key in cache:
            coords = cache[key]
            try:
                lat, lon = float(coords['lat']), float(coords['lon'])
                logger.info(f"Cache hit para '{key}': ({lat}, {lon})")
                return True, lat, lon
            except (ValueError, TypeError, KeyError): continue
    return False, None, None

def atualizar_cache(endereco, lat, lon, cache):
    if not endereco or lat is None or lon is None or not isinstance(cache, dict): return
    try: lat_float, lon_float = float(lat), float(lon)
    except (ValueError, TypeError): return
    endereco_normalizado = normalize_string(endereco)
    cache[endereco_normalizado] = {"lat": lat_float, "lon": lon_float}

def ajustar_nomes_campos(item_dict):
    if not isinstance(item_dict, dict): return {}
    item = item_dict.copy()
    if 'preco' in item and 'valor' not in item: item['valor'] = item['preco']
    if 'quartos' in item and 'num_quartos' not in item: item['num_quartos'] = item['quartos']
    if 'banheiros' in item and 'num_banheiros' not in item: item['num_banheiros'] = item['banheiros']
    if 'titulo' not in item and 'titulo_limpo' not in item:
        tipo = item.get('tipo_imovel', 'Imóvel')
        finalidade = item.get('finalidade', '')
        item['titulo'] = f"{tipo} {finalidade}" if finalidade else tipo
    item.setdefault('titulo', item.get('endereco', 'Sem Título'))
    return item

def usar_coordenadas_existentes(item):
    geo = item.get('geolocalizacao')
    lat, lon = None, None
    if isinstance(geo, dict):
        lat = geo.get('latitude')
        lon = geo.get('longitude')
    if lat is None: lat = item.get('latitude')
    if lon is None: lon = item.get('longitude')
    if lat is not None and lon is not None:
        try:
            lat_f, lon_f = float(lat), float(lon)
            logger.debug(f"Coordenadas existentes encontradas: ({lat_f}, {lon_f})")
            return True, lat_f, lon_f
        except (ValueError, TypeError):
            logger.warning(f"Coordenadas existentes inválidas: lat='{lat}', lon='{lon}'. Ignorando.")
    return False, None, None

def coordenadas_centro_goiania(): return -16.6869, -49.2648

def formatar_valor(valor):
    if valor is None or valor != valor: return "N/A" # Trata None e NaN
    try:
        val = float(valor)
        if val >= 1_000_000: return f"R$ {val/1_000_000:.1f} M".replace('.', ',') # Mudança para M
        elif val >= 1_000:
            decimais = 1 if (val % 1000) != 0 and val > 1000 else 0
            return f"R$ {val/1000:.{decimais}f}k".replace('.', ',')
        else:
            return f"R$ {val:.2f}".replace('.', ',')
    except (ValueError, TypeError): return str(valor)


def extrair_bairro(item):
    campos_tentar = ['bairro', 'localizacao', 'logradouro', 'endereco']
    cidades_remover = ['goiania', 'aparecida de goiania', 'goias', 'go', 'brasil', 'anapolis']
    for campo in campos_tentar:
        valor_campo = item.get(campo)
        if valor_campo and isinstance(valor_campo, str):
            partes = [p.strip() for p in valor_campo.split(',') if p.strip()]
            if not partes: continue
            for parte_cand in partes:
                norm_parte = normalize_string(parte_cand)
                if norm_parte and norm_parte not in cidades_remover and not parte_cand.isdigit() and len(parte_cand) > 2:
                    return parte_cand.title()
            if len(partes) == 1 and normalize_string(partes[0]) not in cidades_remover: return partes[0].title()
            if len(partes) > 1:
                 if normalize_string(partes[-1]) in cidades_remover and normalize_string(partes[-2]) not in cidades_remover:
                     return partes[-2].title()
                 if normalize_string(partes[0]) not in cidades_remover:
                     return partes[0].title()
    return "Sem Bairro Definido"

def criar_legenda_html(faixas_preco_config):
    items_legenda = []
    for nome_faixa, info in faixas_preco_config.items():
        cor = info.get('color', 'gray')
        min_val, max_val = info.get('min'), info.get('max')
        if nome_faixa == 'Sem Preço': texto_faixa = "Sem Preço"
        elif min_val is None: texto_faixa = f"Menor que {formatar_valor(max_val)}"
        elif max_val == float('inf'): texto_faixa = f"Maior que {formatar_valor(min_val)}"
        else: texto_faixa = f"{formatar_valor(min_val)} - {formatar_valor(max_val)}"
        items_legenda.append(
            f'<i style="background:{cor}; width: 15px; height: 15px; border-radius: 50%; margin-right: 5px; display: inline-block; vertical-align: middle;"></i> {texto_faixa}<br>'
        )
    return f"""
     <div style="position: fixed; bottom: 20px; right: 20px; width: auto; max-width: 220px; background-color: rgba(255, 255, 255, 0.9);
                 z-index:9999; font-size:12px; border-radius: 5px; padding: 10px; border: 1px solid #ccc; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);">
     <h4 style="margin-top:0; margin-bottom: 5px; text-align: center; font-weight: bold;">Legenda de Preços</h4>
     {''.join(items_legenda)}</div>"""

def criar_mapa_centralizado(lat=-16.6869, lon=-49.2648, zoom=12):
    logger.info(f"Criando mapa Folium centralizado em ({lat}, {lon}) com zoom {zoom}.")
    m = folium.Map(location=[lat, lon], zoom_start=zoom, tiles=None)
    folium.TileLayer('openstreetmap', name='OpenStreetMap').add_to(m)
    folium.TileLayer('CartoDB positron', name='Padrão Claro').add_to(m)
    folium.TileLayer('CartoDB dark_matter', name='Padrão Escuro').add_to(m)
    return m

# NOVA FUNÇÃO PARA CRIAR A BARRA DE FILTRO E O JAVASCRIPT CORRESPONDENTE
def criar_barra_filtro_html_e_js(faixas_preco_config, todos_imoveis_data_json_str, map_var_name_str, marker_clusters_var_names_map_json_str):
    style_css = """
    #filter-sidebar {
        position: fixed;
        top: 20px; /* Ajustado para mais perto do topo */
        left: 10px;
        width: 260px;
        background-color: rgba(255, 255, 255, 0.97); /* Levemente mais opaco */
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15); /* Sombra sutil */
        z-index: 1000;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; /* Fonte mais moderna */
        font-size: 13px;
        max-height: calc(100vh - 40px);
        overflow-y: auto;
        display: flex;
        flex-direction: column;
    }
    #filter-sidebar h4 { 
        margin-top: 0; 
        margin-bottom:15px; 
        color: #1a73e8; /* Azul Google */
        text-align:center; 
        font-size: 1.2em; /* Um pouco maior */
        font-weight: 600;
    }
    #filter-sidebar .price-range-inputs, #filter-sidebar .price-checkboxes, #filter-sidebar .filter-buttons { margin-bottom: 15px; }
    #filter-sidebar label { display: block; margin-bottom: 5px; color: #333; font-weight: 500;}
    #filter-sidebar .checkbox-label { font-weight: normal; margin-bottom: 8px; display:flex; align-items:center; }
    #filter-sidebar input[type='checkbox'] { margin-right: 8px; vertical-align: middle; accent-color: #1a73e8; } /* Cor do checkbox */
    #filter-sidebar input[type='number'] { 
        padding: 9px; /* Um pouco mais de padding */
        border: 1px solid #ccc; 
        border-radius: 4px; 
        width: calc(100% - 20px); 
        margin-bottom: 10px;
        box-sizing: border-box;
        font-size: 0.95em;
    }
    #filter-sidebar input[type='number']:focus { border-color: #1a73e8; box-shadow: 0 0 0 2px rgba(26,115,232,0.2); outline:none;}
    #filter-sidebar .price-input-group { display: flex; gap: 10px; }
    #filter-sidebar .price-input-group div { flex: 1; }
    #filter-sidebar button { 
        padding: 10px 15px; 
        border: none; 
        border-radius: 5px; /* Bordas levemente mais arredondadas */
        cursor: pointer; 
        font-weight: 600; /* Mais negrito */
        width: 100%;
        box-sizing: border-box;
        margin-top: 5px;
        transition: background-color 0.2s ease; /* Transição suave */
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px; /* Espaço entre ícone e texto */
    }
    #filter-sidebar #applyFiltersButton { background-color: #1a73e8; color: white; } /* Azul Google */
    #filter-sidebar #applyFiltersButton:hover { background-color: #1765c2; } /* Azul mais escuro no hover */
    #filter-sidebar #clearFiltersButton { background-color: #6c757d; color: white; margin-top:8px; }
    #filter-sidebar #clearFiltersButton:hover { background-color: #5a6268; }
    #filter-sidebar .scrollable-content {
        flex-grow: 1;
        overflow-y: auto;
        padding-right: 5px; /* Espaço para a barra de rolagem não sobrepor conteúdo */
    }
    /* Estilo para a barra de rolagem */
    #filter-sidebar ::-webkit-scrollbar { width: 6px; }
    #filter-sidebar ::-webkit-scrollbar-track { background: #f1f1f1; border-radius: 3px; }
    #filter-sidebar ::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
    #filter-sidebar ::-webkit-scrollbar-thumb:hover { background: #aaa; }
    """

    faixas_html = "<div class='price-checkboxes'><label>Ou selecione uma faixa:</label>"
    # Iterar sobre faixas_preco_config para criar checkboxes
    # Garantir que 'Sem Preço' não crie um checkbox problemático ou dar a ele um tratamento especial
    idx_checkbox = 0
    for nome_faixa, info in faixas_preco_config.items():
        if nome_faixa == 'Sem Preço': # Não incluir 'Sem Preço' como checkbox de filtro ativo
            continue
        # Usar valores numéricos para min/max, convertendo float('inf') para uma string que o JS possa tratar como tal ou um número muito grande
        min_val_attr = info['min'] if info['min'] is not None else '0'
        max_val_attr = info['max'] if info['max'] != float('inf') else 'Infinity'

        faixas_html += f"""
        <label class='checkbox-label'>
            <input type='checkbox' name='price_range' value='{idx_checkbox}' data-min='{min_val_attr}' data-max='{max_val_attr}'>
            {nome_faixa.replace("R$ ", "").replace("Mi", "M")} 
        </label>
        """
        idx_checkbox +=1
    faixas_html += "</div>"

    filter_bar_html = f"""
    <div id="filter-sidebar">
        <h4><i class="fas fa-filter"></i> Filtros de Imóveis</h4>
        <div class="scrollable-content">
            <div class="price-range-inputs">
                <label for="minPriceInput">Preço Mínimo (R$):</label>
                <input type="number" id="minPriceInput" placeholder="Ex: 50000">
                <label for="maxPriceInput">Preço Máximo (R$):</label>
                <input type="number" id="maxPriceInput" placeholder="Ex: 300000">
            </div>
            {faixas_html}
        </div>
        <div class="filter-buttons">
            <button id="applyFiltersButton"><i class="fas fa-check"></i> Aplicar</button>
            <button id="clearFiltersButton"><i class="fas fa-undo"></i> Limpar</button>
        </div>
    </div>
    """

    # JavaScript code
    javascript_code = f"""
    <script>
        const allImoveisData = {todos_imoveis_data_json_str};
        const markerClusterGroupObjects = {{}}; 
        const mapInstance = window['{map_var_name_str}']; 
        const markerClustersVarNames = {marker_clusters_var_names_map_json_str}; 

        function initializeMarkerClusterGroups() {{
            for (const bairro_norm in markerClustersVarNames) {{
                const mcVarName = markerClustersVarNames[bairro_norm];
                if (window[mcVarName]) {{
                    markerClusterGroupObjects[bairro_norm] = window[mcVarName];
                }} else {{
                    // console.warn(`Filter: MarkerClusterGroup para '${{bairro_norm}}' (var: ${{mcVarName}}) não encontrado no window.`);
                }}
            }}
            // console.log("Filter: MarkerClusterGroups JS objects inicializados:", markerClusterGroupObjects);
        }}
        
        function formatPriceForJS(valueStr) {{
            const value = parseFloat(valueStr);
            if (isNaN(value)) return "N/A";
            if (value >= 1000000) return `R$ ${{(value/1000000).toFixed(1).replace('.',',')}} M`;
            if (value >= 1000) {{
                const decimals = (value % 1000 !== 0 && value > 1000) ? 0 : 0; // Simplificado para 0 decimais para k
                return `R$ ${{(value/1000).toFixed(decimals).replace('.',',')}}k`;
            }}
            return `R$ ${{value.toFixed(2).replace('.',',')}}`;
        }}

        function createLeafletMarker(imovelData) {{
            let popupHtml = `<div style="font-family: Arial, sans-serif; max-width: 280px; font-size: 0.9em;">
                             <h4 style="margin-bottom: 5px; font-size: 1.1em;">${{imovelData.titulo || 'Imóvel'}}</h4><hr style="margin: 5px 0;">
                             <p style="margin: 3px 0;"><i class="fas fa-dollar-sign fa-fw" style="color: ${{imovelData.marker_color}};"></i> <strong>Preço:</strong> ${{formatPriceForJS(imovelData.price)}}</p>`;
            if (imovelData.area_m2 != null) popupHtml += `<p style="margin: 3px 0;"><i class="fas fa-ruler-combined fa-fw"></i> <strong>Área:</strong> ${{parseFloat(imovelData.area_m2).toFixed(0)}} m²</p>`;
            if (imovelData.num_quartos != null) popupHtml += `<p style="margin: 3px 0;"><i class="fas fa-bed fa-fw"></i> <strong>Quartos:</strong> ${{parseInt(imovelData.num_quartos)}}</p>`;
            if (imovelData.num_banheiros != null) popupHtml += `<p style="margin: 3px 0;"><i class="fas fa-bath fa-fw"></i> <strong>Banheiros:</strong> ${{parseInt(imovelData.num_banheiros)}}</p>`;
            if (imovelData.num_vagas != null) popupHtml += `<p style="margin: 3px 0;"><i class="fas fa-car fa-fw"></i> <strong>Vagas:</strong> ${{parseInt(imovelData.num_vagas)}}</p>`;
            if (imovelData.fonte) popupHtml += `<p style="margin: 3px 0;"><i class="fas fa-building fa-fw"></i> <strong>Fonte:</strong> ${{imovelData.fonte}}</p>`;
            popupHtml += `<p style="margin: 3px 0;"><i class="fas fa-map-marker-alt fa-fw"></i> <strong>Endereço:</strong> ${{imovelData.endereco}}</p>`;
            if (imovelData.is_default_loc) popupHtml += '<p style="color: #e67e22;font-weight:bold;"><i class="fas fa-exclamation-triangle"></i> ATENÇÃO: Localização Aproximada</p>';
            let link = imovelData.link || '#';
            if (typeof link === 'string' && !link.startsWith('http://') && !link.startsWith('https://') && link !== '#') {{
                link = 'http://' + link;
            }}
            popupHtml += `<hr style="margin: 5px 0;"><p style="margin-top: 5px; text-align: center;">
                          <a href="${{link}}" target="_blank" style="color: #007bff; font-weight: bold;">
                          <i class="fas fa-external-link-alt"></i> Ver Anúncio</a></p></div>`;

            let tooltipText = `${{imovelData.bairro_display_name}} - ${{formatPriceForJS(imovelData.price)}}`;
            if (imovelData.is_default_loc) tooltipText += " (Aprox.)";
            
            const markerOptions = {{
                radius: 5, color: imovelData.marker_color, fill: true,
                fillColor: imovelData.marker_color, fillOpacity: 0.7
            }};
            const marker = L.circleMarker([imovelData.lat, imovelData.lon], markerOptions);
            marker.bindPopup(popupHtml, {{maxWidth: 300}}); // Adicionado maxWidth para popup
            marker.bindTooltip(tooltipText);
            return marker;
        }}

        function applyFilters() {{
            // console.log("Filter: Aplicando filtros...");
            const minPriceInput = document.getElementById('minPriceInput').value;
            const maxPriceInput = document.getElementById('maxPriceInput').value;
            
            const minPrice = minPriceInput ? parseFloat(minPriceInput) : 0;
            const maxPrice = maxPriceInput ? parseFloat(maxPriceInput) : Infinity;
            
            const selectedRangeCheckboxes = Array.from(document.querySelectorAll("input[name='price_range']:checked"));
            let priceRangesFromCheckboxes = [];
            if (selectedRangeCheckboxes.length > 0) {{
                selectedRangeCheckboxes.forEach(cb => {{
                    priceRangesFromCheckboxes.push({{ 
                        min: parseFloat(cb.dataset.min), 
                        max: (cb.dataset.max === 'Infinity' ? Infinity : parseFloat(cb.dataset.max))
                    }});
                }});
            }}

            const filteredImoveis = allImoveisData.filter(imovel => {{
                const price = parseFloat(imovel.price);
                
                // Se o imóvel não tem preço (NaN)
                if (isNaN(price)) {{
                    // Mostrar apenas se nenhum filtro de preço estiver ativo (nem min/max, nem checkboxes)
                    return !minPriceInput && !maxPriceInput && selectedRangeCheckboxes.length === 0;
                }}

                let matchesNumericRange = (price >= minPrice && price <= maxPrice);
                
                let matchesCheckboxRange = true; // Assume true se nenhum checkbox estiver marcado
                if (priceRangesFromCheckboxes.length > 0) {{
                    matchesCheckboxRange = priceRangesFromCheckboxes.some(range => price >= range.min && price < range.max);
                }}
                
                return matchesNumericRange && matchesCheckboxRange;
            }});

            // console.log(`Filter: Total de imóveis: ${{allImoveisData.length}}, Filtrados: ${{filteredImoveis.length}}`);

            for (const bairro_norm in markerClusterGroupObjects) {{
                if (markerClusterGroupObjects[bairro_norm] && markerClusterGroupObjects[bairro_norm].clearLayers) {{
                    markerClusterGroupObjects[bairro_norm].clearLayers();
                }}
            }}
            
            const markersByGroup = {{}};
            filteredImoveis.forEach(imovel => {{
                const leafletMarker = createLeafletMarker(imovel);
                const groupName = imovel.bairro_norm;
                if (!markersByGroup[groupName]) markersByGroup[groupName] = [];
                markersByGroup[groupName].push(leafletMarker);
            }});

            for (const groupName in markersByGroup) {{
                if (markerClusterGroupObjects[groupName] && markerClusterGroupObjects[groupName].addLayers) {{
                     markerClusterGroupObjects[groupName].addLayers(markersByGroup[groupName]);
                }}
            }}
            // console.log("Filter: Filtros aplicados e marcadores atualizados.");
        }}

        function clearFilters() {{
            document.getElementById('minPriceInput').value = '';
            document.getElementById('maxPriceInput').value = '';
            document.querySelectorAll("input[name='price_range']").forEach(cb => cb.checked = false);
            applyFilters();
        }}

        document.addEventListener('DOMContentLoaded', function() {{
            let attempts = 0;
            const maxAttempts = 30; // Tentar por até 3 segundos
            const intervalId = setInterval(function() {{
                let mapInstanceReady = typeof window['{map_var_name_str}'] !== 'undefined' && window['{map_var_name_str}'] !== null;
                let allMcsReady = true;
                if (Object.keys(markerClustersVarNames).length > 0) {{ // Só checar MCs se houver algum esperado
                    for (const bairro_norm in markerClustersVarNames) {{
                        if (typeof window[markerClustersVarNames[bairro_norm]] === 'undefined' || window[markerClustersVarNames[bairro_norm]] === null) {{
                            allMcsReady = false;
                            break;
                        }}
                    }}
                }} else {{ // Se não há MCs (nenhum item mapeado), considera pronto para filtros (não fará nada)
                    allMcsReady = true;
                }}

                if (mapInstanceReady && allMcsReady) {{
                    clearInterval(intervalId);
                    initializeMarkerClusterGroups(); 
                    
                    const applyBtn = document.getElementById('applyFiltersButton');
                    const clearBtn = document.getElementById('clearFiltersButton');

                    if(applyBtn) applyBtn.addEventListener('click', applyFilters); else console.error("Filter: Botão Aplicar não encontrado");
                    if(clearBtn) clearBtn.addEventListener('click', clearFilters); else console.error("Filter: Botão Limpar não encontrado");
                    
                    // console.log("Filter: Barra de filtros e mapa inicializados e listeners configurados.");
                    applyFilters(); // Aplicar uma vez para carregar os marcadores iniciais respeitando filtros vazios
                }} else {{
                    attempts++;
                    if (attempts > maxAttempts) {{
                        clearInterval(intervalId);
                        console.error("Filter: Falha ao inicializar o mapa ou MarkerClusters a tempo para os filtros.");
                    }}
                }}
            }}, 100);
        }});
    </script>
    """
    full_html_content = f"<style>{style_css}</style>\n{filter_bar_html}\n{javascript_code}"
    return full_html_content

# --- Função Principal de Processamento por Arquivo ---
def processar_json_e_criar_mapa(json_file_name, base_input_dir, output_dir, geocode_cache_global, driver_instance, regio_goiania_coords, faixas_preco_config):
    logger.info(f"=== Iniciando processamento para: {json_file_name} ===")
    json_path = os.path.join(base_input_dir, json_file_name)
    map_name_base = os.path.splitext(json_file_name)[0]
    output_html_name = f"mapa_{map_name_base}.html"
    output_html_path = os.path.join(output_dir, output_html_name)
    failed_addresses_log_path = os.path.join(output_dir, f"falhas_geocodificacao_{map_name_base}.txt")
    not_mapped_log_path = os.path.join(output_dir, f"nao_mapeados_fora_regiao_{map_name_base}.txt")

    # ... (resto do seu código de carregamento e correção de JSON) ...
    if not os.path.exists(json_path):
        logger.error(f"Arquivo JSON de entrada não encontrado: {json_path}. Pulando.")
        return None

    dados = None
    file_content_debug = "" 
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            file_content = f.read().strip()
        
        file_content_debug = file_content 
        corrected_content = file_content
        original_content_for_comparison = file_content 

        is_single_object = corrected_content.startswith('{') and corrected_content.endswith('}')
        
        if not corrected_content.startswith('[') and not is_single_object and \
           ('},{' in corrected_content or re.search(r'\}\s*,\s*,\s*\{', corrected_content)): 
            corrected_content = f"[{corrected_content}]"
            logger.warning(f"Conteúdo de '{json_path}' não parecia ser uma lista JSON formal nem um objeto único. Tentando envolver em colchetes.")

        pattern_multiple_commas = r'(?<=[}\]])\s*,(?:\s*,)+\s*(?=[{\[])'
        if re.search(pattern_multiple_commas, corrected_content):
            corrected_content = re.sub(pattern_multiple_commas, ',', corrected_content)
            logger.info(f"Tentativa de correção de múltiplas vírgulas entre elementos JSON em '{json_path}'.")
        
        if corrected_content != original_content_for_comparison:
            logger.info(f"Conteúdo de '{json_path}' foi modificado pelas rotinas de correção antes do parseamento.")
            file_content_debug = corrected_content 

        dados = json.loads(corrected_content)

        if isinstance(dados, dict):
            logger.warning(f"Conteúdo de {json_path} resultou em um único objeto JSON. Envolvendo em lista.")
            dados = [dados]
        elif not isinstance(dados, list):
            logger.error(f"Conteúdo de {json_path} não é uma lista JSON nem um objeto JSON. Tipo: {type(dados)}. Pulando.")
            return None
        
        logger.info(f"Dados carregados de '{json_path}'. Total de {len(dados)} itens.")
        
    except json.JSONDecodeError as e:
        logger.error(f"Erro de decodificação JSON em '{json_path}': {e}")
        snippet_start = max(0, e.pos - 30)
        snippet_end = min(len(file_content_debug), e.pos + 30)
        problematic_snippet = file_content_debug[snippet_start:snippet_end]
        logger.debug(f"Posição do erro: {e.pos}. Trecho problemático:\n>>>\n{problematic_snippet}\n<<<")
        return None
    except Exception as e: 
        logger.error(f"Erro inesperado ao carregar ou pré-processar JSON de '{json_path}': {e}")
        return None

    mapa_folium = criar_mapa_centralizado()
    grupos_bairro_map = {} # Para FeatureGroups e MarkerClusters por bairro
    
    # INICIALIZAÇÕES PARA A BARRA DE FILTRO
    imoveis_para_js = []
    marker_cluster_js_vars_map = {} # bairro_norm -> mc.get_name() para o JS

    geocoded_map, existing_coords_map, cache_hit_map, default_coords_map, skipped_map, not_mapped_outside_map = 0,0,0,0,0,0
    failed_items_fallback_list_map = []
    not_mapped_items_list_map = []

    for i, item_original in enumerate(dados, start=1):
        if i > 1 and (i - 1) % BATCH_SIZE == 0:
            logger.info(f"Processados {i-1}/{len(dados)} para {map_name_base}. Pausando {BATCH_PAUSE}s...")
            time.sleep(BATCH_PAUSE)
            if (i - 1) % (BATCH_SIZE * 5) == 0: salvar_cache(geocode_cache_global)

        item = ajustar_nomes_campos(item_original)
        # logger.info(f"--- Processando item {i}/{len(dados)} (mapa: {map_name_base}) ---") # Log muito verboso
        endereco = item.get('endereco')

        if not endereco or not isinstance(endereco, str):
            logger.warning(f"Item {i}: Endereço ausente/inválido. Pulando.")
            skipped_map += 1
            continue

        lat, lon = None, None
        source_coord = "Não Geocodificado"
        is_default_loc = False

        tem_coords, lat_ex, lon_ex = usar_coordenadas_existentes(item)
        if tem_coords:
            lat, lon, source_coord = lat_ex, lon_ex, "Existente"
            existing_coords_map += 1
        else:
            cache_hit, lat_c, lon_c = verificar_cache(endereco, geocode_cache_global)
            if cache_hit:
                lat, lon, source_coord = lat_c, lon_c, "Cache"
                cache_hit_map += 1
            elif driver_instance:
                # logger.info(f"Item {i}: Tentando geocodificação online...") # Log verboso
                lat_geo, lon_geo, _ = selenium_geocode(endereco, driver_instance)
                if lat_geo is not None and lon_geo is not None:
                    lat, lon, source_coord = lat_geo, lon_geo, "Geocodificado"
                    geocoded_map +=1
                    atualizar_cache(endereco, lat, lon, geocode_cache_global)
                # else: logger.warning(f"Item {i}: Falha na geocodificação online para '{endereco}'.")
            # else: logger.warning(f"Item {i}: Driver não disponível e cache miss.")
        
        if lat is None or lon is None:
            lat_fallback, lon_fallback = coordenadas_centro_goiania()
            # Não atribuir lat, lon ainda, só se for realmente usar fallback
            source_coord_fallback, is_default_loc_fallback = "Fallback (Centro Gyn)", True
            # logger.warning(f"Item {i}: Sem coordenadas. Será fallback se não estiver na região.")
            # failed_items_fallback_list_map.append({'item_index': i, 'endereco': endereco, 'motivo': 'Falha coordenadas'})
            
        # Verificar se está na região ANTES de aplicar fallback definitivo
        # Se lat/lon vieram de geocodificação/cache mas estão fora da região, não usar fallback ainda
        if lat is not None and lon is not None:
            if not esta_na_regiao(lat, lon, regio_goiania_coords):
                logger.debug(f"Item {i}: Coords ({lat}, {lon}) FORA da região. Não mapeando.")
                not_mapped_outside_map += 1
                not_mapped_items_list_map.append({'item_index': i, 'endereco': endereco, 'latitude': lat, 'longitude': lon, 'source': source_coord})
                continue # Pula para o próximo item, não adiciona ao mapa nem aos dados JS
            # else: Coords válidas e dentro da região
        else: # lat E lon SÃO None -> Usar fallback
            lat, lon = coordenadas_centro_goiania()
            source_coord, is_default_loc = "Fallback (Centro Gyn)", True
            default_coords_map += 1
            logger.warning(f"Item {i}: Usando fallback (Centro de Goiânia) para '{endereco}'.")
            failed_items_fallback_list_map.append({'item_index': i, 'endereco': endereco, 'motivo': 'Falha coordenadas, usando fallback'})


        # logger.info(f"Item {i}: Coords ({lat}, {lon}) VÁLIDAS para mapeamento.")
        valor_num = float('nan') 
        try:
            valor_num = float(item.get('valor')) 
        except (ValueError, TypeError):
            pass # valor_num permanece NaN

        faixa_selecionada = faixas_preco_config['Sem Preço']
        if not valor_num != valor_num:  # Checa se valor_num NÃO é NaN
            for _, info_f in faixas_preco_config.items():
                if info_f['min'] is not None and info_f['max'] is not None and info_f['min'] <= valor_num < info_f['max']:
                    faixa_selecionada = info_f; break
        cor_marcador = faixa_selecionada['color']

        bairro_item = extrair_bairro(item)
        bairro_norm_item = normalize_string(bairro_item)

        if bairro_norm_item not in grupos_bairro_map:
            fg = folium.FeatureGroup(name=f"Bairro: {bairro_item}", show=True)
            # Usar um nome previsível para o MarkerCluster se possível, ou pegar via get_name()
            mc = MarkerCluster(name=f"Cluster_{bairro_norm_item.replace(' ', '_')}", disable_clustering_at_zoom=16).add_to(fg) # Exemplo de nome
            fg.add_to(mapa_folium)
            grupos_bairro_map[bairro_norm_item] = {'feature_group': fg, 'marker_cluster': mc}
            
            # ARMAZENAR O NOME DA VARIÁVEL JS DO MARKERCLUSTER
            # Isso garante que pegamos o nome real que Folium usará
            marker_cluster_js_vars_map[bairro_norm_item] = mc.get_name()
        else: 
            mc = grupos_bairro_map[bairro_norm_item]['marker_cluster']
        
        # Os marcadores em si não são adicionados aqui no Python,
        # eles serão criados e adicionados pelo JavaScript baseado nos dados coletados.
        # No entanto, o MarkerCluster e FeatureGroup precisam existir.

        # Extrair vagas (lógica movida para coleta de dados para JS)
        vagas_finais = None
        try: vagas_finais = int(item.get('num_vagas'))
        except (ValueError, TypeError, AttributeError):
            vagas_str = item.get('vagas', '')
            if isinstance(vagas_str, str):
                match_v = re.search(r'\d+', vagas_str)
                if match_v:
                    try: vagas_finais = int(match_v.group(0))
                    except ValueError: pass
            elif isinstance(vagas_str, (int, float)):
                 try: vagas_finais = int(vagas_str)
                 except ValueError: pass
        
        # COLETAR DADOS DO IMÓVEL PARA O JAVASCRIPT
        imovel_data_for_js = {
            'id': i,
            'lat': lat,
            'lon': lon,
            'price': valor_num if valor_num == valor_num else None, # Envia null para JS se NaN
            'bairro_norm': bairro_norm_item,
            'bairro_display_name': bairro_item,
            'titulo': item.get('titulo', 'Imóvel'),
            'endereco': endereco,
            'link': item.get('link', '#'),
            'area_m2': item.get("area_m2"),
            'num_quartos': item.get('num_quartos'),
            'num_banheiros': item.get('num_banheiros'),
            'num_vagas': vagas_finais,
            'fonte': item.get('fonte'),
            'marker_color': cor_marcador,
            'is_default_loc': is_default_loc,
            # Não precisa do popup_html e tooltip_txt, pois o JS vai montá-los
        }
        imoveis_para_js.append(imovel_data_for_js)
        # logger.info(f"Item {i}: Adicionado aos dados para JS. Coords: ({lat}, {lon}). Fonte: {source_coord}.")
            
    logger.info(f"Processamento dos itens para {map_name_base} concluído.")

    # APÓS O LOOP DE PROCESSAMENTO DE TODOS OS ITENS
    
    # Serializar os dados para JS
    todos_imoveis_json_str = json.dumps(imoveis_para_js)
    marker_clusters_map_json_str = json.dumps(marker_cluster_js_vars_map) 
    map_var_name = mapa_folium.get_name()

    # Criar e adicionar a barra de filtro e o JS
    # A CDN do FontAwesome já é adicionada implicitamente pelo Folium ou pelos popups.
    # Se não for, o HTML da barra pode precisar incluir:
    # <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.2.0/css/all.min.css"/>
    # Mas como seus popups já usam, deve estar ok.
    
    filter_sidebar_full_html = criar_barra_filtro_html_e_js(
        faixas_preco_config,
        todos_imoveis_json_str,
        map_var_name,
        marker_clusters_map_json_str
    )
    mapa_folium.get_root().html.add_child(folium.Element(filter_sidebar_full_html))

    mapa_folium.get_root().html.add_child(folium.Element(criar_legenda_html(faixas_preco_config)))
    if grupos_bairro_map: # Só adicionar LayerControl se houver grupos/bairros
        folium.LayerControl(collapsed=True).add_to(mapa_folium)

    try:
        mapa_folium.save(output_html_path)
        logger.info(f"Mapa salvo: '{output_html_path}'")
    except Exception as e:
        logger.error(f"Erro ao salvar mapa '{output_html_path}': {e}")
        return None

    if failed_items_fallback_list_map:
        with open(failed_addresses_log_path, 'w', encoding='utf-8') as f:
            f.write(f"Itens mapeados com fallback para {map_name_base}:\n")
            for item_info in failed_items_fallback_list_map: f.write(f"Idx: {item_info['item_index']}, End: {item_info['endereco']}, Motivo: {item_info['motivo']}\n")
    if not_mapped_items_list_map:
        with open(not_mapped_log_path, 'w', encoding='utf-8') as f:
            f.write(f"Itens NÃO mapeados (fora da região) para {map_name_base}:\n")
            for item_info in not_mapped_items_list_map: f.write(f"Idx: {item_info['item_index']}, End: {item_info['endereco']}, Coords: ({item_info['latitude']},{item_info['longitude']}), Fonte: {item_info['source']}\n")

    # O total de mapeados agora será determinado pelo JS no carregamento inicial dos filtros
    total_mapeados_inicialmente = len(imoveis_para_js) 
    logger.info(f"--- Resumo para {map_name_base} ---")
    logger.info(f"Total de itens JSON: {len(dados) if dados else 0}, Itens válidos para mapa (com coords): {total_mapeados_inicialmente}, Pulados (sem endereço): {skipped_map}")
    logger.info(f"Coords: Exist: {existing_coords_map}, Cache: {cache_hit_map}, Geocod: {geocoded_map}, Fallback Efetivo: {default_coords_map}")
    logger.info(f"Não Mapeados (Fora Região ou falha geocod): {not_mapped_outside_map}")
    
    nome_amigavel_mapa = json_file_name.replace("resultados_", "").replace(".json", "").replace("_", " ").capitalize()
    return {"title": nome_amigavel_mapa, "path": output_html_name}


# --- Função de Geração do Índice ---
def gerar_index_html(map_infos_list, index_file_path):
    if not map_infos_list:
        logger.warning("Nenhuma informação de mapa para gerar o índice.")
        return
    map_links_html_str = ""
    for map_info_item in map_infos_list:
        map_links_html_str += f'        <li><a href="{map_info_item["path"]}">{map_info_item["title"]}</a></li>\n'
    html_content_template = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Índice de Mapas de Imóveis</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #f0f2f5; color: #333; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }}
        .container {{ width: 90%; max-width: 800px; margin-top: 30px; background-color: #fff; padding: 20px 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a73e8; text-align: center; margin-bottom: 25px; font-size: 2em; }}
        ul {{ list-style-type: none; padding: 0; }}
        li {{ margin-bottom: 15px; }}
        a {{ display: block; padding: 15px 20px; background-color: #e9f0fc; color: #1a73e8; text-decoration: none; border-radius: 5px; font-size: 1.1em; font-weight: 500; transition: all 0.3s ease; border: 1px solid #d1e0fc; }}
        a:hover {{ background-color: #d1e0fc; color: #0056b3; transform: translateY(-2px); box-shadow: 0 2px 6px rgba(0,0,0,0.08); }}
        footer {{ margin-top: 30px; padding: 15px; text-align: center; font-size: 0.9em; color: #777; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Mapas de Imóveis Gerados</h1>
        <ul>
{map_links_html_str}
        </ul>
    </div>
    <footer><p>Mapas gerados em: {time.strftime("%d/%m/%Y %H:%M:%S")}</p></footer>
</body></html>"""
    try:
        with open(index_file_path, 'w', encoding='utf-8') as f: f.write(html_content_template)
        logger.info(f"Arquivo de índice salvo: '{index_file_path}'")
    except Exception as e: logger.error(f"Erro ao salvar arquivo de índice HTML: {e}")

# --- Script Principal ---
if __name__ == '__main__':
    os.makedirs(OUTPUT_DIR_NAME, exist_ok=True)
    logger.info(f"Diretório de saída: '{os.path.abspath(OUTPUT_DIR_NAME)}'")

    geocode_cache_main = carregar_cache()
    driver_main = None
    try:
        logger.info("Tentando inicializar WebDriver global...")
        driver_main = inicializar_driver()
    except RuntimeError as e:
        logger.warning(f"WebDriver global não inicializado: {e}. Geocodificação online dependerá do cache.")
    except Exception as e_geral:
        logger.error(f"Erro inesperado ao inicializar WebDriver: {e_geral}")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_input_dir_main = os.path.join(script_dir, "resultado") 
    logger.info(f"Procurando arquivos JSON no diretório: {base_input_dir_main}")

    if not os.path.isdir(base_input_dir_main):
        logger.error(f"Diretório de entrada '{base_input_dir_main}' não encontrado.")
    # else:
    #     try: logger.info(f"Conteúdo de '{base_input_dir_main}': {os.listdir(base_input_dir_main)}")
    #     except Exception as e: logger.error(f"Erro ao listar '{base_input_dir_main}': {e}")

    FAIXAS_PRECO_GLOBAL_CONFIG = {
        'Até R$ 200k':     {'min': 0,       'max': 200000,    'color': '#28a745', 'icon': 'dollar-sign'},
        'R$ 200k-500k':    {'min': 200000,  'max': 500000,    'color': '#007bff', 'icon': 'dollar-sign'},
        'R$ 500k-1M':     {'min': 500000,  'max': 1000000,   'color': '#fd7e14', 'icon': 'dollar-sign'}, # Alterado para M
        'Acima de R$ 1M': {'min': 1000000, 'max': float('inf'), 'color': '#dc3545', 'icon': 'dollar-sign'}, # Alterado para M
        'Sem Preço':       {'min': None,    'max': None,      'color': '#6c757d', 'icon': 'question-circle'}
    }

    maps_generated_infos_list = []

    for json_file_item in JSON_FILES_TO_PROCESS:
        map_gen_info = processar_json_e_criar_mapa(
            json_file_item,
            base_input_dir_main,
            OUTPUT_DIR_NAME,
            geocode_cache_main,
            driver_main,
            REGIAO_GOIANIA,
            FAIXAS_PRECO_GLOBAL_CONFIG 
        )
        if map_gen_info:
            maps_generated_infos_list.append(map_gen_info)
        logger.info(f"Pausa de {BATCH_PAUSE // 2}s entre processamento de arquivos JSON...") 
        time.sleep(BATCH_PAUSE // 2 if BATCH_PAUSE > 1 else 1)

    if maps_generated_infos_list:
        index_html_main_path = os.path.join(OUTPUT_DIR_NAME, "index.html")
        gerar_index_html(maps_generated_infos_list, index_html_main_path)
    else:
        logger.warning("Nenhum mapa foi gerado. Arquivo de índice não criado.")

    if driver_main:
        try:
            driver_main.quit()
            logger.info("WebDriver global fechado.")
        except Exception as e: logger.error(f"Erro ao fechar WebDriver global: {e}")

    salvar_cache(geocode_cache_main)
    logger.info("--- FIM DA EXECUÇÃO DE TODOS OS ARQUIVOS ---")
    print(f"\nProcessamento concluído. Verifique a pasta '{OUTPUT_DIR_NAME}'.")