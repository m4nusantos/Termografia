# 🌡️ Leitor de Termografia

App web para ler, **em lote**, a temperatura que vem **escrita nas imagens de
termografia**. Você envia as fotos (até ~300), o app usa OCR para identificar o
número impresso e devolve uma tabela pronta para baixar em **Excel** ou **CSV**.

As imagens são processadas **na memória** e **não são salvas** no servidor. O
OCR roda **no próprio servidor, offline** — suas fotos **não** são enviadas para
nenhuma API externa de terceiros.

---

## Como funciona (duas formas, mesmo código)

O app detecta sozinho qual motor de OCR está disponível:

| Forma | Onde roda | Motor de OCR | Instala algo no seu PC? | Acessível a outras pessoas? |
|-------|-----------|--------------|--------------------------|------------------------------|
| **A — Nuvem** | Streamlit Cloud ou Hugging Face Spaces | **Tesseract** (instalado no servidor via `packages.txt`) | **Não** | **Sim** (link, pode ser privado) |
| **B — Local** | Sua máquina | **EasyOCR** (só `pip`, sem motor de sistema) | Não (só pacotes Python) | Não (só você) |

> **Por que duas formas?** O `pytesseract` é apenas um "controle remoto" do
> programa Tesseract, que precisa estar instalado na máquina que roda o app. No
> seu notebook corporativo isso é bloqueado — por isso, **localmente** usamos o
> **EasyOCR** (não precisa de instalação de sistema), e **na nuvem** usamos o
> **Tesseract** (instalado no servidor, não no seu PC).

---

## ▶️ Forma A — Publicar na nuvem (acessível a outras pessoas)

### A.1 — Streamlit Community Cloud (mais simples)

1. Suba este repositório para o **GitHub** (já está pronto: contém `app.py`,
   `requirements.txt` e `packages.txt`).
2. Acesse <https://share.streamlit.io> e entre com sua conta GitHub.
3. Clique em **"Create app" / "Deploy a public app from GitHub"**, escolha este
   repositório, branch e o arquivo `app.py`.
4. Clique em **Deploy**. O Streamlit instala o Tesseract automaticamente (lendo
   o `packages.txt`) e gera um endereço tipo `https://seu-app.streamlit.app`.

**Deixar privado (segurança, sem precisar de senha):**
no painel do app → **Settings → Sharing** → mude para **"Only specific people
can view this app"** e adicione os e-mails (Google) das pessoas autorizadas. Só
quem você convidar consegue abrir.

### A.2 — Hugging Face Spaces (alternativa ao Streamlit Cloud)

1. Crie um Space em <https://huggingface.co/new-space> → SDK **Streamlit**.
2. Suba os arquivos deste repositório (`app.py`, `requirements.txt`,
   `packages.txt`, pasta `.streamlit/`). O Spaces lê o `packages.txt` (apt) e
   instala o Tesseract no servidor.
3. **No topo do `README.md` do Space**, deixe o cabeçalho de configuração:

   ```yaml
   ---
   title: Leitor de Termografia
   emoji: 🌡️
   colorFrom: orange
   colorTo: red
   sdk: streamlit
   app_file: app.py
   pinned: false
   ---
   ```

4. **Deixar privado:** em **Settings → Visibility** do Space, escolha
   **Private** (só você/colaboradores convidados acessam).

---

## 💻 Forma B — Rodar local (sem instalar softwares de sistema)

Funciona em notebook corporativo restrito, pois usa só pacotes Python (`pip`).

1. Abra a pasta do projeto no **VSCode** e abra o terminal integrado.
2. (Recomendado) crie um ambiente isolado:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   ```
3. Instale as dependências locais:
   ```bash
   pip install -r requirements-local.txt
   ```
4. Rode o app:
   ```bash
   streamlit run app.py
   ```
5. O navegador abre em `http://localhost:8501`. Pronto.

> **1ª execução:** o EasyOCR baixa um modelo (~64 MB) uma única vez (precisa de
> internet só nesse momento). Depois funciona normalmente.
>
> **Compartilhar na rede interna:** outras pessoas na MESMA rede da empresa
> podem acessar pelo IP da sua máquina (ex.: `http://SEU-IP:8501`) enquanto o
> app estiver rodando. Para acesso "pela internet" de fato, use a Forma A.

---

## 🧭 Como usar o app

1. **Motor de OCR**: aparece automaticamente na barra lateral (Tesseract na
   nuvem, EasyOCR local).
2. **Região da temperatura**: como o número fica **sempre na mesma posição**,
   ajuste o retângulo (X, Y, Largura, Altura em %) na barra lateral. A
   pré-visualização mostra o recorte na 1ª foto — deixe o retângulo cercando só
   o número. Esse mesmo recorte é aplicado a todas as imagens (mais precisão).
3. Envie as imagens (pode selecionar várias de uma vez).
4. Clique em **"Ler temperaturas de todas as imagens"**.
5. Confira/corrija os valores na tabela (ela é editável) e baixe em **Excel** ou
   **CSV**.

**Opções avançadas** (barra lateral): ampliação do recorte, testar texto
claro/escuro e modo de segmentação do Tesseract — úteis se algum número não for
identificado.

---

## 🔒 Privacidade e segurança

- OCR **offline no servidor** — nenhuma foto é enviada a serviços externos.
- Imagens processadas **em memória**; **nada é salvo** em disco pelo app.
- Na nuvem, restrinja o acesso pela opção de app/Space **privado** (por e-mail).
- Não suba fotos sensíveis para o repositório Git (a pasta `amostras/` já está
  no `.gitignore`).

---

## 🗂️ Arquivos do projeto

| Arquivo | Para que serve |
|---------|----------------|
| `app.py` | Aplicação Streamlit (interface e fluxo) |
| `ocr_backends.py` | Pré-processamento + OCR (Tesseract e EasyOCR) |
| `requirements.txt` | Dependências da **nuvem** (Tesseract) |
| `packages.txt` | Instala o Tesseract no **servidor** da nuvem |
| `requirements-local.txt` | Dependências para rodar **local** (EasyOCR) |
| `.streamlit/config.toml` | Tamanho de upload e tema |
