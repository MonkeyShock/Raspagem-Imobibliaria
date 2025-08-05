# Imobiliária - Coleta, Processamento e Visualização de Imóveis

Este projeto automatiza a coleta, processamento, deduplicação, geocodificação e visualização de dados de imóveis de diversos portais imobiliários (OLX, VivaReal, ZapImóveis, Investt, FacilitaImóveis) na região de Goiânia e entorno. O objetivo é gerar mapas interativos e relatórios para análise de mercado imobiliário, facilitando a tomada de decisão para investidores, corretores e pesquisadores.

---

## Sumário

- [Visão Geral](#visão-geral)
- [Fluxo de Dados](#fluxo-de-dados)
- [Estrutura dos Diretórios](#estrutura-dos-diretórios)
- [Principais Scripts](#principais-scripts)
- [Instalação e Dependências](#instalação-e-dependências)
- [Configuração do Ambiente](#configuração-do-ambiente)
- [Como Usar - Passo a Passo](#como-usar---passo-a-passo)
- [Exemplo de Execução](#exemplo-de-execução)
- [Dicas de Manutenção](#dicas-de-manutenção)
- [Possíveis Problemas e Soluções](#possíveis-problemas-e-soluções)
- [Licença e Créditos](#licença-e-créditos)

---

## Visão Geral

O projeto foi desenvolvido para automatizar a análise do mercado imobiliário, permitindo:

- Raspagem de dados de imóveis à venda e para aluguel em múltiplos portais.
- Limpeza, padronização e deduplicação dos dados.
- Geocodificação de endereços para obtenção de coordenadas.
- Geração de mapas interativos em HTML com filtros dinâmicos.

## Fluxo de Dados

1. **Raspagem**: Scripts em `OlxPython/`, `VivaRealPython/`, `ZapImoveisPython/`, etc., coletam dados brutos dos portais e salvam em arquivos JSON.
2. **Processamento**: O script `Processamento.py` consolida, limpa e deduplica os dados, padronizando campos e removendo duplicatas.
3. **Geocodificação**: Endereços são convertidos em coordenadas (lat/lon) usando Selenium e Google Maps.
4. **Visualização**: O script `Mapa.py` gera mapas HTML interativos, agrupando imóveis por faixa de preço, tipo, etc.

## Estrutura dos Diretórios

- `OlxPython/`, `VivaRealPython/`, `ZapImoveisPython/`: Scripts de raspagem para cada portal.
- `facilitaimoveis_data/`, `vivareal_data/`, `zapimoveis_data/`, `olx_data/`, `investt_data/`: Dados brutos coletados de cada portal (JSON).
- `resultado/`: Dados processados e consolidados (JSON).
- `mapas_imoveis_gerados/`: Mapas HTML gerados para visualização.
- `documentação/`: Documentos e anotações do projeto.
- `geocode_cache.json`: Cache de geocodificação para evitar consultas repetidas ao Google Maps.

## Principais Scripts

- `Mapa.py`: Gera mapas interativos a partir dos dados processados.
- `Processamento.py`: Consolida, limpa e deduplica os dados de imóveis.
- `FacilitaImoveis.py`, `Invest.py`: Raspagem de dados dos respectivos portais.
- Scripts em subpastas: Cada portal tem scripts específicos para diferentes tipos de imóveis (casas, apartamentos, terrenos, aluguel, venda).

## Instalação e Dependências

As dependências estão listadas em `requirements.txt`. Instale com:

```bash
pip install -r requirements.txt
```

**Principais pacotes:**

- selenium
- undetected-chromedriver
- beautifulsoup4 (bs4)
- folium
- lxml
- tk

## Configuração do Ambiente

- **Google Chrome**: Instale o navegador Chrome.
- **ChromeDriver**: Baixe a versão compatível com seu Chrome e coloque o executável no PATH ou na mesma pasta dos scripts.
- **Python 3.8+** recomendado.

## Como Usar - Passo a Passo

1. **Raspagem dos Dados**

   - Execute os scripts de cada portal (exemplo para OLX):
     ```bash
     cd OlxPython
     python OlxApartamentosCompra.py
     python OlxCasasAluguel.py
     # ... outros scripts conforme desejado
     ```
   - Repita para os outros diretórios de portais.

2. **Processamento e Consolidação**

   - No diretório raiz, execute:
     ```bash
     python Processamento.py
     ```
   - Isso irá consolidar os dados em arquivos na pasta `resultado/`.

3. **Geração dos Mapas**

   - Execute:
     ```bash
     python Mapa.py
     ```
   - Os mapas HTML serão gerados em `mapas_imoveis_gerados/`.

4. **Visualização**

   - Abra os arquivos HTML gerados no navegador para explorar os imóveis no mapa.

## Exemplo de Execução

```bash
cd OlxPython
python OlxApartamentosCompra.py
cd ..
python Processamento.py
python Mapa.py
start mapas_imoveis_gerados/mapa_resultados_apartamento_venda.html
```

## Dicas de Manutenção

- **Atualização de ChromeDriver**: Sempre que o Chrome for atualizado, baixe a versão correspondente do ChromeDriver.
- **Cache de Geocodificação**: O arquivo `geocode_cache.json` armazena endereços já convertidos para coordenadas, acelerando execuções futuras.
- **Adição de Novos Portais**: Crie um novo diretório e scripts seguindo o padrão dos existentes.
- **Customização de Mapas**: Edite `Mapa.py` para alterar faixas de preço, cores, filtros, etc.

## Possíveis Problemas e Soluções

- **Timeout no Selenium**: Verifique a conexão de internet e se o ChromeDriver está correto.
- **Erros de Importação**: Certifique-se de que todas as dependências do `requirements.txt` estão instaladas.
- **Dados Duplicados**: O processamento já remove duplicatas, mas revise os scripts de raspagem para evitar inconsistências.
- **Mudanças no Layout dos Portais**: Caso algum portal mude o HTML, será necessário ajustar os seletores nos scripts de raspagem.

## Licença e Créditos

- **Autor:** Ryan Pablo
- **Licença:** MIT
- **Documentação e manutenção:** Consulte a pasta `documentação/` para guias detalhados e instruções de manutenção.

---

Se precisar de suporte ou quiser contribuir, fique à vontade para abrir uma issue ou enviar um pull request!
