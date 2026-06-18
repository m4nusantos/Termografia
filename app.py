"""Leitor de Termografia — extrai a temperatura escrita nas imagens.

App web (Streamlit) que lê em lote (até ~300) imagens de termografia e usa OCR
para identificar o valor de temperatura impresso na foto.

Funciona de DUAS formas, sem mudar o código:

* Na NUVEM (Streamlit Cloud / Hugging Face Spaces): usa o motor Tesseract, que
  é instalado no servidor pelo arquivo ``packages.txt``. Nada é instalado no
  seu computador.
* LOCAL (na sua máquina): usa o EasyOCR, instalado só com ``pip``, sem precisar
  de software de sistema.

O app detecta sozinho qual motor está disponível.
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

import ocr_backends as ocr

st.set_page_config(
    page_title="Leitor de Termografia",
    page_icon="🌡️",
    layout="wide",
)


# Formatos de imagem aceitos.
ACCEPTED_TYPES = ["jpg", "jpeg", "png", "bmp", "tif", "tiff"]

# ==========================================================================  #
# >>> REGIÃO PADRÃO DA TEMPERATURA <<<
# Estes são os valores com que o app JÁ ABRE (em % da imagem). Mude estes 4
# números para deixar o recorte certo das SUAS fotos pré-configurado.
#   - X: distância da borda ESQUERDA (0 = encostado à esquerda)
#   - Y: distância do TOPO          (0 = encostado em cima)
#   - LARGURA e ALTURA: tamanho do retângulo
# Você também pode ajustar tudo pelos controles da barra lateral durante o uso.
# ==========================================================================  #
REGIAO_PADRAO_X = 6        # %
REGIAO_PADRAO_Y = 0        # %
REGIAO_PADRAO_LARGURA = 21  # %
REGIAO_PADRAO_ALTURA = 12   # %


# --------------------------------------------------------------------------- #
# Funções auxiliares de recorte
# --------------------------------------------------------------------------- #
def box_to_pixels(img: Image.Image, box_pct: tuple[float, float, float, float]):
    """Converte (x%, y%, largura%, altura%) em coordenadas de pixel (l, t, r, b)."""
    w, h = img.size
    x, y, bw, bh = box_pct
    left = int(x / 100 * w)
    top = int(y / 100 * h)
    right = int((x + bw) / 100 * w)
    bottom = int((y + bh) / 100 * h)
    right = max(right, left + 1)
    bottom = max(bottom, top + 1)
    return left, top, right, bottom


def draw_region(img: Image.Image, box_pct) -> Image.Image:
    preview = img.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)
    left, top, right, bottom = box_to_pixels(img, box_pct)
    line_w = max(2, img.size[0] // 250)
    draw.rectangle([left, top, right, bottom], outline=(255, 40, 40), width=line_w)
    return preview


def crop_region(img: Image.Image, box_pct) -> Image.Image:
    return img.crop(box_to_pixels(img, box_pct))


def open_image(uploaded_file) -> Image.Image:
    """Abre um arquivo enviado como imagem RGB (reposiciona o ponteiro de leitura)."""
    uploaded_file.seek(0)
    return Image.open(uploaded_file).convert("RGB")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Temperaturas")
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Cabeçalho
# --------------------------------------------------------------------------- #
st.title("🌡️ Leitor de Termografia")
st.caption(
    "Envie suas imagens de termografia e o app identifica a temperatura escrita "
    "na foto. As imagens são processadas na memória e **não são salvas** no "
    "servidor."
)

backends = ocr.available_backends()

if not backends:
    st.error(
        "Nenhum motor de OCR foi encontrado neste ambiente.\n\n"
        "- **Na nuvem (Tesseract):** confira se o arquivo `packages.txt` contém "
        "`tesseract-ocr`.\n"
        "- **Local (EasyOCR):** rode `pip install -r requirements-local.txt`."
    )
    st.stop()


# --------------------------------------------------------------------------- #
# Barra lateral — configurações
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("⚙️ Configurações")

    backend = st.selectbox(
        "Motor de OCR",
        options=backends,
        help="Tesseract = nuvem · EasyOCR = local. Detectado automaticamente.",
    )
    st.success(f"Motor ativo: **{backend}**")

    st.divider()
    st.subheader("Região da temperatura")
    use_full = st.checkbox(
        "Usar a imagem inteira (sem recorte)",
        value=False,
        help="Desmarque para ler apenas a região onde o número aparece. "
        "Como a temperatura fica sempre na mesma posição, recortar melhora muito "
        "a precisão.",
    )

    if use_full:
        box_pct = (0.0, 0.0, 100.0, 100.0)
    else:
        st.caption("Ajuste o retângulo (em % da imagem). O mesmo recorte vale para todas.")
        col_a, col_b = st.columns(2)
        with col_a:
            x = st.slider("X (esquerda) %", 0, 100, REGIAO_PADRAO_X)
            w = st.slider("Largura %", 1, 100, REGIAO_PADRAO_LARGURA)
        with col_b:
            y = st.slider("Y (topo) %", 0, 100, REGIAO_PADRAO_Y)
            h = st.slider("Altura %", 1, 100, REGIAO_PADRAO_ALTURA)
        box_pct = (float(x), float(y), float(w), float(h))

    st.divider()
    with st.expander("Opções avançadas"):
        upscale = st.slider("Ampliação da região (zoom)", 1, 5, 3)
        try_both = st.checkbox(
            "Tentar texto claro e escuro", value=True,
            help="Testa as duas polaridades e usa a que achar um número.",
        )
        psm = st.select_slider(
            "Modo de segmentação (Tesseract)",
            options=[6, 7, 8, 11, 13],
            value=7,
            help="7 = uma linha de texto. 8 = uma palavra. Só afeta o Tesseract.",
        )

        st.markdown("**Faixa plausível de temperatura**")
        usar_faixa = st.checkbox(
            "Ignorar valores fora da faixa", value=False,
            help="Sinaliza/descarta leituras absurdas (ex.: 365 quando o certo é "
            "~36,5 — erro comum de ponto decimal). Defina o intervalo esperado.",
        )
        if usar_faixa:
            fc1, fc2 = st.columns(2)
            min_val = fc1.number_input("Mínima", value=0.0, step=1.0)
            max_val = fc2.number_input("Máxima", value=150.0, step=1.0)
        else:
            min_val = None
            max_val = None

    st.divider()
    unit = st.radio("Unidade exibida", ["°C", "°F", "—"], horizontal=True, index=0)


# --------------------------------------------------------------------------- #
# Upload das imagens
# --------------------------------------------------------------------------- #
# Chave dinâmica do uploader: ao incrementá-la, o widget "esquece" os arquivos
# enviados — é assim que o botão "Limpar" zera a seleção.
if "uploader_key" not in st.session_state:
    st.session_state["uploader_key"] = 0

files = st.file_uploader(
    "📤 Selecione as imagens de termografia (pode selecionar várias de uma vez)",
    type=ACCEPTED_TYPES,
    accept_multiple_files=True,
    key=f"uploader_{st.session_state['uploader_key']}",
)

# Botão para limpar as imagens e os resultados e iniciar uma nova leitura.
if st.button("🗑️ Limpar imagens e resultados"):
    st.session_state["uploader_key"] += 1
    st.session_state.pop("resultados", None)
    st.rerun()

if not files:
    st.info(
        "Selecione suas imagens para começar. Dica: para muitas fotos, "
        "selecione todas de uma vez na janela de upload."
    )
    st.stop()

st.write(f"**{len(files)} imagem(ns)** selecionada(s).")

# Pré-visualização do recorte na primeira imagem.
try:
    first_img = open_image(files[0])
except Exception:
    st.error("Não foi possível abrir a primeira imagem.")
    st.stop()

if not use_full:
    st.subheader("👁️ Conferência da região")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.image(draw_region(first_img, box_pct), caption="Região selecionada (vermelho)", use_container_width=True)
    with col2:
        st.image(crop_region(first_img, box_pct), caption="Recorte que será lido", use_container_width=True)

    left, top, right, bottom = box_to_pixels(first_img, box_pct)
    st.caption(
        f"Ajuste os controles na barra lateral até o retângulo cercar só o número. "
        f"Região na 1ª imagem ({first_img.width}×{first_img.height} px): "
        f"x {left}→{right}, y {top}→{bottom}  ·  "
        f"em %: X={box_pct[0]:.0f} · Y={box_pct[1]:.0f} · Largura={box_pct[2]:.0f} · Altura={box_pct[3]:.0f}"
    )


# --------------------------------------------------------------------------- #
# Visualizador de uma imagem enviada
# --------------------------------------------------------------------------- #
with st.expander("🖼️ Visualizar / testar uma imagem específica"):
    nomes = [f.name for f in files]
    rotulos = [f"{i + 1}. {nome}" for i, nome in enumerate(nomes)]
    idx = rotulos.index(
        st.selectbox("Escolha a imagem", rotulos, key="visualizar_sel")
    )
    sel_img = open_image(files[idx])

    vcol1, vcol2 = st.columns([3, 1])
    with vcol1:
        img_mostrar = sel_img if use_full else draw_region(sel_img, box_pct)
        st.image(img_mostrar, caption=nomes[idx], use_container_width=True)
    with vcol2:
        if not use_full:
            st.image(
                crop_region(sel_img, box_pct),
                caption="Recorte lido",
                use_container_width=True,
            )

    # Mostra o que já foi lido para esta imagem (se o lote já rodou).
    if "resultados" in st.session_state:
        nome_sel = nomes[idx]
        linha = st.session_state["resultados"].query("Arquivo == @nome_sel")
        if not linha.empty:
            r = linha.iloc[0]
            st.write(
                f"**Temperatura lida:** {r['Temperatura']} {r['Unidade']}  ·  "
                f"**Status:** {r['Status']}"
            )
            st.caption(f"Texto bruto do OCR: `{r['Texto lido (OCR)']}`")

    # Testa a leitura só nesta imagem, com as configurações atuais — útil para
    # ajustar a região/zoom nas fotos que falharam, sem reprocessar o lote todo.
    if st.button("🔍 Testar leitura nesta imagem", key="testar_uma"):
        regiao_teste = sel_img if use_full else crop_region(sel_img, box_pct)
        txt, vals = ocr.extract_temperature(
            regiao_teste,
            backend=backend,
            psm=psm,
            upscale=upscale,
            try_both_polarities=try_both,
            min_val=min_val,
            max_val=max_val,
        )
        if vals:
            extra = unit if unit != "—" else ""
            st.success(f"Leu: **{vals[0]} {extra}**  ·  todos os valores: {vals}")
        else:
            st.warning(
                "Não identifiquei número aqui. Tente aumentar a 'Ampliação' nas "
                "opções avançadas, ajustar a região ou marcar 'texto claro e escuro'."
            )
        st.caption(f"Texto bruto do OCR: `{txt}`")


# --------------------------------------------------------------------------- #
# Processamento em lote
# --------------------------------------------------------------------------- #
if st.button("🔍 Ler temperaturas de todas as imagens", type="primary"):
    rows = []
    progress = st.progress(0.0, text="Processando...")
    n = len(files)

    for i, f in enumerate(files, start=1):
        try:
            img = open_image(f)
            region = crop_region(img, box_pct)
            raw_text, values = ocr.extract_temperature(
                region,
                backend=backend,
                psm=psm,
                upscale=upscale,
                try_both_polarities=try_both,
                min_val=min_val,
                max_val=max_val,
            )
            principal = values[0] if values else None
            todos = ", ".join(str(v) for v in values) if values else ""
            rows.append(
                {
                    "Arquivo": f.name,
                    "Temperatura": principal,
                    "Unidade": unit if unit != "—" else "",
                    "Todos os valores": todos,
                    "Texto lido (OCR)": raw_text,
                    "Status": "OK" if values else "Não identificado",
                }
            )
        except Exception as exc:  # uma imagem ruim não derruba o lote
            rows.append(
                {
                    "Arquivo": getattr(f, "name", "?"),
                    "Temperatura": None,
                    "Unidade": "",
                    "Todos os valores": "",
                    "Texto lido (OCR)": f"ERRO: {exc}",
                    "Status": "Erro",
                }
            )

        progress.progress(i / n, text=f"Processando {i}/{n}...")

    progress.empty()
    st.session_state["resultados"] = pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Resultados (editáveis) + downloads
# --------------------------------------------------------------------------- #
if "resultados" in st.session_state:
    df = st.session_state["resultados"]

    ok = int((df["Status"] == "OK").sum())
    total = len(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Imagens", total)
    c2.metric("Identificadas", ok)
    c3.metric("Para revisar", total - ok)

    st.subheader("📋 Resultados (você pode corrigir antes de baixar)")
    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Temperatura": st.column_config.NumberColumn("Temperatura", format="%.2f"),
        },
        key="editor",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "⬇️ Baixar Excel (.xlsx)",
            data=to_excel_bytes(edited),
            file_name=f"temperaturas_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with col_dl2:
        st.download_button(
            "⬇️ Baixar CSV",
            data=edited.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"temperaturas_{stamp}.csv",
            mime="text/csv",
        )
