"""
Lateral Synthesis MCP - Divergence Strategies

Pluggable strategies for generating divergent concepts.
"""

import json
import logging
import random
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to concepts data file
CONCEPTS_FILE = Path(__file__).parent.parent / "data" / "concepts.json"

# -----------------------------------------------------------------------------
# Base Strategy
# -----------------------------------------------------------------------------

class DivergenceStrategy(ABC):
    """Abstract base class for divergence generation strategies."""
    
    @abstractmethod
    def generate(self, origin: str, count: int) -> list[str]:
        """
        Generate divergent concepts from an origin.
        
        Args:
            origin: The starting concept/phrase
            count: Number of divergent concepts to generate
            
        Returns:
            List of divergent concept strings
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging/config."""
        pass


# -----------------------------------------------------------------------------
# Random Strategy (wonderwords)
# -----------------------------------------------------------------------------

class RandomStrategy(DivergenceStrategy):
    """Generate random words with no relation to origin."""
    
    def __init__(self):
        self._words = []
        self._source = "unknown"
        
        # 1. Try wonderwords (optional)
        try:
            from wonderwords import RandomWord
            self._rw = RandomWord()
            self._source = "wonderwords"
        except ImportError:
            self._rw = None
            
        # 2. Load concepts.json (primary fallback)
        self._fallback_words = self._load_concepts_file()
        
        # If wonderwords failed, we rely on the file
        if not self._rw:
            self._words = self._fallback_words
            self._source = "concepts.json"
            
        # 3. Panic fallback (if file missing/empty and no wonderwords)
        if not self._rw and not self._words:
            self._words = ["entropy", "prism", "cascade", "horizon", "symmetry"]
            self._source = "panic_fallback"
            logger.warning("Using panic fallback word list (concepts.json missing/empty)")

    def _load_concepts_file(self) -> list[str]:
        """Load word list from concepts.json."""
        try:
            if not CONCEPTS_FILE.exists():
                logger.warning(f"concepts.json not found at {CONCEPTS_FILE}")
                return []
                
            with open(CONCEPTS_FILE) as f:
                data = json.load(f)
            
            fallback = data.get("fallback_words", {})
            words = []
            for category in [
                "nouns",
                "verbs",
                "adjectives",
                "abstract",
                "phrases",
                "numbers",
                "equations",
            ]:
                words.extend(fallback.get(category, []))
            return words
        except Exception as e:
            logger.warning(f"Failed to load concepts.json: {e}")
            return []
    
    @property
    def name(self) -> str:
        return f"random ({self._source})"
    
    def generate(self, origin: str, count: int) -> list[str]:
        """Generate random words (true randomness)."""
        logger.debug(f"Generating {count} random divergent concepts for origin: {origin[:20]}...")
        
        # Use wonderwords if available, but occasionally sample from concepts.json
        # so we can emit phrases/numbers/equations too.
        if self._rw:
            concepts: list[str] = []
            word_types = ["noun", "verb", "adjective"]
            for i in range(count):
                use_fallback = bool(self._fallback_words) and (i % 4 == 3)
                if use_fallback:
                    concepts.append(random.choice(self._fallback_words))
                    continue

                word_type = word_types[i % len(word_types)]
                try:
                    if word_type == "noun":
                        word = self._rw.word(include_parts_of_speech=["nouns"])
                    elif word_type == "verb":
                        word = self._rw.word(include_parts_of_speech=["verbs"])
                    else:
                        word = self._rw.word(include_parts_of_speech=["adjectives"])
                    concepts.append(word)
                except Exception:
                    # Fallback to list if wonderwords fails for some reason
                    if self._fallback_words:
                        concepts.append(random.choice(self._fallback_words))
                    else:
                        concepts.append("unknown")
            return concepts
            
        # Otherwise use loaded list (concepts.json or panic fallback)
        if not self._words:
             return ["error"] * count # Should be covered by panic fallback in init
             
        return [random.choice(self._words) for _ in range(count)]


# -----------------------------------------------------------------------------
# Strategy Registry
# -----------------------------------------------------------------------------

STRATEGIES: dict[str, type[DivergenceStrategy]] = {
    "random": RandomStrategy,
}


def get_strategy(method: str) -> DivergenceStrategy:
    """Get a divergence strategy by name."""
    strategy_class = STRATEGIES.get(method)
    if strategy_class is None:
        logger.warning(f"Unknown divergence method '{method}', using random")
        strategy_class = RandomStrategy
    return strategy_class()


def generate_divergent_concepts(origin: str, method: str = "random", count: int = 5) -> list[str]:
    """
    Generate divergent concepts using the specified method.
    
    Args:
        origin: The starting concept/phrase
        method: Divergence strategy name
        count: Number of concepts to generate
        
    Returns:
        List of divergent concept strings
    """
    strategy = get_strategy(method)
    logger.info(f"Generating {count} divergent concepts using '{strategy.name}' strategy")
    concepts = strategy.generate(origin, count)
    logger.debug(f"Generated concepts: {concepts}")
    return concepts
