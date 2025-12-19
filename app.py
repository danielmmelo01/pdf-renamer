import streamlit as st
import io
import zipfile
import re
import os
import unicodedata
import requests
from pypdf import PdfReader, PdfWriter
from streamlit_lottie import st_lottie

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="IntelliGrid - Organizador de Pagamentos",
    page_icon="⚡",
    layout="centered"
)

# --- CARREGAR ANIMAÇÃO LOTTIE ---
def load_lottieurl(url: str):
    """Carrega animação Lottie de uma URL."""
    try:
        r = requests.get(url)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

# URL de uma animação de sucesso (check azul/verde moderno)
lottie_success_url = "https://lottie.host/6923610b-5066-43e6-a206-52732c847fdf/a523392b-6267-4a20-8605-000343300533.json"
lottie_success_anim = load_lottieurl(lottie_success_url)

# --- ESTILIZAÇÃO CSS (TEMA INTELLIGRID) ---
st.markdown("""
    <style>
        .main {
            background-color: #f8f9fa; # Fundo claro
        }
        h1 {
            color: #005eb8; # Azul IntelliGrid
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            font-weight: 700;
        }
        .stMarkdown p strong {
             color: #005eb8;
        }
        /* Estilo dos Botões */
        .stButton>button {
            background-color: #005eb8;
            color: white;
            border-radius: 8px;
            border: none;
            padding: 12px 28px;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0, 94, 184, 0.2);
        }
        .stButton>button:hover {
            background-color: #004a99;
            box-shadow: 0 6px 8px rgba(0, 94, 184, 0.3);
            transform: translateY(-2px);
        }
        /* Área de Upload */
        [data-testid='stFileUploader'] {
            border: 2px dashed #a0c4e3;
            border-radius: 12px;
            padding: 20px;
            background-color: #f0f7fc;
        }
        /* Caixas de Sucesso/Erro */
        .stAlert {
            border-radius: 8px;
        }
    </style>
""", unsafe_allow_html=True)

# --- FUNÇÕES AUXILIARES DE PROCESSAMENTO ---

def sanitize_filename(text):
    """Remove caracteres inválidos e normaliza para nome de arquivo."""
    if not text: return "GLOSA"
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = re.sub(r'[^\w\s-]', '', text).strip()
    return text

def extract_info(text):
    """
    Extrai Banco (Restrito a Sicredi, BB, Caixa), Beneficiário e Valor.
    """
    text_upper = text.upper()
    
    # 1. Identificar Banco (Restrito aos 3 solicitados)
    # Mapeamento para nome padrão no arquivo
    bancos_map = {
        "SICREDI": "SICREDI",
        "BANCO DO BRASIL": "BB",
        "CAIXA": "CAIXA"
    }
    
    banco_detectado = "OUTRO_BANCO"
    
    # Usa regex com boundary (\b) para evitar falsos positivos em palavras compostas
    for nome_busca, nome_arquivo in bancos_map.items():
        # Escapa caracteres especiais se houver e adiciona boundaries
        pattern = r"\b" + re.escape(nome_busca) + r"\b"
        if re.search(pattern, text_upper):
            banco_detectado = nome_arquivo
            # Prioridade: se achou um, para. (Assumindo que não há dois bancos no mesmo comprovante)
            break
            
    # 2. Identificar Valor (Padrão R$ X.XXX,XX ou X.XXX,XX)
    padrao_valor = r'(?:R\$\s?)?(\d{1,3}(?:\.\d{3})*,\d{2})\b'
    match_valor = re.search(padrao_valor, text)
    valor_formatado = "0"
    
    if match_valor:
        valor_str = match_valor.group(1)
        try:
            # Converte para float (remove ponto de milhar, troca vírgula por ponto)
            valor_float = float(valor_str.replace('.', '').replace(',', '.'))
            # Trunca para inteiro conforme solicitado
            valor_formatado = str(int(valor_float))
        except:
            valor_formatado = "ERRO_VALOR"

    # 3. Identificar Beneficiário (Busca por palavras-chave comuns)
    beneficiario = "DESCONHECIDO"
    # Padrões comuns em comprovantes dos bancos citados
    padroes_benef = [
        r'(?:BENEFICIÁRIO|FAVORECIDO|DESTINATÁRIO|PAGO A|NOME DO RECEBEDOR)[:\s]+(.+)',
        r'(?:PARA)[:\s]+(.+)' # Comum no Sicredi
    ]
    
    for padrao in padroes_benef:
        match_benef = re.search(padrao, text, re.IGNORECASE)
        if match_benef:
            # Pega a primeira linha encontrada após o marcador
            beneficiario_raw = match_benef.group(1).strip()
            # Pega apenas a primeira linha se houver quebra
            beneficiario = beneficiario_raw.split('\n')[0] 
            break
        
    # Truncar beneficiário (max 30 chars)
    beneficiario = beneficiario[:30].strip()
    
    return banco_detectado, beneficiario, valor_formatado

