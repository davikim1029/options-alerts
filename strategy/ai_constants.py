import enum

class RateLimitError(Exception):
    """Raised when Rate Limit hit."""
    pass


class AI_MODEL(enum.Enum):
    OPENAI = "OPENAI"
    OPENROUTER = "OPENROUTER"
    HUGGINGFACE = "HUGGINGFACE"
    OLLAMA = "OLLAMA"

all_ai_models =  [AI_MODEL.OPENROUTER,AI_MODEL.OPENAI, AI_MODEL.HUGGINGFACE, AI_MODEL.OLLAMA]