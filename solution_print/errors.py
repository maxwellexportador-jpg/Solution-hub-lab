"""Exceções tipadas da camada Solution Print.

Erros de domínio são explícitos para que roteador, API e integrações possam
distinguir "modelo inexistente" de "modelo indisponível" e de "política
violada", sem capturar ``Exception`` genericamente.
"""

from __future__ import annotations


class LabError(Exception):
    """Erro base da camada Solution Print."""


class ConfigurationError(LabError):
    """Configuração ausente, inválida ou insegura."""


class ValidationError(LabError):
    """Entrada inválida (payload, mensagem, metadados ou modelo)."""


class ModelNotFound(LabError):
    """O identificador de modelo não existe no registro."""


class ModelUnavailable(LabError):
    """O modelo existe, mas não pode ser executado neste ambiente."""


class AdapterError(LabError):
    """Falha genérica do adaptador de inferência."""


class AdapterTimeout(AdapterError):
    """O adaptador excedeu o tempo limite configurado."""


class AdapterUnavailable(AdapterError):
    """O adaptador não está operacional (dependência, endpoint ou pesos)."""


class MalformedResponse(AdapterError):
    """O provedor respondeu em formato inesperado."""


class PolicyViolation(LabError):
    """Ação bloqueada pela política de segurança ou de custo."""


class NoModelAvailable(LabError):
    """Nenhum modelo atende à tarefa e aos recursos disponíveis."""


class AllModelsFailed(LabError):
    """Todos os modelos autorizados falharam em tempo de execução."""


class IntegrationError(LabError):
    """Falha de contrato/comunicação com um projeto do ecossistema."""
