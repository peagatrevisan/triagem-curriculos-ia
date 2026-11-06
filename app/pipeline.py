"""Orquestra a triagem: lê, anonimiza, avalia em paralelo, classifica e ordena."""
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .config import config
from .extracao import ler_candidato
from .modelos import Classificacao, ResultadoCandidato, ResumoTriagem, Vaga
from .privacidade import anonimizar
from .ranking import classificar, ordenar


def _triar_um(avaliador, vaga: Vaga, nome: str, conteudo: bytes) -> ResultadoCandidato:
    try:
        candidato = ler_candidato(nome, conteudo)
    except Exception as erro:
        return ResultadoCandidato(id=nome, classificacao=Classificacao.REVISAO_MANUAL,
                                  motivo=f"Não foi possível ler o arquivo: {erro}")

    if len(candidato.curriculo) < config.MIN_CARACTERES_TEXTO:
        return ResultadoCandidato(
            id=candidato.id, classificacao=Classificacao.REVISAO_MANUAL,
            motivo=(f"Pouco texto extraído ({len(candidato.curriculo)} caracteres). "
                    "Provavelmente é um PDF escaneado; precisa de leitura humana ou OCR."),
        )

    try:
        avaliacao, tokens_in, tokens_out = avaliador.avaliar(
            vaga, anonimizar(candidato.curriculo), anonimizar(candidato.questionario)
        )
    except Exception as erro:
        return ResultadoCandidato(id=candidato.id, classificacao=Classificacao.REVISAO_MANUAL,
                                  motivo=f"Falha na avaliação automática: {erro}")

    classificacao, nota, atendidos, eliminatorias, motivo = classificar(vaga, avaliacao)
    return ResultadoCandidato(
        id=candidato.id, classificacao=classificacao, nota=nota, obrigatorios_atendidos=atendidos,
        avaliacoes=avaliacao.avaliacoes, eliminatorias=eliminatorias, motivo=motivo,
        observacao_final=avaliacao.observacao_final, resumo=avaliacao.resumo,
        tokens_entrada=tokens_in, tokens_saida=tokens_out,
    )


def triar(
    vaga: Vaga,
    arquivos: list[tuple[str, bytes]],
    avaliador,
    anteriores: list[ResultadoCandidato] | None = None,
    ao_concluir: Callable[[ResultadoCandidato], None] | None = None,
) -> ResumoTriagem:
    """Tria os arquivos em paralelo.

    Retomada: `anteriores` traz candidatos já avaliados numa execução que
    caiu no meio; eles não são reenviados à IA. `ao_concluir` é chamado a cada
    candidato terminado, para gravar o progresso na hora.
    """
    anteriores = anteriores or []
    ja_feitos = {r.id for r in anteriores}
    pendentes = [(n, c) for n, c in arquivos if _id_provavel(n, c) not in ja_feitos]

    def tarefa(arquivo):
        resultado = _triar_um(avaliador, vaga, *arquivo)
        if ao_concluir:
            ao_concluir(resultado)
        return resultado

    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=config.MAX_CONCORRENCIA) as executor:
        novos = list(executor.map(tarefa, pendentes))
    segundos = round(time.perf_counter() - inicio, 1)

    resultados = anteriores + novos
    tokens_in = sum(r.tokens_entrada for r in novos)
    tokens_out = sum(r.tokens_saida for r in novos)
    custo = None
    if config.PRECO_ENTRADA_USD_1M or config.PRECO_SAIDA_USD_1M:
        custo = round(tokens_in / 1e6 * config.PRECO_ENTRADA_USD_1M + tokens_out / 1e6 * config.PRECO_SAIDA_USD_1M, 4)

    contagem = Counter(r.classificacao.value for r in resultados)
    return ResumoTriagem(
        id=uuid.uuid4().hex[:8], vaga=vaga, modo=avaliador.modo, total=len(resultados),
        retomados=len(anteriores),
        por_classificacao={c.value: contagem.get(c.value, 0) for c in Classificacao},
        segundos=segundos, tokens_entrada=tokens_in, tokens_saida=tokens_out,
        custo_estimado_usd=custo, resultados=ordenar(resultados),
    )


def _id_provavel(nome: str, conteudo: bytes) -> str:
    try:
        return ler_candidato(nome, conteudo).id if nome.lower().endswith(".json") else nome
    except Exception:
        return nome