def process_pdf(file_bytes, filename_original):
    """Processa um PDF, separa páginas e renomeia."""
    processed_files = []
    
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        
        if len(reader.pages) == 0:
             st.warning(f"Arquivo {filename_original} está vazio ou corrompido.")
             return []

        for i, page in enumerate(reader.pages):
            # Extrair texto da página
            text = page.extract_text()
            
            if not text or len(text.strip()) < 10:
                # Fallback básico se não extrair texto (ex: página em branco ou imagem pura sem OCR)
                text = "Geração de imagem não suportada nesta versão"
                banco, beneficiario, valor = "ERRO_LEITURA", "Verificar_Manual", "0"
            else:
                # Extrair dados com a lógica de negócios
                banco, beneficiario, valor = extract_info(text)
            
            # Montar novo nome
            # Formato: pagamento + nome do banco - nome do beneficiário + valor
            banco_clean = sanitize_filename(banco)
            beneficiario_clean = sanitize_filename(beneficiario)
            
            new_name = f"pagamento {banco_clean} - {beneficiario_clean} {valor}.pdf"
            
            # Criar novo PDF de uma página na memória
            writer = PdfWriter()
            writer.add_page(page)
            output_pdf = io.BytesIO()
            writer.write(output_pdf)
            output_pdf.seek(0)
            
            processed_files.append({
                "name": new_name,
                "data": output_pdf,
                "original_source": filename_original,
                "page_num": i+1,
                "is_multi_page": len(reader.pages) > 1
            })
            
    except Exception as e:
        st.error(f"Erro crítico ao ler {filename_original}: {str(e)}")
        
    return processed_files

# --- INTERFACE PRINCIPAL ---

# Cabeçalho com Logo (Placeholder) e Título
col_logo, col_title = st.columns([1, 5])
with col_logo:
    # Usei um ícone de raio genérico, idealmente seria o logo da empresa
    st.markdown("<div style='font-size: 4rem; text-align: center;'>⚡</div>", unsafe_allow_html=True)
with col_title:
    st.title("IntelliGrid Renamer")
    st.markdown("Ferramenta para padronização de comprovantes de pagamento.")

st.markdown("---")
st.info("Bancos suportados nesta versão: **Sicredi, Banco do Brasil, Caixa**.")

# Área de Upload
uploaded_files = st.file_uploader(
    "Solte seus arquivos aqui (PDF único, múltiplos PDFs ou ZIP)", 
    type=['pdf', 'zip'], 
    accept_multiple_files=True
)

if uploaded_files:
    # Botão de ação principal
    if st.button("Iniciar Processamento e Renomeação", type="primary"):
        all_processed = []
        
        # Barra de progresso e spinner
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processando arquivo {idx+1}/{total_files}: {uploaded_file.name}...")
            
            # Tratamento de ZIP
            if uploaded_file.name.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(uploaded_file) as z:
                        pdf_files_in_zip = [f for f in z.namelist() if f.lower().endswith('.pdf') and not f.startswith('__MACOSX')]
                        for zip_idx, filename in enumerate(pdf_files_in_zip):
                            status_text.text(f"Lendo ZIP {uploaded_file.name}: {filename}...")
                            with z.open(filename) as f:
                                pdf_bytes = f.read()
                                results = process_pdf(pdf_bytes, filename)
                                all_processed.extend(results)
                except zipfile.BadZipFile:
                    st.error(f"O arquivo {uploaded_file.name} é um ZIP inválido.")
            
            # Tratamento de PDF individual
            elif uploaded_file.name.lower().endswith('.pdf'):
                 results = process_pdf(uploaded_file.getvalue(), uploaded_file.name)
                 all_processed.extend(results)
            
            # Atualiza barra de progresso
            progress_bar.progress((idx + 1) / total_files)
            
        progress_bar.empty()
        status_text.empty()
        
        # --- TELA DE RESULTADOS COM ANIMAÇÃO ---
        if all_processed:
            st.markdown("---")
            
            # Exibe a animação Lottie de sucesso
            if lottie_success_anim:
                st_lottie(lottie_success_anim, height=120, key="success_animation")
            
            st.success(f"Sucesso! {len(all_processed)} comprovantes foram processados e renomeados.")
            
            # Preparar ZIP final para download de tudo
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                seen_names = {}
                for item in all_processed:
                    # Lógica para evitar sobrescrever arquivos com nomes idênticos
                    filename = item["name"]
                    if filename in seen_names:
                        seen_names[filename] += 1
                        name_part, ext = os.path.splitext(filename)
                        filename = f"{name_part} ({seen_names[filename]}){ext}"
                    else:
                        seen_names[filename] = 0
                        
                    zf.writestr(filename, item["data"].getvalue())
            
            # Botão de Download Principal (ZIP)
            st.download_button(
                label="📦 BAIXAR TODOS OS ARQUIVOS RENOMEADOS (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="Comprovantes_IntelliGrid_Processados.zip",
                mime="application/zip",
                use_container_width=True
            )
            
            # Visualização Individual (Expander para não poluir a tela)
            with st.expander("Visualizar e Baixar Arquivos Individualmente"):
                st.caption("Abaixo estão os arquivos gerados. Clique no botão ao lado para baixar um específico.")
                for item in all_processed:
                    col_desc, col_btn = st.columns([4, 1])
                    with col_desc:
                        st.markdown(f"**📄 {item['name']}**")
                        origin_info = f"Origem: {item['original_source']}"
                        if item['is_multi_page']:
                            origin_info += f" (Página {item['page_num']})"
                        st.caption(origin_info)
                    with col_btn:
                         st.download_button(
                            label="⬇️ Baixar",
                            data=item['data'],
                            file_name=item['name'],
                            mime="application/pdf",
                            key=f"btn_{item['name']}_{item['page_num']}" # Key única necessária
                        )
        else:
             st.warning("Nenhum arquivo PDF válido foi encontrado para processar.")

# --- RODAPÉ ---
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #6c757d; font-size: 0.8em;'>"
    "IntelliGrid Tools v1.2 | Desenvolvido para uso interno."
    "</div>", 
    unsafe_allow_html=True

)
