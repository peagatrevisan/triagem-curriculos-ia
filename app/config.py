"""Configuração lida do ambiente (.env). Nenhuma chave fica escrita no código."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent
PASTA_SAIDAS = RAIZ / "saidas"


class Config:
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or None
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Quantos currículos são avaliados em paralelo. O limite real é a cota da API.
    MAX_CONCORRENCIA: int = int(os.getenv("MAX_CONCORRENCIA", "8"))
    TENTATIVAS: int = int(os.getenv("TENTATIVAS", "3"))

    # Abaixo disso, o texto extraído provavelmente veio de um PDF escaneado
    # (imagem). O currículo vai para revisão manual em vez de ser avaliado.
    MIN_CARACTERES_TEXTO: int = int(os.getenv("MIN_CARACTERES_TEXTO", "300"))

    # Opcional: preço por 1 milhão de tokens (USD) para estimar o custo no relatório.
    # Confira os valores atuais na página de preços do Gemini antes de preencher.
    PRECO_ENTRADA_USD_1M: float = float(os.getenv("PRECO_ENTRADA_USD_1M", "0"))
    PRECO_SAIDA_USD_1M: float = float(os.getenv("PRECO_SAIDA_USD_1M", "0"))


config = Config()
