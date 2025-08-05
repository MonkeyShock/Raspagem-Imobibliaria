import os
import json
import time
import re
import unicodedata
import subprocess
import urllib.parse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from multiprocessing import Pool, Manager, Value

# Diretórios de entrada para cada fonte
INPUT_DIRS = {
    'olx': 'olx_data',
    'zapimoveis': 'zapimoveis_data',
    'vivareal': 'vivareal_data',
    'invest': 'investt_data',
    'facilitaimoveis': 'facilitaimoveis_data',
}

# Mapeamento para nomes dos arquivos de entrada JSON para categorias de interesse
CATEGORY_FILE_PATTERNS = {
    'casa_venda': [
        'casas_compra.json', 'casas_compra.json', 'casas_compra.json',
        'casas_venda.json', 'casas_venda.json',
    ],
    'apartamento_venda': [
        'apartamentos_compra.json', 'apartamentos_compra.json', 'apartamentos_compra.json',
        'apartamentos_venda.json', 'apartamentos_venda.json',
    ],
    'casa_aluguel': [
        'casas_aluguel.json', 'casas_aluguel.json', 'casas_aluguel.json',
        'casas_aluguel.json', 'casas_aluguel.json',
    ],
    'apartamento_aluguel': [
        'apartamentos_aluguel.json', 'apartamentos_aluguel.json', 'apartamentos_aluguel.json',
        'apartamentos_aluguel.json', 'apartamentos_aluguel.json',
    ],
    'terreno_venda': [
        'terrenos_terrenos.json', 'lote_compra.json', 'terreno_compra.json',
        'terrenos_compra.json', 'terrenos_venda.json',
    ],
}

OUTPUT_DIR = 'resultado'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Globais do Worker
worker_geocoding_cache = None
worker_geocoding_request_count = None
worker_counter_access_lock = None 
worker_max_geocoding_requests_warning = 100

def init_worker_globals(shared_cache, shared_counter, shared_counter_lock_arg, max_warning):
    global worker_geocoding_cache, worker_geocoding_request_count, worker_counter_access_lock, worker_max_geocoding_requests_warning
    worker_geocoding_cache = shared_cache
    worker_geocoding_request_count = shared_counter
    worker_counter_access_lock = shared_counter_lock_arg
    worker_max_geocoding_requests_warning = max_warning

def limpar_endereco_para_geocodificacao(endereco_str):
    if not isinstance(endereco_str, str) or not endereco_str.strip():
        return endereco_str
    frases_lixo_base = [
        "Casa para comprar em", "Apartamento para comprar em",
        "Casa para alugar em", "Apartamento para alugar em",
        "Terreno para comprar em", "Lote para comprar em",
        "Terreno para vender em", "Lote para vender em"
    ]
    endereco_limpo = endereco_str
    for frase_base in frases_lixo_base:
        padrao_inicio_colado = rf"^\s*{re.escape(frase_base)}(?=[a-zA-Z0-9À-ÿ])"
        endereco_limpo = re.sub(padrao_inicio_colado, "", endereco_limpo, flags=re.IGNORECASE).strip()
        padrao_inicio_espaco = rf"^\s*{re.escape(frase_base)}\s*,?\s*"
        endereco_limpo = re.sub(padrao_inicio_espaco, "", endereco_limpo, flags=re.IGNORECASE).strip()
        padrao_meio_colado = rf",\s*{re.escape(frase_base)}(?=[a-zA-Z0-9À-ÿ])"
        endereco_limpo = re.sub(padrao_meio_colado, ",", endereco_limpo, flags=re.IGNORECASE)
        padrao_meio_espaco = rf",\s*{re.escape(frase_base)}\s*,?\s*"
        endereco_limpo = re.sub(padrao_meio_espaco, ",", endereco_limpo, flags=re.IGNORECASE)
    endereco_limpo = re.sub(r'\s*,\s*', ', ', endereco_limpo)
    endereco_limpo = re.sub(r'(,\s*){2,}', ', ', endereco_limpo)
    endereco_limpo = endereco_limpo.strip(' ,')
    endereco_limpo = re.sub(r'\s+', ' ', endereco_limpo).strip()
    if endereco_limpo.startswith(", "): endereco_limpo = endereco_limpo[2:]
    elif endereco_limpo.startswith(","): endereco_limpo = endereco_limpo[1:]
    return endereco_limpo

