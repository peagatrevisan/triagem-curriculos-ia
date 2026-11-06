"""API FastAPI da triagem. Rode com: uvicorn app.main:app --reload"""
import json
import re
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .avaliacao import criar_avaliador
from .config import PASTA_SAIDAS
from .extracao import FORMATOS_ACEITOS
from .modelos import ResumoTriagem, Vaga
from .pipeline import triar
from .relatorio import gerar_saidas

app = FastAPI(
    title="Triagem de currículos com IA",
    description=(
        "Avalia currículo e questionário de cada candidato contra os requisitos da vaga com o Gemini. "
        "Gera um Excel separado por classificação e um parecer em Word por candidato."
    ),
    version="2.0.0",
)

LIMITE_ARQUIVOS = 2000
ARQUIVOS_SAIDA = {"pacote": ("triagem.zip", "zip"), "planilha": ("planilha.xlsx", "xlsx")}


@app.get("/api/saude")
def saude():
    return {"status": "ok", "modo": criar_avaliador().modo}


@app.post("/api/triagem", response_model=ResumoTriagem)
async def criar_triagem(
    vaga: UploadFile = File(..., description="JSON com título, requisitos e perguntas eliminatórias da vaga"),
    candidatos: list[UploadFile] = File(..., description="Candidatos em JSON (currículo + questionário), PDF, DOCX ou TXT"),
):
    try:
        dados_vaga = Vaga.model_validate(json.loads(await vaga.read()))
    except (json.JSONDecodeError, ValidationError) as erro:
        raise HTTPException(422, f"Arquivo da vaga inválido: {erro}")

    if len(candidatos) > LIMITE_ARQUIVOS:
        raise HTTPException(413, f"Envie no máximo {LIMITE_ARQUIVOS} candidatos por vez.")

    arquivos = []
    for c in candidatos:
        nome = Path(c.filename or "sem_nome").name
        if Path(nome).suffix.lower() not in FORMATOS_ACEITOS:
            raise HTTPException(422, f"{nome}: formato não suportado.")
        arquivos.append((nome, await c.read()))

    resumo = triar(dados_vaga, arquivos, criar_avaliador())
    gerar_saidas(resumo, PASTA_SAIDAS / resumo.id)
    return resumo


@app.get("/api/triagem/{id_triagem}/{arquivo}")
def baixar(id_triagem: str, arquivo: str):
    """arquivo = 'pacote' (Excel + pareceres em Word, .zip) ou 'planilha' (.xlsx)."""
    if not re.fullmatch(r"[0-9a-f]{8}", id_triagem) or arquivo not in ARQUIVOS_SAIDA:
        raise HTTPException(404, "Não encontrado.")
    nome, extensao = ARQUIVOS_SAIDA[arquivo]
    caminho = PASTA_SAIDAS / id_triagem / nome
    if not caminho.exists():
        raise HTTPException(404, "Triagem não encontrada.")
    return FileResponse(caminho, filename=f"triagem_{id_triagem}.{extensao}")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
