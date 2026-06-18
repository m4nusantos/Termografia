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
) -> Image.Image:
    """Limpa a imagem para melhorar a taxa de acerto do OCR.

    Passos: tons de cinza -> autocontraste -> ampliação -> binarização (Otsu).
    A ``invert`` é útil porque termografia tanto pode ter texto claro em fundo
    escuro quanto o contrário.
    """
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)

    if upscale > 1:
        gray = gray.resize(
            (gray.width * upscale, gray.height * upscale), Image.LANCZOS
        )

    if binarize:
        arr = np.asarray(gray)
        t = _otsu_threshold(arr)
        bw = (arr > t).astype(np.uint8) * 255
        if invert:
            bw = 255 - bw
        return Image.fromarray(bw)

    if invert:
        return ImageOps.invert(gray)
    return gray


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
def parse_temperatures(text: str) -> list[float]:
    """Extrai todos os números de temperatura plausíveis do texto do OCR."""
    values: list[float] = []
    for raw in _TEMP_RE.findall(text.replace(" ", "")):
        try:
            values.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return values


def extract_temperature(
    img: Image.Image,
    backend: str,
    psm: int = 7,
    upscale: int = 3,
    try_both_polarities: bool = True,
) -> tuple[str, list[float]]:
    """Roda o pipeline completo em UMA imagem (já recortada na região do número).

    Retorna ``(texto_bruto_do_ocr, lista_de_valores)``. Tenta as duas
    polaridades (texto claro/escuro) e devolve a primeira que produzir números.
    """
    polarities = [False, True] if try_both_polarities else [False]
    best_text = ""
    for invert in polarities:
        proc = preprocess(img, upscale=upscale, binarize=True, invert=invert)
        text = run_ocr(proc, backend, psm=psm).strip()
        values = parse_temperatures(text)
        if values:
            return text, values
        if not best_text:
            best_text = text
    return best_text, []
