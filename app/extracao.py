"""
Leitura dos candidatos.

- .json: o formato que o sistema real recebe da extensão do navegador, com o
  texto do currículo e as respostas do questionário já capturados do ATS.
- .pdf, .docx, .txt: só o currículo, para quem não usa ATS.
"""
import io
import json
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from .modelos import Candidato

FORMATOS_ACEITOS = {".json", ".pdf", ".docx", ".txt"}


def extrair_texto(nome_arquivo: str, conteudo: bytes) -> str:
    extensao = Path(nome_arquivo).suffix.lower()
    if extensao == ".pdf":
        leitor = PdfReader(io.BytesIO(conteudo))
        return "\n".join((pagina.extract_text() or "") for pagina in leitor.pages).strip()
    if extensao == ".docx":
        documento = Document(io.BytesIO(conteudo))
        return "\n".join(p.text for p in documento.paragraphs).strip()
    if extensao == ".txt":
        return conteudo.decode("utf-8", errors="ignore").strip()
    raise ValueError(f"Formato não suportado: {extensao} (aceitos: {', '.join(sorted(FORMATOS_ACEITOS))})")


def ler_candidato(nome_arquivo: str, conteudo: bytes) -> Candidato:
    if Path(nome_arquivo).suffix.lower() == ".json":
        dados = json.loads(conteudo.decode("utf-8"))
        dados.setdefault("id", Path(nome_arquivo).stem)
        return Candidato.model_validate(dados)
    return Candidato(id=Path(nome_arquivo).name, curriculo=extrair_texto(nome_arquivo, conteudo))
