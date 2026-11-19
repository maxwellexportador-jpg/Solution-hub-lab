"""Adaptador do MiniMind upstream (carregamento tardio).

O import de ``torch``/``transformers`` acontece apenas dentro de ``infer()``.
Assim a camada Solution Print pode ser importada, testada e usada em CI sem
PyTorch, e a indisponibilidade vira erro tipado em vez de ``ImportError`` na
importação do pacote.

Este adaptador **não altera** nenhum arquivo do MiniMind: ele reutiliza
``model/model_minimind.py`` como biblioteca, exatamente como o upstream.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..errors import AdapterUnavailable, MalformedResponse
from ..registry import ModelSpec
from .base import BaseAdapter, InferenceRequest, InferenceResponse

CHECKPOINT_ENV = "SOLUTION_PRINT_MINIMIND_CHECKPOINT"
HIDDEN_ENV = "SOLUTION_PRINT_MINIMIND_HIDDEN"
LAYERS_ENV = "SOLUTION_PRINT_MINIMIND_LAYERS"
MAX_SEQ_ENV = "SOLUTION_PRINT_MINIMIND_MAX_SEQ"
MOE_ENV = "SOLUTION_PRINT_MINIMIND_USE_MOE"
DEVICE_ENV = "SOLUTION_PRINT_MINIMIND_DEVICE"

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKENIZER_DIR = REPO_ROOT / "model"


class MiniMindAdapter(BaseAdapter):
    """Inferência local com checkpoint ``.pth`` do MiniMind."""

    name = "minimind"

    def __init__(self, spec: ModelSpec, environ: Optional[Dict[str, str]] = None):
        super().__init__(spec, environ)
        self._env = environ if environ is not None else os.environ
        self._model = None
        self._tokenizer = None
        self._device = "cpu"

    # ------------------------------------------------------------------ #
    # Configuração
    # ------------------------------------------------------------------ #
    def _checkpoint(self) -> Optional[Path]:
        raw = self._env.get(CHECKPOINT_ENV, "").strip()
        if not raw:
            return None
        return Path(raw).expanduser()

    def _config_values(self) -> Dict[str, Any]:
        def _int(name: str, default: int) -> int:
            try:
                return int(self._env.get(name, default))
            except (TypeError, ValueError):
                return default

        return {
            "hidden_size": _int(HIDDEN_ENV, 512),
            "num_hidden_layers": _int(LAYERS_ENV, 8),
            "max_seq_len": _int(MAX_SEQ_ENV, 512),
            "use_moe": self._env.get(MOE_ENV, "0") == "1",
        }

    def available(self) -> Tuple[bool, str]:
        checkpoint = self._checkpoint()
        if checkpoint is None:
            return False, "defina %s com o caminho do checkpoint .pth" % CHECKPOINT_ENV
        if not checkpoint.is_file():
            return False, "checkpoint não encontrado: %s" % checkpoint
        if importlib.util.find_spec("torch") is None:
            return False, "PyTorch não instalado (dependência opcional de inferência)"
        if importlib.util.find_spec("transformers") is None:
            return False, "transformers não instalado"
        if not (TOKENIZER_DIR / "tokenizer.json").is_file():
            return False, "tokenizer.json ausente em %s" % TOKENIZER_DIR
        return True, "checkpoint e dependências presentes: %s" % checkpoint

    # ------------------------------------------------------------------ #
    # Carregamento tardio
    # ------------------------------------------------------------------ #
    def _load(self) -> Tuple[Any, Any, str]:
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer, self._device

        checkpoint = self._checkpoint()
        ok, reason = self.available()
        if not ok or checkpoint is None:
            raise AdapterUnavailable(reason)

        import sys

        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        try:
            import torch  # type: ignore
            from transformers import AutoTokenizer  # type: ignore
            from model.model_minimind import (  # type: ignore
                MiniMindConfig,
                MiniMindForCausalLM,
            )
        except ImportError as exc:  # pragma: no cover - depende de ambiente
            raise AdapterUnavailable(
                "dependências de inferência ausentes: %s" % type(exc).__name__
            ) from exc

        device = self._env.get(DEVICE_ENV, "").strip()
        if not device:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        config = MiniMindConfig(**self._config_values())
        model = MiniMindForCausalLM(config)
        try:
            state = torch.load(str(checkpoint), map_location=device)
            model.load_state_dict(state, strict=True)
        except Exception as exc:  # pragma: no cover - requer pesos reais
            raise AdapterUnavailable(
                "falha ao carregar checkpoint (%s); verifique hidden/layers/use_moe"
                % type(exc).__name__
            ) from exc

        model = model.half().eval().to(device)
        try:
            tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR))
        except Exception as exc:  # pragma: no cover - requer arquivos reais
            raise AdapterUnavailable(
                "falha ao carregar tokenizer (%s)" % type(exc).__name__
            ) from exc

        self._model, self._tokenizer, self._device = model, tokenizer, device
        return model, tokenizer, device

    # ------------------------------------------------------------------ #
    # Inferência
    # ------------------------------------------------------------------ #
    def infer(self, request: InferenceRequest) -> InferenceResponse:
        started = self._start_timer()
        request.validate()

        # Carrega primeiro: sem checkpoint válido, nem importa torch.
        model, tokenizer, device = self._load()

        import torch  # type: ignore
        messages = request.as_chat_payload()

        try:
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:  # pragma: no cover - tokenizer alternativo
            prompt = "\n".join(
                "%s: %s" % (item["role"], item["content"]) for item in messages
            ) + "\nassistant:"

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
        inputs = {key: value.to(device) for key, value in inputs.items()}

        generation: Dict[str, Any] = {
            "max_new_tokens": int(request.max_tokens),
            "pad_token_id": getattr(tokenizer, "eos_token_id", None),
        }
        temperature = float(request.temperature)
        if temperature > 0:
            generation.update(
                {
                    "do_sample": True,
                    "temperature": temperature,
                    "top_p": 0.92,
                }
            )
        else:
            generation["do_sample"] = False

        with torch.no_grad():
            try:
                output = model.generate(**inputs, **generation)
            except Exception as exc:  # pragma: no cover - requer pesos reais
                raise AdapterUnavailable(
                    "falha na geração (%s)" % type(exc).__name__
                ) from exc

        prompt_length = inputs["input_ids"].shape[-1]
        generated = output[0][prompt_length:]
        text = tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not text:
            raise MalformedResponse("modelo não produziu texto")

        return InferenceResponse(
            model=self.spec.id,
            text=text,
            provider=self.spec.provider,
            usage={
                "prompt_tokens": int(prompt_length),
                "completion_tokens": int(len(generated)),
                "device": device,
            },
            latency_ms=self._elapsed_ms(started),
            simulated=False,
            finish_reason="stop",
        )
