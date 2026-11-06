"""
Roda a triagem pela linha de comando, sem subir a API.

Exemplos:
  python triar.py                                    # vaga e candidatos de exemplo
  python triar.py --vaga minha_vaga.json --pasta candidatos/
  python triar.py --simulado                         # sem chave de API
  python triar.py --retomar                          # continua uma execução que caiu no meio

O progresso é gravado candidato a candidato em saidas/<código da vaga>/analises.jsonl.
Com --retomar, quem já está nesse arquivo não é enviado de novo à IA.
"""
import argparse
import threading
from pathlib import Path

from app.avaliacao import criar_avaliador
from app.config import PASTA_SAIDAS
from app.extracao import FORMATOS_ACEITOS
from app.modelos import ResultadoCandidato, Vaga
from app.pipeline import triar
from app.relatorio import ABAS, gerar_saidas

RAIZ = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description="Triagem de currículos com IA")
    parser.add_argument("--vaga", default=RAIZ / "data" / "vaga_exemplo.json", type=Path)
    parser.add_argument("--pasta", default=RAIZ / "data" / "candidatos", type=Path)
    parser.add_argument("--simulado", action="store_true", help="não chama a IA (busca por palavras-chave)")
    parser.add_argument("--retomar", action="store_true", help="pula candidatos já avaliados")
    args = parser.parse_args()

    vaga = Vaga.model_validate_json(args.vaga.read_text(encoding="utf-8"))
    arquivos = [(p.name, p.read_bytes()) for p in sorted(args.pasta.iterdir()) if p.suffix.lower() in FORMATOS_ACEITOS]

    pasta = PASTA_SAIDAS / vaga.codigo
    pasta.mkdir(parents=True, exist_ok=True)
    progresso = pasta / "analises.jsonl"
    anteriores = []
    if args.retomar and progresso.exists():
        anteriores = [ResultadoCandidato.model_validate_json(l) for l in progresso.read_text(encoding="utf-8").splitlines() if l.strip()]
    elif progresso.exists():
        progresso.unlink()

    trava = threading.Lock()

    def gravar(resultado: ResultadoCandidato):
        with trava, progresso.open("a", encoding="utf-8") as f:
            f.write(resultado.model_dump_json() + "\n")

    avaliador = criar_avaliador(forcar_simulado=args.simulado)
    print(f"Vaga: {vaga.titulo} | {len(arquivos)} candidatos | já avaliados: {len(anteriores)} | modo: {avaliador.modo}\n")

    resumo = triar(vaga, arquivos, avaliador, anteriores=anteriores, ao_concluir=gravar)

    for i, r in enumerate(resumo.resultados, 1):
        nota = f"{r.nota:5.1f}" if r.avaliacoes else "    —"
        print(f"{i:>2}. {r.id:<34} {ABAS[r.classificacao]:<20} nota {nota}  {r.motivo[:60]}")

    pacote = gerar_saidas(resumo, pasta)
    print(f"\nTempo: {resumo.segundos:.1f} s", end="")
    if resumo.tokens_entrada:
        print(f" | tokens: {resumo.tokens_entrada:,} entrada / {resumo.tokens_saida:,} saída", end="")
    if resumo.custo_estimado_usd is not None:
        print(f" | custo estimado: US$ {resumo.custo_estimado_usd:.4f}", end="")
    print(f"\nPlanilha: {pasta / 'planilha.xlsx'}\nPareceres: {pasta / 'pareceres'}\nPacote: {pacote}")


if __name__ == "__main__":
    main()
