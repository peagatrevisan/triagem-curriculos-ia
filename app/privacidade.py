"""
Minimização de dados antes de enviar o currículo ao modelo (LGPD).

Contato, documentos e data de nascimento não ajudam a avaliar requisitos
técnicos, e nome, idade ou endereço podem enviesar a avaliação. Por isso
esses dados são mascarados antes da chamada à IA. O candidato continua
identificado no relatório pelo nome do arquivo.
"""
import re

PADROES = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("[CPF]", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("[TELEFONE]", re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")),
    ("[LINK]", re.compile(r"https?://\S+|(?:www\.|linkedin\.com/|github\.com/)\S+", re.IGNORECASE)),
    ("[CEP]", re.compile(r"\b\d{5}-\d{3}\b")),
]

LINHAS_PESSOAIS = re.compile(
    r"^\s*(nome|data de nascimento|nascimento|idade|estado civil|endere[cç]o|sexo|g[eê]nero|"
    r"nacionalidade|naturalidade|filhos)\s*[:\-].*$",
    re.IGNORECASE | re.MULTILINE,
)


def anonimizar(texto: str) -> str:
    texto = LINHAS_PESSOAIS.sub("[DADO PESSOAL OMITIDO]", texto)
    for marcador, padrao in PADROES:
        texto = padrao.sub(marcador, texto)
    return texto
