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
        try:
            from wonderwords import RandomWord
            self._rw = RandomWord()
            self._available = True
        except ImportError:
            logger.warning("wonderwords not installed, using fallback word list")
            self._rw = None
            self._available = False
            self._fallback_words = self._load_fallback_words()
    
    def _load_fallback_words(self) -> list[str]:
        """Load fallback word list from concepts.json."""
        try:
            with open(CONCEPTS_FILE) as f:
                data = json.load(f)
            fallback = data.get("fallback_words", {})
            words = []
            for category in ["nouns", "verbs", "adjectives", "abstract"]:
                words.extend(fallback.get(category, []))
            if words:
                return words
        except Exception as e:
            logger.warning(f"Failed to load concepts.json: {e}")
        # Hardcoded minimal fallback if file missing
        return ["entropy", "prism", "cascade", "horizon", "symmetry"]
    
    @property
    def name(self) -> str:
        return "random"
    
    def generate(self, origin: str, count: int) -> list[str]:
        """Generate random words, ignoring the origin entirely."""
        logger.debug(f"Generating {count} random divergent concepts (origin ignored)")
        
        if self._available and self._rw:
            concepts = []
            # Mix of word types for variety
            word_types = ["noun", "verb", "adjective"]
            for i in range(count):
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
                    # Fallback if specific POS fails
                    concepts.append(self._rw.word())
            return concepts
        # Use fallback list
        if count <= len(self._fallback_words):
            return random.sample(self._fallback_words, count)
        return random.choices(self._fallback_words, k=count)


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
