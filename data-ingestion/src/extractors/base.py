from abc import ABC, abstractmethod
from typing import Any, Dict
from pathlib import Path

class BaseExtractor(ABC):
    """
    Abstract Base Class for all ingestion sources.
    Enforces a strict contract: Input Path -> Output Data.
    """

    @abstractmethod
    def extract(self, file_path: Path, **kwargs) -> Dict[str, Any]:
        """
        Extracts content from a file.
        
        Args:
            file_path (Path): Path to the input file.
            **kwargs: Additional arguments (config, device, etc.)

        Returns:
            Dict[str, Any]: A standardized dictionary containing keys like:
                            {'content': str, 'metadata': dict}
        """
        pass
