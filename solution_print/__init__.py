"""Solution Print AI Lab — camada própria sobre o MiniMind upstream.

Este pacote é independente do MiniMind: nada aqui importa ``torch`` no nível
de módulo, de modo que a camada possa ser testada em máquinas leves e em CI
sem instalar PyTorch, Transformers ou CUDA.

Regra de preservação: nenhum arquivo upstream é reescrito por este pacote.
O MiniMind original (Apache-2.0, Jingyao Gong) permanece intacto e rastreável
em ``model/``, ``trainer/``, ``scripts/`` e ``dataset/``.
"""

from __future__ import annotations

__all__ = [
    "__version__",
    "CONTRACT_VERSION",
    "UPSTREAM_PROJECT",
    "UPSTREAM_URL",
]

__version__ = "0.1.0"

#: Versão dos contratos de integração expostos pelo laboratório.
CONTRACT_VERSION = "1.0"

UPSTREAM_PROJECT = "jingyaogong/minimind"
UPSTREAM_URL = "https://github.com/jingyaogong/minimind"