def load_json_safe(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        print(f"AVISO: Arquivo não encontrado: '{filepath}'", flush=True)
        return []
    except json.JSONDecodeError:
        print(f"AVISO: Erro ao decodificar JSON em '{filepath}'. Arquivo pode estar corrompido.", flush=True)
        return []
    except Exception as e:
        print(f"AVISO: Erro inesperado ao carregar '{filepath}': {e}", flush=True)
        return []

def normalizar_texto(texto):
    if not texto: return ''
    texto = str(texto)
    texto = unicodedata.normalize('NFKD', texto)
    return texto.encode('ASCII', 'ignore').decode('utf-8').lower()

def geocodificar(endereco):
    """
    Geocodifica um endereço usando a nova lógica de scraping de URL do Google Maps.
    """
    global worker_geocoding_cache, worker_geocoding_request_count, worker_max_geocoding_requests_warning
    
    endereco_original_para_log = None
    if isinstance(endereco, str):
        endereco_original_para_log = endereco[:150]
        endereco_limpo = limpar_endereco_para_geocodificacao(endereco)
        if endereco_limpo != endereco and endereco_limpo:
             print(f"Geo: Endereço original: '{endereco_original_para_log[:70]}...', Limpo: '{endereco_limpo[:70]}...'")
        endereco = endereco_limpo
    
    if not endereco: return None, None
    
    if endereco in worker_geocoding_cache:
        print(f"GEO_TRACE: Cache hit for: '{endereco[:70]}...'")
        return worker_geocoding_cache[endereco]

    txt = normalizar_texto(endereco)
    endereco_formatado = f"{endereco}, Goiânia, GO, Brasil" if 'goiania' not in txt and 'goias' not in txt else endereco
    
    with worker_counter_access_lock:
        worker_geocoding_request_count.value += 1
        current_req_count = worker_geocoding_request_count.value
    
    if current_req_count > 0 and current_req_count % worker_max_geocoding_requests_warning == 0:
        print(f"Alerta GEO: {current_req_count} requisições totais de geocodificação feitas. Monitore o uso.")

    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--log-level=3')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    service = Service(log_output=os.devnull)
    driver = None
    
    try:
        print(f"GEO_TRACE: Geocodificando com Google Maps: '{endereco_formatado[:70]}...'")
        driver = webdriver.Chrome(options=options, service=service)
        
        # Lógica de geocodificação via Google Maps URL Scraping
        encoded_address = urllib.parse.quote(endereco_formatado)
        search_url = f"https://www.google.com/maps/search/?api=1&query={encoded_address}"
        
        driver.get(search_url)
        # Aumenta o timeout e espera que a URL contenha as coordenadas
        WebDriverWait(driver, 20).until(EC.url_contains("@"))
        
        current_url = driver.current_url
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', current_url)
        
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            worker_geocoding_cache[endereco] = (lat, lon)
            print(f"GEO_TRACE: Sucesso (Google Maps): '{endereco_formatado[:50]}...' -> ({lat}, {lon})")
            return lat, lon
        else:
             print(f"GEO_TRACE: Coordenadas não encontradas na URL final para '{endereco_formatado[:50]}...'.")

    except TimeoutException:
        print(f"GEO_TRACE: Timeout (Google Maps) para '{endereco_formatado[:50]}...'")
    except WebDriverException as e:
        print(f"GEO_TRACE: Erro WebDriver (Google Maps) para '{endereco_formatado[:50]}...': {type(e).__name__} - {e}")
    except Exception as e:
        print(f"GEO_TRACE: Erro inesperado ao geocodificar '{endereco_formatado[:50]}...': {type(e).__name__} - {e}")
    finally:
        if driver:
            driver.quit()
        # Delay para evitar sobrecarregar o serviço
        time.sleep(1.5)
    
    worker_geocoding_cache[endereco] = (None, None)
    return None, None


def parse_price_to_float(preco_val):
    if preco_val is None: return None
    s = str(preco_val)
    s = re.sub(r'[R$\s]', '', s).strip()
    if ',' in s and '.' in s: 
        if s.rfind(',') > s.rfind('.'): 
            s = s.replace('.', '').replace(',', '.')
        else: 
            s = s.replace(',', '')
    elif ',' in s: 
        s = s.replace(',', '.')
    try:
        val = float(s)
        return val if val > 0 else None
    except ValueError:
        return None

def parse_area_to_float(area_val):
    if area_val is None: return None
    s = str(area_val).lower()
    s = s.replace('m²', '').replace('m2', '').strip()
    s = re.sub(r'[^\d\.]', '', s.replace(',', '.')).strip()
    if not s: return None
    try:
        val = float(s)
        return val if val > 0 else None
    except ValueError:
        return None

def extract_standardized_data(item, source):
    tipo_imovel, preco, finalidade, area_m2, quartos, banheiros, vagas, endereco, link = [None] * 9
    
    titulo_str = str(item.get('titulo', ''))
    link_str = str(item.get('link', ''))
    tipo_item_str = str(item.get('tipo', ''))

    titulo_lower = titulo_str.lower()
    link_lower = link_str.lower()
    tipo_item_lower = tipo_item_str.lower()

    if source == 'olx':
        if 'casa' in titulo_lower: tipo_imovel = 'Casa'
        elif 'apartamento' in titulo_lower: tipo_imovel = 'Apartamento'
        elif 'terreno' in titulo_lower or 'lote' in titulo_lower: tipo_imovel = 'Terreno'
        preco = item.get('preco'); area_m2 = item.get('area_m2') 
        quartos = item.get('quartos'); endereco = item.get('localizacao'); link = item.get('link')
    elif source == 'zapimoveis':
        if 'casa' in titulo_lower or 'casa' in link_lower: tipo_imovel = 'Casa'
        elif 'apartamento' in titulo_lower or 'apartamento' in link_lower: tipo_imovel = 'Apartamento'
        elif 'lote' in titulo_lower or 'terreno' in titulo_lower or 'lote' in link_lower or 'terreno' in link_lower: tipo_imovel = 'Terreno'
        preco = item.get('preco'); area_m2 = item.get('area_m2')
        quartos = item.get('quartos'); banheiros = item.get('banheiros'); vagas = item.get('vagas')
        endereco = item.get('endereco') if item.get('endereco') else titulo_str; link = item.get('link')
    elif source == 'invest':
        if 'casa' in tipo_item_lower: tipo_imovel = 'Casa'
        elif 'apartamento' in tipo_item_lower: tipo_imovel = 'Apartamento'
        elif 'terreno' in tipo_item_lower or 'lote' in tipo_item_lower: tipo_imovel = 'Terreno'
        else: 
            if 'casa' in titulo_lower: tipo_imovel = 'Casa'
            elif 'apartamento' in titulo_lower: tipo_imovel = 'Apartamento'
            elif 'terreno' in titulo_lower or 'lote' in titulo_lower: tipo_imovel = 'Terreno'
        
        preco = item.get('venda') if item.get('venda') else item.get('locacao')
        area_m2 = item.get('area') 
        quartos = item.get('quartos'); banheiros = item.get('banheiros'); vagas = item.get('vagas')
        endereco = item.get('localizacao') 
        link = item.get('link') or item.get('urlDetalhes') or item.get('url')
    elif source == 'facilitaimoveis':
        if 'casa' in tipo_item_lower: tipo_imovel = 'Casa'
        elif 'apartamento' in tipo_item_lower: tipo_imovel = 'Apartamento'
        elif 'terreno' in tipo_item_lower or 'lote' in tipo_item_lower: tipo_imovel = 'Terreno'
        preco = item.get('preco'); finalidade = item.get('negocio') 
        area_m2 = item.get('area_m2')
        quartos = item.get('dormitorios'); banheiros = item.get('banheiros')
        vagas = item.get('vagas'); endereco = item.get('endereco'); link = item.get('link')
    elif source == 'vivareal':
        if 'casa' in tipo_item_lower: tipo_imovel = 'Casa'
        elif 'apartamento' in tipo_item_lower: tipo_imovel = 'Apartamento'
        elif 'terreno' in tipo_item_lower or 'lote' in tipo_item_lower: tipo_imovel = 'Terreno'
        else:
            if 'casa' in link_lower: tipo_imovel = 'Casa'
            elif 'apartamento' in link_lower: tipo_imovel = 'Apartamento'
            elif 'terreno' in link_lower or 'lote' in link_lower: tipo_imovel = 'Terreno'
        preco = item.get('preco'); finalidade = item.get('finalidade')
        area_m2 = item.get('area_m2')
        quartos = item.get('quartos'); banheiros = item.get('banheiros')
        vagas = item.get('vagas'); endereco = item.get('endereco'); link = item.get('link')
    
    preco_float = parse_price_to_float(preco)
    area_m2_float = parse_area_to_float(area_m2)
    
    lat, lon = geocodificar(endereco) if endereco and isinstance(endereco, str) and endereco.strip() else (None, None)
    geolocalizacao = {"latitude": lat, "longitude": lon} if lat is not None and lon is not None else None
    
    return {
        "tipo_imovel": tipo_imovel, "finalidade": finalidade, "endereco": endereco, 
        "preco": preco_float, "area_m2": area_m2_float, 
        "quartos": str(quartos) if quartos is not None else None, 
        "banheiros": str(banheiros) if banheiros is not None else None,
        "vagas": str(vagas) if vagas is not None else None, 
        "link": link, "geolocalizacao": geolocalizacao, "fonte": source
    }

def e_preco_similar(preco1, preco2, tolerancia=0.05):
    if preco1 is None or preco2 is None: return False
    p1, p2 = preco1, preco2
    if p1 == 0 and p2 == 0: return True 
    if p1 == 0 or p2 == 0: return False 
    return abs(p1 - p2) / max(p1, p2) <= tolerancia

def e_area_similar(area1, area2, tolerancia=0.05):
    if area1 is None or area2 is None: return False
    a1, a2 = area1, area2
    if a1 == 0 and a2 == 0: return True
    if a1 == 0 or a2 == 0: return False
    return abs(a1 - a2) / max(a1, a2) <= tolerancia

def e_mesmo_local(item1, item2, distancia_maxima_graus=0.001): 
    geo1, geo2 = item1.get('geolocalizacao'), item2.get('geolocalizacao')
    if geo1 and geo2 and geo1.get('latitude') is not None and geo1.get('longitude') is not None \
       and geo2.get('latitude') is not None and geo2.get('longitude') is not None:
        try:
            lat1, lon1 = float(geo1['latitude']), float(geo1['longitude'])
            lat2, lon2 = float(geo2['latitude']), float(geo2['longitude'])
            if abs(lat1 - lat2) <= distancia_maxima_graus and abs(lon1 - lon2) <= distancia_maxima_graus:
                return True
        except (ValueError, TypeError): pass
    
    end1_norm = normalizar_texto(str(item1.get('endereco') or ''))
    end2_norm = normalizar_texto(str(item2.get('endereco') or ''))
    
    if end1_norm and end2_norm and end1_norm != 'none' and end2_norm != 'none' and len(end1_norm) > 5 and len(end2_norm) > 5 :
        end1_clean = re.sub(r'\b(apto|apartamento|casa|nº|numero|num|lote|terreno|edificio|condominio|residencia|bloco|torre)\b\s*[\w\d.-]*', '', end1_norm, flags=re.IGNORECASE).strip()
        end2_clean = re.sub(r'\b(apto|apartamento|casa|nº|numero|num|lote|terreno|edificio|condominio|residencia|bloco|torre)\b\s*[\w\d.-]*', '', end2_norm, flags=re.IGNORECASE).strip()
        end1_clean = re.sub(r'\s\s+', ' ', end1_clean.replace(',', ' ')).strip()
        end2_clean = re.sub(r'\s\s+', ' ', end2_clean.replace(',', ' ')).strip()
        if len(end1_clean) > 5 and len(end2_clean) > 5 :
            return end1_clean in end2_clean or end2_clean in end1_clean
    return False

def sao_imoveis_duplicados(item1, item2):
    if item1.get('tipo_imovel') != item2.get('tipo_imovel') or \
       item1.get('finalidade') != item2.get('finalidade'):
        return False
    if not e_mesmo_local(item1, item2):
        return False
    if item1.get('tipo_imovel') != 'Terreno':
        q1_str, q2_str = item1.get('quartos'), item2.get('quartos')
        if q1_str is not None and q2_str is not None and q1_str.strip() and q2_str.strip():
            try:
                q1_int = int(re.sub(r'\D', '', q1_str))
                q2_int = int(re.sub(r'\D', '', q2_str))
                if q1_int != q2_int: return False
            except ValueError: pass
    preco_similar = e_preco_similar(item1.get('preco'), item2.get('preco'))
    area_similar = e_area_similar(item1.get('area_m2'), item2.get('area_m2'))
    preco_presente_ambos = item1.get('preco') is not None and item2.get('preco') is not None
    area_presente_ambos = item1.get('area_m2') is not None and item2.get('area_m2') is not None
    if preco_presente_ambos and area_presente_ambos: return preco_similar and area_similar
    elif preco_presente_ambos: return preco_similar
    elif area_presente_ambos: return area_similar
    else: return True

def tem_mais_informacoes(item_novo, item_existente):
    campos_gerais = ['preco', 'area_m2', 'endereco', 'link']
    campos_residenciais = ['quartos', 'banheiros', 'vagas']
    campos_novo = campos_gerais + (campos_residenciais if item_novo.get('tipo_imovel') != 'Terreno' else [])
    campos_existente = campos_gerais + (campos_residenciais if item_existente.get('tipo_imovel') != 'Terreno' else [])
    def contar_campos_validos(item, lista_campos):
        count = 0
        for c in lista_campos:
            val = item.get(c)
            if val is not None:
                if isinstance(val, (int, float)) and val != 0: count += 1
                elif isinstance(val, str) and val.strip(): count +=1
        geo = item.get('geolocalizacao')
        if geo and geo.get('latitude') is not None and geo.get('longitude') is not None: count += 1
        return count
    count_novo = contar_campos_validos(item_novo, campos_novo)
    count_existente = contar_campos_validos(item_existente, campos_existente)
    if count_novo == count_existente:
        link_novo_presente = bool(item_novo.get('link') and str(item_novo.get('link')).strip())
        link_existente_presente = bool(item_existente.get('link') and str(item_existente.get('link')).strip())
        if link_novo_presente and not link_existente_presente: return True
        if not link_novo_presente and link_existente_presente: return False
        return False 
    return count_novo > count_existente

def processar_categoria_worker(categoria, arquivos_lista_nomes_param, input_dirs_param, output_dir_param):
    print(f"WORKER: Iniciando processamento para categoria '{categoria}'...", flush=True)
    combinados = []
    registros_duplicados_tratados = 0
    itens_filtrados_preco_area = 0
    itens_sem_tipo_ou_finalidade_validos = 0
    fontes_disponiveis = list(input_dirs_param.keys())

    for idx_fonte, nome_arquivo_json in enumerate(arquivos_lista_nomes_param):
        if idx_fonte < len(fontes_disponiveis):
            source = fontes_disponiveis[idx_fonte]
            input_dir = input_dirs_param[source]
            arquivo_caminho = os.path.join(input_dir, nome_arquivo_json)
            print(f"WORKER '{categoria}': Carregando arquivo '{arquivo_caminho}'...", flush=True)
            lista_itens = load_json_safe(arquivo_caminho)
            if not lista_itens:
                print(f"WORKER '{categoria}': Nenhum item em '{nome_arquivo_json}' ou arquivo não pôde ser carregado.", flush=True)
                continue
            total_itens_no_arquivo = len(lista_itens)
            print(f"WORKER '{categoria}': {total_itens_no_arquivo} itens carregados de '{nome_arquivo_json}' (Fonte: {source})", flush=True)
            
            for item_idx, item_original in enumerate(lista_itens):
                if (item_idx + 1) % 20 == 0 or item_idx == total_itens_no_arquivo - 1:
                    print(f"WORKER '{categoria}': Processando item {item_idx + 1}/{total_itens_no_arquivo} de '{nome_arquivo_json}'...", flush=True)
                item_padronizado = extract_standardized_data(item_original, source)
                if item_padronizado is None : continue
                if 'venda' in categoria or 'compra' in categoria: item_padronizado['finalidade'] = 'Venda'
                elif 'aluguel' in categoria or 'locacao' in categoria: item_padronizado['finalidade'] = 'Aluguel'
                if 'casa' in categoria: item_padronizado['tipo_imovel'] = 'Casa'
                elif 'apartamento' in categoria: item_padronizado['tipo_imovel'] = 'Apartamento'
                elif 'terreno' in categoria: item_padronizado['tipo_imovel'] = 'Terreno'
                if not item_padronizado['tipo_imovel'] or not item_padronizado['finalidade']:
                    itens_sem_tipo_ou_finalidade_validos += 1
                    continue
                item_mantido_por_filtro = True
                if item_padronizado['tipo_imovel'] == 'Terreno' and item_padronizado['finalidade'] == 'Venda':
                    preco_terreno_float = item_padronizado.get('preco')
                    if preco_terreno_float is not None and preco_terreno_float > 150000: item_mantido_por_filtro = False
                if item_padronizado['tipo_imovel'] == 'Casa':
                    area_casa_float = item_padronizado.get('area_m2')
                    if area_casa_float is not None and not (90 <= area_casa_float <= 110): item_mantido_por_filtro = False
                if not item_mantido_por_filtro:
                    itens_filtrados_preco_area += 1
                    continue
                duplicado_encontrado_flag = False
                for idx_existente, imovel_ja_combinado in enumerate(combinados):
                    if sao_imoveis_duplicados(item_padronizado, imovel_ja_combinado):
                        registros_duplicados_tratados += 1
                        duplicado_encontrado_flag = True
                        if tem_mais_informacoes(item_padronizado, imovel_ja_combinado):
                            fontes_sec_antigas = imovel_ja_combinado.get('fontes_secundarias', [])
                            fonte_principal_antiga = imovel_ja_combinado['fonte']
                            combinados[idx_existente] = item_padronizado
                            combinados[idx_existente]['fontes_secundarias'] = combinados[idx_existente].get('fontes_secundarias', [])
                            if fonte_principal_antiga not in combinados[idx_existente]['fontes_secundarias'] and \
                               fonte_principal_antiga != combinados[idx_existente]['fonte']:
                                combinados[idx_existente]['fontes_secundarias'].append(fonte_principal_antiga)
                            for fs_antiga in fontes_sec_antigas:
                                if fs_antiga not in combinados[idx_existente]['fontes_secundarias'] and \
                                   fs_antiga != combinados[idx_existente]['fonte']:
                                    combinados[idx_existente]['fontes_secundarias'].append(fs_antiga)
                        else:
                            imovel_ja_combinado['fontes_secundarias'] = imovel_ja_combinado.get('fontes_secundarias', [])
                            if item_padronizado['fonte'] not in imovel_ja_combinado['fontes_secundarias'] and \
                               item_padronizado['fonte'] != imovel_ja_combinado['fonte']:
                                imovel_ja_combinado['fontes_secundarias'].append(item_padronizado['fonte'])
                        break 
                if not duplicado_encontrado_flag:
                    combinados.append(item_padronizado)
    nome_arquivo_saida = f"resultados_{categoria}.json"
    caminho_saida = os.path.join(output_dir_param, nome_arquivo_saida)
    msg_final = (f"WORKER '{categoria}': Processamento concluído. Salvando em '{caminho_saida}' ({len(combinados)} registros). "
                 f"Duplicatas tratadas: {registros_duplicados_tratados}. "
                 f"Filtrados (preço/área): {itens_filtrados_preco_area}. "
                 f"Descartados (sem tipo/finalidade): {itens_sem_tipo_ou_finalidade_validos}.")
    print(msg_final, flush=True)
    try:
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            json.dump(combinados, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"WORKER '{categoria}': ERRO AO SALVAR '{caminho_saida}': {e}", flush=True)
    return msg_final

def combinar_jsons_paralelo():
    print("Iniciando combinação de JSONs por categoria EM PARALELO...", flush=True)
    manager = Manager()
    shared_geocoding_cache = manager.dict()
    shared_geocoding_request_counter = manager.Value('i', 0)
    shared_counter_lock = manager.Lock()
    max_geocoding_warning_threshold = 50

    tasks_args = []
    categories_to_process_count = 0
    for cat, arquivos_nomes in CATEGORY_FILE_PATTERNS.items():
        output_filename = f"resultados_{cat}.json"
        output_filepath = os.path.join(OUTPUT_DIR, output_filename)
        if os.path.exists(output_filepath):
            print(f"Arquivo de resultado '{output_filepath}' já existe. Pulando categoria '{cat}'.", flush=True)
            continue 
        tasks_args.append((cat, arquivos_nomes, INPUT_DIRS, OUTPUT_DIR))
        categories_to_process_count +=1

    if categories_to_process_count == 0:
        print("Todos os arquivos de resultado para as categorias configuradas já existem ou nenhuma categoria para processar.", flush=True)
        print("\nProcesso de Combinação Concluído (nenhuma tarefa nova executada).", flush=True)
        return

    num_workers = min(len(tasks_args), os.cpu_count() or 1, 4) 
    print(f"Utilizando {num_workers} workers em paralelo para {len(tasks_args)} categorias.", flush=True)

    init_args_tuple = (shared_geocoding_cache, shared_geocoding_request_counter, shared_counter_lock, max_geocoding_warning_threshold)
    with Pool(processes=num_workers, initializer=init_worker_globals, initargs=init_args_tuple) as pool:
        results = pool.starmap(processar_categoria_worker, tasks_args)

    for result_msg in results:
        print(f"MAIN: {result_msg}", flush=True)
    total_geocoding_requests_made = shared_geocoding_request_counter.value
    print(f"\nProcesso de Combinação Paralelo Concluído.", flush=True)
    print(f"Total de {total_geocoding_requests_made} requisições de geocodificação (novas) feitas ao Google Maps nesta execução.", flush=True)
    if total_geocoding_requests_made > 200:
        print("ATENÇÃO: Um número elevado de requisições de geocodificação foi feito.", flush=True)

if __name__ == "__main__":
    start_time = time.time()
    combinar_jsons_paralelo()
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\nTempo total de execução: {total_time:.2f} segundos.", flush=True)
    print("====================================================================", flush=True)
    print(" Processo de Combinação Concluído.", flush=True)
    print(f" Verifique a pasta '{OUTPUT_DIR}' para os arquivos combinados.", flush=True)
    print("====================================================================", flush=True)