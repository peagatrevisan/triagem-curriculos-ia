"""
Consolidação: transforma as avaliações por requisito em classificação e nota.

Decisão de projeto: o LLM avalia cada requisito e transcreve as respostas do
questionário, mas a classificação final (inclusive as perguntas eliminatórias)
é calculada por regra fixa no código. Assim o critério é igual para todos,
auditável e não varia entre chamadas.
"""
from .avaliacao import normalizar
from .modelos import AvaliacaoLLM, Classificacao, Status, Vaga

PONTOS = {Status.ATENDE: 1.0, Status.ATENDE_PARCIALMENTE: 0.5, Status.NAO_ATENDE: 0.0}
PESO_OBRIGATORIO = 2.0
PESO_DESEJAVEL = 1.0

ORDEM = {
    Classificacao.ADERENTE: 0,
    Classificacao.PARCIALMENTE_ADERENTE: 1,
    Classificacao.REVISAO_MANUAL: 2,  # nunca é eliminado sem uma pessoa olhar
    Classificacao.NAO_ADERENTE: 3,
}


def respostas_eliminatorias(vaga: Vaga, avaliacao: AvaliacaoLLM) -> dict[str, str]:
    """Localiza cada pergunta eliminatória entre as respostas transcritas pelo modelo."""
    respostas = {}
    for p in vaga.perguntas_eliminatorias:
        trecho = normalizar(p.trecho)
        achada = next((r for r in avaliacao.respostas_fechadas if trecho in normalizar(r.pergunta)), None)
        respostas[p.coluna] = achada.resposta if achada else "não respondida"
    return respostas


def classificar(vaga: Vaga, avaliacao: AvaliacaoLLM) -> tuple[Classificacao, float, str, dict[str, str], str]:
    """Regras, nesta ordem:
    1. resposta contrária numa pergunta eliminatória  -> NAO_ADERENTE
    2. algum requisito obrigatório NAO_ATENDE          -> NAO_ADERENTE
    3. todos os obrigatórios ATENDE                    -> ADERENTE
    4. caso contrário (algum parcial)                  -> PARCIALMENTE_ADERENTE
    A nota (0 a 100) ordena candidatos dentro da mesma classificação; os
    requisitos desejáveis entram só nela.
    """
    soma, peso_total, obrigatorios = 0.0, 0.0, []
    for requisito, a in zip(vaga.requisitos, avaliacao.avaliacoes):
        peso = PESO_OBRIGATORIO if requisito.obrigatorio else PESO_DESEJAVEL
        soma += PONTOS[a.status] * peso
        peso_total += peso
        if requisito.obrigatorio:
            obrigatorios.append((requisito.nome, a.status))

    nota = round(100 * soma / peso_total, 1) if peso_total else 0.0
    atendidos = f"{sum(s == Status.ATENDE for _, s in obrigatorios)}/{len(obrigatorios)}"
    eliminatorias = respostas_eliminatorias(vaga, avaliacao)

    contrarias = [
        p.coluna for p in vaga.perguntas_eliminatorias
        if eliminatorias[p.coluna] != "não respondida"
        and normalizar(eliminatorias[p.coluna]) != normalizar(p.resposta_exigida)
    ]
    if contrarias:
        return Classificacao.NAO_ADERENTE, nota, atendidos, eliminatorias, f"Pergunta eliminatória: {', '.join(contrarias)}"

    nao_atende = [nome for nome, s in obrigatorios if s == Status.NAO_ATENDE]
    if nao_atende:
        return Classificacao.NAO_ADERENTE, nota, atendidos, eliminatorias, f"Não atende: {'; '.join(nao_atende)}"
    if all(s == Status.ATENDE for _, s in obrigatorios):
        return Classificacao.ADERENTE, nota, atendidos, eliminatorias, ""
    return Classificacao.PARCIALMENTE_ADERENTE, nota, atendidos, eliminatorias, ""


def ordenar(resultados: list) -> list:
    return sorted(resultados, key=lambda r: (ORDEM[r.classificacao], -r.nota, r.id))
