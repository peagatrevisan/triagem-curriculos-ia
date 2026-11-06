"""
Saídas da triagem para a equipe de R&S:

- planilha.xlsx: uma aba por classificação (Atende, Atende parcialmente,
  Não atende, Revisão manual), mais o resumo. Cada linha tem a coluna
  "DECISÃO DO R&S", em amarelo, para o recrutador confirmar.
- pareceres/<candidato>.docx: um Word por linha da planilha, com a
  justificativa e as evidências de cada requisito, para auditoria.
"""
import re
import zipfile
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .modelos import Classificacao, ResultadoCandidato, ResumoTriagem, Status

ABAS = {
    Classificacao.ADERENTE: "Atende",
    Classificacao.PARCIALMENTE_ADERENTE: "Atende parcialmente",
    Classificacao.NAO_ADERENTE: "Não atende",
    Classificacao.REVISAO_MANUAL: "Revisão manual",
}
ROTULO_STATUS = {
    Status.ATENDE: "ATENDE",
    Status.ATENDE_PARCIALMENTE: "ATENDE PARCIALMENTE",
    Status.NAO_ATENDE: "NÃO ATENDE",
}
CORES = {
    Classificacao.ADERENTE: RGBColor(0x1B, 0x7F, 0x3B),
    Classificacao.PARCIALMENTE_ADERENTE: RGBColor(0xB2, 0x6B, 0x00),
    Classificacao.NAO_ADERENTE: RGBColor(0xB0, 0x24, 0x18),
    Classificacao.REVISAO_MANUAL: RGBColor(0x44, 0x55, 0x77),
}
AMARELO = PatternFill("solid", fgColor="FFF2A8")
CABECALHO = PatternFill("solid", fgColor="1F3864")


def nome_parecer(r: ResultadoCandidato) -> str:
    return re.sub(r"[^\w.-]+", "_", Path(r.id).stem) + ".docx"


