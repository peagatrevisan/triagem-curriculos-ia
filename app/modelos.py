"""Estruturas de dados da triagem: o que entra (vaga, candidato) e o que sai (avaliações)."""
from enum import Enum

from pydantic import BaseModel, Field


# ---------- Entrada ----------
class Requisito(BaseModel):
    nome: str
    obrigatorio: bool = True
    # Só é usado no modo simulado (sem chave de API), que faz uma busca simples
    # por palavras. A avaliação real com IA ignora este campo.
    palavras_chave: list[str] = []


class PerguntaEliminatoria(BaseModel):
    """Pergunta fechada (Sim/Não) do questionário que elimina o candidato.

    Quem aplica a regra é o código, não a IA: o modelo só transcreve a
    pergunta e a resposta, e o código compara com a resposta exigida.
    """
    coluna: str                     # rótulo curto no relatório, ex.: "PRESENCIAL"
    trecho: str                     # parte do texto da pergunta, para localizá-la
    resposta_exigida: str = "Sim"


class Vaga(BaseModel):
    codigo: str
    titulo: str
    descricao: str = ""
    tempo_minimo_meses: int = 6
    requisitos: list[Requisito] = Field(min_length=1)
    perguntas_eliminatorias: list[PerguntaEliminatoria] = []
    # Linhas da seção "Validação documental" do parecer, preenchida pelo R&S
    documentos_exigidos: list[str] = ["Diploma ou declaração de conclusão", "Comprovação de experiência"]


class Candidato(BaseModel):
    """O que o sistema recebe de cada inscrição (no sistema real, capturado do ATS)."""
    id: str
    curriculo: str
    questionario: str = ""


# ---------- Saída do LLM (formato forçado via saída estruturada) ----------
class Status(str, Enum):
    ATENDE = "ATENDE"
    ATENDE_PARCIALMENTE = "ATENDE_PARCIALMENTE"
    NAO_ATENDE = "NAO_ATENDE"


class Evidencia(BaseModel):
    empresa: str = Field(description="Empresa ou instituição; vazio se não houver")
    cargo: str = Field(description="Cargo ou curso; vazio se não houver")
    periodo: str = Field(description="Período como aparece no currículo; vazio se não houver")
    descricao: str = Field(description="O que foi feito, em poucas palavras")


class AvaliacaoRequisito(BaseModel):
    requisito: str
    status: Status
    evidencias: list[Evidencia] = Field(description="Experiências que sustentam o status; lista vazia se nenhuma")
    justificativa: str = Field(description="Justificativa objetiva; se parcial, diga exatamente o que falta")
    alterado_pelo_questionario: bool = Field(
        description="true se o status só melhorou por causa das respostas do questionário"
    )


class RespostaFechada(BaseModel):
    pergunta: str = Field(description="Pergunta Sim/Não exatamente como aparece no questionário")
    resposta: str = Field(description="Resposta selecionada pelo candidato: Sim ou Não")


class AvaliacaoLLM(BaseModel):
    avaliacoes: list[AvaliacaoRequisito]
    respostas_fechadas: list[RespostaFechada] = Field(
        description="Todas as perguntas Sim/Não do questionário com a resposta, sem resumir"
    )
    observacao_final: str = Field(
        description="Requisitos que passaram a ser atendidos por causa do questionário e qual informação justificou; vazio se nenhum"
    )
    resumo: str = Field(description="Uma ou duas frases sobre a aderência do candidato à vaga")


# ---------- Resultado consolidado ----------
class Classificacao(str, Enum):
    ADERENTE = "ADERENTE"
    PARCIALMENTE_ADERENTE = "PARCIALMENTE_ADERENTE"
    NAO_ADERENTE = "NAO_ADERENTE"
    REVISAO_MANUAL = "REVISAO_MANUAL"


class ResultadoCandidato(BaseModel):
    id: str
    classificacao: Classificacao
    nota: float = 0.0
    obrigatorios_atendidos: str = ""
    avaliacoes: list[AvaliacaoRequisito] = []
    eliminatorias: dict[str, str] = {}   # coluna -> resposta do candidato
    motivo: str = ""                     # por que foi eliminado ou foi para revisão manual
    observacao_final: str = ""
    resumo: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0


class ResumoTriagem(BaseModel):
    id: str
    vaga: Vaga
    modo: str
    total: int
    retomados: int = 0
    por_classificacao: dict[str, int]
    segundos: float
    tokens_entrada: int
    tokens_saida: int
    custo_estimado_usd: float | None
    resultados: list[ResultadoCandidato]
