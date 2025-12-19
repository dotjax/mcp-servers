"""
Lateral Synthesis MCP - Divergence Strategies

Pluggable strategies for generating divergent concepts.
"""

import logging
import random
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

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
        """Fallback word list if wonderwords not available."""
        return [
            # Nouns
            "elephant", "glacier", "symphony", "blueprint", "telescope",
            "volcano", "manuscript", "cathedral", "archipelago", "pendulum",
            "labyrinth", "prism", "fossil", "avalanche", "compass",
            "horizon", "mosaic", "chimera", "scaffold", "reservoir",
            # Verbs
            "illuminate", "cascade", "oscillate", "crystallize", "navigate",
            "transcend", "converge", "dissolve", "amplify", "calibrate",
            # Adjectives
            "ephemeral", "visceral", "tangential", "primordial", "quantum",
            "fractal", "recursive", "emergent", "liminal", "paradoxical",
            # Abstract concepts
            "entropy", "resonance", "symmetry", "recursion", "emergence",
            "inertia", "catalysis", "equilibrium", "polarity", "metamorphosis",
        ]
    
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
