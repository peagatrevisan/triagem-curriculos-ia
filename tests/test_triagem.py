import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import main
from app.avaliacao import AvaliadorSimulado, alinhar_com_vaga
from app.modelos import (AvaliacaoLLM, AvaliacaoRequisito, Classificacao, RespostaFechada,
                         Status, Vaga)
from app.pipeline import triar
from app.privacidade import anonimizar
from app.ranking import classificar
from app.relatorio import gerar_saidas

RAIZ = Path(__file__).resolve().parent.parent
VAGA = Vaga.model_validate_json((RAIZ / "data" / "vaga_exemplo.json").read_text(encoding="utf-8"))
PASTA = RAIZ / "data" / "candidatos"
SIM_SIM = [
    RespostaFechada(pergunta="Você tem disponibilidade para trabalho presencial em Florianópolis/SC?", resposta="Sim"),
    RespostaFechada(pergunta="Você tem disponibilidade para início em até 30 dias?", resposta="Sim"),
]


def avaliacao(*status: str, fechadas=SIM_SIM) -> AvaliacaoLLM:
    return AvaliacaoLLM(
        avaliacoes=[
            AvaliacaoRequisito(requisito=r.nome, status=Status(s), evidencias=[], justificativa="",
                               alterado_pelo_questionario=False)
            for r, s in zip(VAGA.requisitos, status)
        ],
        respostas_fechadas=fechadas, observacao_final="", resumo="",
    )


TODOS = ("ATENDE",) * 6


# ---------- Regras de classificação ----------
def test_todos_obrigatorios_atendidos_e_aderente_mesmo_sem_desejaveis():
    classe, nota, obrig, _, _ = classificar(VAGA, avaliacao("ATENDE", "ATENDE", "ATENDE", "NAO_ATENDE", "NAO_ATENDE", "NAO_ATENDE"))
    assert classe == Classificacao.ADERENTE
    assert obrig == "3/3"
    assert nota == pytest.approx(66.7)


def test_obrigatorio_parcial_vira_parcialmente_aderente():
    classe, *_ = classificar(VAGA, avaliacao("ATENDE", "ATENDE_PARCIALMENTE", "ATENDE", "ATENDE", "ATENDE", "ATENDE"))
    assert classe == Classificacao.PARCIALMENTE_ADERENTE


def test_um_obrigatorio_nao_atendido_elimina_mesmo_com_nota_alta():
    classe, nota, _, _, motivo = classificar(VAGA, avaliacao("ATENDE", "ATENDE", "NAO_ATENDE", "ATENDE", "ATENDE", "ATENDE"))
    assert classe == Classificacao.NAO_ADERENTE
    assert nota > 60
    assert "SQL" in motivo


def test_pergunta_eliminatoria_elimina_candidato_que_atende_tudo():
    fechadas = [SIM_SIM[0].model_copy(update={"resposta": "Não"}), SIM_SIM[1]]
    classe, _, _, eliminatorias, motivo = classificar(VAGA, avaliacao(*TODOS, fechadas=fechadas))
    assert classe == Classificacao.NAO_ADERENTE
    assert eliminatorias["PRESENCIAL"] == "Não"
    assert "PRESENCIAL" in motivo


def test_pergunta_eliminatoria_nao_respondida_nao_elimina():
    classe, _, _, eliminatorias, _ = classificar(VAGA, avaliacao(*TODOS, fechadas=[]))
    assert classe == Classificacao.ADERENTE
    assert eliminatorias["PRESENCIAL"] == "não respondida"


def test_requisito_omitido_pelo_modelo_entra_como_nao_atende():
    completa = avaliacao(*TODOS)
    incompleta = completa.model_copy(update={"avaliacoes": completa.avaliacoes[:2]})
    alinhada = alinhar_com_vaga(VAGA, incompleta)
    assert len(alinhada.avaliacoes) == len(VAGA.requisitos)
    assert alinhada.avaliacoes[2].status == Status.NAO_ATENDE


# ---------- Privacidade ----------
def test_anonimizacao_remove_dados_pessoais():
    texto = (
        "Nome: Fulana de Tal\nData de nascimento: 01/01/2000\n"
        "CPF: 123.456.789-09 | E-mail: fulana@example.com | Telefone: (48) 99999-0000\n"
        "LinkedIn: linkedin.com/in/fulana\nAnalista de Dados com SQL"
    )
    limpo = anonimizar(texto)
    for dado in ["Fulana", "2000", "123.456.789-09", "fulana@example.com", "99999-0000", "linkedin.com"]:
        assert dado not in limpo
    assert "Analista de Dados com SQL" in limpo


# ---------- Fluxo completo (modo simulado, sem chamar API) ----------
def arquivos():
    return [(p.name, p.read_bytes()) for p in sorted(PASTA.iterdir())]


def test_pipeline_aplica_eliminatoria_e_manda_escaneado_para_revisao():
    resumo = triar(VAGA, arquivos(), AvaliadorSimulado())
    por_id = {r.id: r for r in resumo.resultados}
    assert resumo.total == len(arquivos())
    assert por_id["lucas_gabriel_nunes.pdf"].classificacao == Classificacao.REVISAO_MANUAL
    assert por_id["fernanda_lopes_martins"].motivo == "Pergunta eliminatória: PRESENCIAL"


def test_retomada_nao_reavalia_quem_ja_foi_avaliado():
    primeira = triar(VAGA, arquivos(), AvaliadorSimulado())
    anteriores = primeira.resultados[:5]
    chamados = []
    segunda = triar(VAGA, arquivos(), AvaliadorSimulado(), anteriores=anteriores, ao_concluir=chamados.append)
    assert segunda.total == len(arquivos())
    assert segunda.retomados == 5
    assert len(chamados) == len(arquivos()) - 5


def test_saidas_tem_abas_por_classificacao_e_um_word_por_candidato(tmp_path):
    resumo = triar(VAGA, arquivos(), AvaliadorSimulado())
    pacote = gerar_saidas(resumo, tmp_path)
    abas = load_workbook(tmp_path / "planilha.xlsx").sheetnames
    assert abas == ["Resumo", "Todos", "Atende", "Atende parcialmente", "Não atende", "Revisão manual"]
    with zipfile.ZipFile(pacote) as z:
        pareceres = [n for n in z.namelist() if n.startswith("pareceres/")]
    assert len(pareceres) == resumo.total


def test_api_gera_triagem_e_pacote(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "criar_avaliador", lambda: AvaliadorSimulado())
    monkeypatch.setattr(main, "PASTA_SAIDAS", tmp_path)
    cliente = TestClient(main.app)

    envio = [("vaga", ("vaga.json", json.dumps(VAGA.model_dump()), "application/json"))]
    envio += [("candidatos", (nome, conteudo)) for nome, conteudo in arquivos()[:4]]
    resposta = cliente.post("/api/triagem", files=envio)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["total"] == 4

    for arquivo in ["pacote", "planilha"]:
        baixado = cliente.get(f"/api/triagem/{corpo['id']}/{arquivo}")
        assert baixado.status_code == 200
        assert baixado.content[:2] == b"PK"  # .zip e .xlsx são zip


def test_api_recusa_formato_nao_suportado(monkeypatch):
    monkeypatch.setattr(main, "criar_avaliador", lambda: AvaliadorSimulado())
    cliente = TestClient(main.app)
    envio = [
        ("vaga", ("vaga.json", json.dumps(VAGA.model_dump()), "application/json")),
        ("candidatos", ("foto.png", b"x")),
    ]
    assert cliente.post("/api/triagem", files=envio).status_code == 422
