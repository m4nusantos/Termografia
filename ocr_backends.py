"""Backends de OCR para leitura de temperatura em imagens de termografia.

Dois motores são suportados:

* ``Tesseract`` (via ``pytesseract``): precisa do programa ``tesseract-ocr``
  instalado no host. É o usado nas publicações em nuvem, onde o arquivo
  ``packages.txt`` instala o motor automaticamente no servidor.
* ``EasyOCR``: backend 100% pip, não precisa de motor de sistema separado.
  É o usado quando se roda localmente em uma máquina sem permissão para
  instalar softwares.

O app detecta sozinho quais backends estão disponíveis, então o MESMO código
roda na nuvem (Tesseract) e localmente (EasyOCR).
"""

from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageOps

# Caracteres que esperamos encontrar em um valor de temperatura.
WHITELIST = "0123456789.,-:°CFcf "

# Captura números como 36, 36.5, 36,5, -4.2, 100.0 ...
_TEMP_RE = re.compile(r"-?\d{1,3}(?:[.,]\d{1,2})?")


# --------------------------------------------------------------------------- #
# Detecção de disponibilidade dos backends
# --------------------------------------------------------------------------- #
def _tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401

        # Não basta importar: o binário precisa existir.
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401

        return True
    except Exception:
        return False


def available_backends() -> list[str]:
    """Lista os motores de OCR realmente utilizáveis neste ambiente."""
    backends: list[str] = []
    if _tesseract_available():
        backends.append("Tesseract")
    if _easyocr_available():
        backends.append("EasyOCR")
    return backends


# --------------------------------------------------------------------------- #
# Pré-processamento de imagem
# --------------------------------------------------------------------------- #
def _otsu_threshold(arr: np.ndarray) -> int:
    """Limiar de Otsu implementado em numpy (sem dependência do OpenCV)."""
    hist, _ = np.histogram(arr.ravel(), bins=256, range=(0, 256))
    total = arr.size
    sum_total = float(np.dot(np.arange(256), hist))
    sum_b = 0.0
    w_b = 0.0
    maximum = 0.0
    threshold = 127
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between >= maximum:
            maximum = between
            threshold = i
    return threshold


def preprocess(
    img: Image.Image,
    upscale: int = 3,
    binarize: bool = True,
    invert: bool = False,
    border: int = 0,
    target_height: int = 0,
) -> Image.Image:
    """Limpa a imagem para melhorar a taxa de acerto do OCR.

    Passos: tons de cinza -> autocontraste -> ampliação -> binarização (Otsu)
    -> borda. A ``invert`` é útil porque termografia tanto pode ter texto claro
    em fundo escuro quanto o contrário. ``target_height`` garante uma altura
    mínima do texto (o Tesseract acerta mais com letras grandes) e ``border``
    adiciona uma margem em volta (o Tesseract também acerta mais com folga).
    """
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)

    # Amplia: respeita o fator pedido, mas também garante uma altura mínima.
    scale = max(1, upscale)
    if target_height and gray.height:
        needed = -(-target_height // gray.height)  # divisão arredondada p/ cima
        scale = max(scale, needed)
    if scale > 1:
        gray = gray.resize(
            (gray.width * scale, gray.height * scale), Image.LANCZOS
        )

    if binarize:
        arr = np.asarray(gray)
        t = _otsu_threshold(arr)
        bw = (arr > t).astype(np.uint8) * 255
        if invert:
            bw = 255 - bw
        out = Image.fromarray(bw)
        # Texto preto em fundo branco (ou o inverso): a borda acompanha o fundo.
        fill = 0 if invert else 255
    else:
        out = ImageOps.invert(gray) if invert else gray
        fill = 0 if invert else 255

    if border > 0:
        out = ImageOps.expand(out, border=border, fill=fill)
    return out


# --------------------------------------------------------------------------- #
# Execução do OCR
# --------------------------------------------------------------------------- #
def _ocr_tesseract(img: Image.Image, psm: int = 7) -> str:
    import pytesseract

    config = f"--oem 3 --psm {psm} -c tessedit_char_whitelist={WHITELIST}"
    return pytesseract.image_to_string(img, config=config)


_easyocr_reader = None  # singleton em nível de processo (init é caro)


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr

        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _easyocr_reader


def _ocr_easyocr(img: Image.Image) -> str:
    reader = _get_easyocr_reader()
    allow = "0123456789.,-°CF"
    results = reader.readtext(
        np.asarray(img.convert("RGB")), allowlist=allow, detail=0
    )
    return " ".join(results)


def run_ocr(img: Image.Image, backend: str, psm: int = 7) -> str:
    if backend == "Tesseract":
        return _ocr_tesseract(img, psm=psm)
    if backend == "EasyOCR":
        return _ocr_easyocr(img)
    raise ValueError(f"Backend de OCR desconhecido: {backend}")


# --------------------------------------------------------------------------- #
# Interpretação do texto -> número de temperatura
# --------------------------------------------------------------------------- #
def parse_temperatures(
    text: str,
    min_val: float | None = None,
    max_val: float | None = None,
) -> list[float]:
    """Extrai os números de temperatura plausíveis do texto do OCR.

    Se ``min_val``/``max_val`` forem informados, descarta valores fora da faixa
    (ajuda a ignorar ruído do OCR, ex.: ``365`` quando você sabe que é ~36,5).
    """
    values: list[float] = []
    for raw in _TEMP_RE.findall(text.replace(" ", "")):
        try:
            v = float(raw.replace(",", "."))
        except ValueError:
            continue
        if min_val is not None and v < min_val:
            continue
        if max_val is not None and v > max_val:
            continue
        values.append(v)
    return values


def extract_temperature(
    img: Image.Image,
    backend: str,
    psm: int = 7,
    upscale: int = 3,
    try_both_polarities: bool = True,
    target_height: int = 300,
    min_val: float | None = None,
    max_val: float | None = None,
) -> tuple[str, list[float]]:
    """Roda o pipeline completo em UMA imagem (já recortada na região do número).

    Retorna ``(texto_bruto_do_ocr, lista_de_valores)``. Para ser robusto, tenta
    várias combinações até achar um número: polaridade (texto claro/escuro) x
    modos de segmentação do Tesseract. A imagem mais fácil é resolvida na 1ª
    tentativa; só as difíceis passam pelas demais (mantém o lote rápido).
    """
    polarities = [False, True] if try_both_polarities else [False]

    # Ordem de modos de leitura a tentar (começa pelo escolhido pelo usuário).
    if backend == "EasyOCR":
        psm_list = [psm]  # EasyOCR ignora PSM; basta 1 tentativa por variante.
    else:
        psm_list = []
        for p in [psm, 7, 8, 6, 13]:
            if p not in psm_list:
                psm_list.append(p)

    best_text = ""
    for invert in polarities:
        proc = preprocess(
            img,
            upscale=upscale,
            binarize=True,
            invert=invert,
            border=20,
            target_height=target_height,
        )
        for p in psm_list:
            text = run_ocr(proc, backend, psm=p).strip()
            values = parse_temperatures(text, min_val=min_val, max_val=max_val)
            if values:
                return text, values
            if not best_text:
                best_text = text
    return best_text, []