# ---------- Excel ----------
def _formatar_aba(ws, larguras: list[int]):
    for i, largura in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(i)].width = largura
    for celula in ws[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = CABECALHO
        celula.alignment = Alignment(wrap_text=True, vertical="center")
    for linha in ws.iter_rows(min_row=2):
        for celula in linha:
            celula.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"


def gerar_planilha(resumo: ResumoTriagem, destino: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Indicador", "Valor"])
    for indicador, valor in [
        ("Vaga", f"{resumo.vaga.codigo} — {resumo.vaga.titulo}"),
        ("Gerado em", f"{datetime.now():%d/%m/%Y %H:%M}"),
        ("Modo", resumo.modo),
        ("Candidatos analisados", resumo.total),
        ("Retomados de execução anterior", resumo.retomados),
        *[(ABAS[c], resumo.por_classificacao[c.value]) for c in ABAS],
        ("Tempo de processamento (s)", resumo.segundos),
        ("Tokens de entrada / saída", f"{resumo.tokens_entrada} / {resumo.tokens_saida}"),
        ("Custo estimado (US$)", resumo.custo_estimado_usd if resumo.custo_estimado_usd is not None else "—"),
        ("Observação", "Classificação sugerida pela triagem com IA. A decisão é da equipe de R&S."),
    ]:
        ws.append([indicador, valor])
    _formatar_aba(ws, [34, 70])

    requisitos = resumo.vaga.requisitos
    eliminatorias = [p.coluna for p in resumo.vaga.perguntas_eliminatorias]
    cabecalho = (
        ["CANDIDATO", "NOTA", "OBRIGATÓRIOS"]
        + [f"{r.nome}{'' if r.obrigatorio else ' (desejável)'}" for r in requisitos]
        + eliminatorias
        + ["MOTIVO", "OBSERVAÇÃO FINAL", "PARECER (WORD)", "DECISÃO DO R&S"]
    )
    larguras = [30, 7, 13] + [38] * len(requisitos) + [14] * len(eliminatorias) + [36, 36, 28, 18]

    def linha(r: ResultadoCandidato) -> list:
        por_req = [f"{ROTULO_STATUS[a.status]} — {a.justificativa}" for a in r.avaliacoes] or [""] * len(requisitos)
        return (
            [r.id, r.nota if r.avaliacoes else "", r.obrigatorios_atendidos]
            + por_req
            + [r.eliminatorias.get(c, "") for c in eliminatorias]
            + [r.motivo, r.observacao_final, nome_parecer(r)]
        )

    # Visão geral com todos (sem coluna de decisão: a decisão é registrada nas abas por classificação)
    todos = wb.create_sheet("Todos")
    todos.append(["CLASSIFICAÇÃO"] + cabecalho[:-1])
    for r in resumo.resultados:
        todos.append([ABAS[r.classificacao]] + linha(r))
    _formatar_aba(todos, [20] + larguras[:-1])

    for classificacao, titulo in ABAS.items():
        aba = wb.create_sheet(titulo)
        aba.append(cabecalho)
        for r in (x for x in resumo.resultados if x.classificacao == classificacao):
            aba.append(linha(r) + [""])
            aba.cell(row=aba.max_row, column=len(cabecalho)).fill = AMARELO
        _formatar_aba(aba, larguras)

    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


# ---------- Word (um parecer por candidato) ----------
def _tabela(doc, cabecalho: list[str], linhas: list[list[str]], larguras_cm: list[float]):
    tabela = doc.add_table(rows=1, cols=len(cabecalho))
    tabela.style = "Light Grid Accent 1"
    tabela.autofit = False
    for celula, texto in zip(tabela.rows[0].cells, cabecalho):
        celula.text = texto
        celula.paragraphs[0].runs[0].bold = True
    for linha in linhas:
        for celula, texto in zip(tabela.add_row().cells, linha):
            celula.text = str(texto)
    for coluna, largura in zip(tabela.columns, larguras_cm):
        coluna.width = Cm(largura)  # Word e LibreOffice leem larguras em lugares diferentes
    for linha in tabela.rows:
        for celula, largura in zip(linha.cells, larguras_cm):
            celula.width = Cm(largura)


def _evidencias(a) -> str:
    if not a.evidencias:
        return "—"
    partes = []
    for e in a.evidencias:
        origem = " · ".join(x for x in [e.empresa, e.cargo, e.periodo] if x)
        partes.append(f"{origem}: {e.descricao}" if origem else e.descricao)
    return "\n".join(partes)


def gerar_parecer(resumo: ResumoTriagem, r: ResultadoCandidato, destino: Path) -> Path:
    """Formulário de análise curricular (etapa 1), um por candidato.

    Segue a estrutura do formulário usado pelo R&S: as seções 2, 3 e 5 vêm
    preenchidas pela triagem; a 4 (documentos) e a 6 (assinatura) ficam para
    o avaliador humano.
    """
    vaga = resumo.vaga
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10)

    doc.add_heading("Formulário — Análise curricular (etapa 1)", level=0)

    doc.add_heading("1. Identificação", level=1)
    doc.add_paragraph(f"Código da vaga: {vaga.codigo} — {vaga.titulo}")
    doc.add_paragraph(f"Candidato: {r.id}")
    doc.add_paragraph(f"Data da triagem automática: {datetime.now():%d/%m/%Y} · modo: {resumo.modo}")
    doc.add_paragraph("Avaliador (nome e cargo): ______________________________")

    doc.add_heading("2. Checklist de pré-requisitos", level=1)
    if vaga.perguntas_eliminatorias:
        _tabela(
            doc,
            ["Critério", "Resposta do candidato", "Exigido", "Atende?"],
            [
                [p.coluna, r.eliminatorias.get(p.coluna, "—"), p.resposta_exigida,
                 "—" if r.eliminatorias.get(p.coluna, "não respondida") == "não respondida"
                 else ("Sim" if r.eliminatorias[p.coluna].lower() == p.resposta_exigida.lower() else "Não")]
                for p in vaga.perguntas_eliminatorias
            ],
            [6.0, 4.0, 3.0, 3.8],
        )
    else:
        doc.add_paragraph("A vaga não tem perguntas eliminatórias.")

    doc.add_heading("3. Requisitos da vaga", level=1)
    doc.add_paragraph(f"Tempo mínimo de experiência considerado: {vaga.tempo_minimo_meses} meses.")
    if r.avaliacoes:
        obrigatorio = {q.nome: q.obrigatorio for q in vaga.requisitos}
        _tabela(
            doc,
            ["Requisito", "Status", "Evidências", "Justificativa"],
            [
                [
                    a.requisito + ("" if obrigatorio.get(a.requisito, True) else " (desejável)"),
                    ROTULO_STATUS[a.status] + (" *" if a.alterado_pelo_questionario else ""),
                    _evidencias(a),
                    a.justificativa,
                ]
                for a in r.avaliacoes
            ],
            [4.2, 2.6, 5.0, 5.0],
        )
        if any(a.alterado_pelo_questionario for a in r.avaliacoes):
            doc.add_paragraph("* Status alterado com base nas respostas do questionário.").italic = True
    else:
        doc.add_paragraph("Sem análise automática para este candidato (ver parecer técnico).")

    doc.add_heading("4. Validação documental", level=1)
    _tabela(
        doc,
        ["Documento", "Recebido?", "Conforme?", "Observação"],
        [[d, "", "", ""] for d in vaga.documentos_exigidos],
        [6.0, 2.5, 2.5, 5.8],
    )

    doc.add_heading("5. Parecer técnico", level=1)
    paragrafo = doc.add_paragraph("Classificação sugerida: ")
    destaque = paragrafo.add_run(ABAS[r.classificacao].upper())
    destaque.bold = True
    destaque.font.color.rgb = CORES[r.classificacao]
    if r.avaliacoes:
        doc.add_paragraph(f"Nota: {r.nota:.0f}/100 · obrigatórios atendidos: {r.obrigatorios_atendidos}")
    if r.motivo:
        doc.add_paragraph(f"Motivo: {r.motivo}")
    if r.resumo:
        doc.add_paragraph(r.resumo)
    if r.observacao_final:
        doc.add_paragraph(f"Observação final: {r.observacao_final}")
    aviso = doc.add_paragraph()
    aviso.add_run(
        "Triagem inicial feita com apoio de IA. A comprovação documental é feita nesta etapa pelo avaliador, "
        "e a decisão sobre o avanço do candidato é da equipe de R&S."
    ).italic = True
    doc.add_paragraph("Decisão do avaliador: (  ) Habilitado   (  ) Não habilitado")
    doc.add_paragraph("Justificativa (obrigatória caso não habilitado): ______________________________")

    doc.add_heading("6. Assinatura", level=1)
    doc.add_paragraph("Avaliador: ______________________________   Data: ____/____/______")

    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.save(destino)
    return destino


def gerar_saidas(resumo: ResumoTriagem, pasta: Path) -> Path:
    """Gera planilha, pareceres e um .zip com tudo. Devolve o caminho do .zip."""
    planilha = gerar_planilha(resumo, pasta / "planilha.xlsx")
    pareceres = [gerar_parecer(resumo, r, pasta / "pareceres" / nome_parecer(r)) for r in resumo.resultados]
    (pasta / "resultado.json").write_text(resumo.model_dump_json(indent=2), encoding="utf-8")

    pacote = pasta / "triagem.zip"
    with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(planilha, planilha.name)
        for p in pareceres:
            z.write(p, f"pareceres/{p.name}")
    return pacote
