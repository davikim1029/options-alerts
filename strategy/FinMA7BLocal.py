# strategy/FinMA7BLocal.py

import torch
import os
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers.utils import logging
from services.logging.logger_singleton import getLogger


# --------------------------------------------------
# GLOBAL SETTINGS
# --------------------------------------------------
os.environ["TOKENIZERS_PARALLELISM"] = "false"
logging.set_verbosity_error()

_MODEL_INSTANCE = None  # singleton cache for FinMA-7B


class FinMA7BLocal:
    """
    Local Hugging Face implementation for FinMA-7B.
    Loads once and can be reused safely across threads.
    """

    def __init__(self, model_name="microsoft/Phi-3-mini-4k-instruct", device=None):
        """
        :param model_name: Hugging Face model name or path
        :param device: 0 for first GPU, -1 for CPU
        """
        self.model_name = model_name
        self.device = device if device is not None else (0 if torch.cuda.is_available() else -1)

        print(f"[FinMA7BLocal] Initializing model: {model_name}")
        print(f"[FinMA7BLocal] Using device: {'GPU' if self.device >= 0 else 'CPU'}")

        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Load model (cached if already downloaded)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            device_map="auto" if self.device >= 0 else None,
            torch_dtype=torch.float16 if self.device >= 0 else torch.float32
        )
        if self.model.config.pad_token_id is None:
            self.model.config.pad_token_id = self.tokenizer.pad_token_id

        print("[FinMA7BLocal] ✅ Model and tokenizer ready.")

    def analyze(self, text: str, metrics: dict = None) -> str:
        """
        Analyze text + optional metrics with FinMA-7B.
        Uses direct model.generate() to avoid prompt echoing.
        """
        if not text:
            return ""

        # Construct prompt
        prompt = text
        if metrics:
            metrics_str = " | ".join(f"{k}: {v}" for k, v in metrics.items())
            prompt = f"{metrics_str}\n{text}"

        # Tokenize
        inputs = self.tokenizer(prompt, return_tensors="pt").to(
            "cuda" if self.device >= 0 else "cpu"
        )

        # Generate
        with torch.no_grad():
            try:
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=1024,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            except Exception as e:
                logger = getLogger()
                logger.logMessage(f"Error calling model: {e}")

        # Decode + clean output
        generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt):].strip()

        return generated_text.strip()


# --------------------------------------------------
# Singleton Accessor
# --------------------------------------------------

def get_finma_model(model_name="microsoft/Phi-3-mini-4k-instruct", device=None):
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        _MODEL_INSTANCE = FinMA7BLocal(model_name=model_name, device=device)
    return _MODEL_INSTANCE


# --------------------------------------------------
# Optional: Manual Pre-Download Helper
# --------------------------------------------------

def predownload_finma(model_name="microsoft/Phi-3-mini-4k-instruct"):
    """
    Run this once (manually) to ensure model is downloaded
    before multi-threaded app starts.
    """
    print(f"[FinMA7BLocal] Pre-downloading model: {model_name}")
    _ = AutoTokenizer.from_pretrained(model_name)
    _ = AutoModelForCausalLM.from_pretrained(model_name)
    print("[FinMA7BLocal] ✅ Model cached locally.")
