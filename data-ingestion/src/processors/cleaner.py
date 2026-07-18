import re
import logging
from typing import Dict, Any, List

# Set up logging
logger = logging.getLogger(__name__)

# Default PII settings used when no config is supplied
_DEFAULT_PII_ENTITIES = [
    "PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS",
    "SG_NRIC", "MCR_NO", "DATE_TIME", "URL",
]
_DEFAULT_PII_REPLACEMENTS = {
    "DEFAULT": "<REDACTED>",
    "PERSON": "<PERSON>",
    "EMAIL_ADDRESS": "<EMAIL>",
    "PHONE_NUMBER": "<PHONE>",
    "SG_NRIC": "<NRIC_ID>",
    "MCR_NO": "<MEDICAL_LICENSE_ID>",
    "DATE_TIME": "<DATE>",
    "URL": "<URL>",
}
_DEFAULT_CUSTOM_RECOGNIZERS = [
    {"entity": "SG_NRIC", "regex": r"(?i)[STFG]\d{7}[A-Z]", "score": 1.0},
    {"entity": "MCR_NO",  "regex": r"\b\d{6}\b",              "score": 0.6},
]


class TextCleaner:
    """
    Markdown text cleaning with PII removal.
    Removes artifacts, normalizes formatting, and anonymizes sensitive information.

    Args:
        config: Optional full pipeline config dict (repo-root config/app.yaml loaded).
                When supplied, all PII settings are read from config['cleaning'].
                When None, built-in defaults are used.
    """

    def __init__(self, config: Dict[str, Any] = None):
        cleaning_cfg = (config or {}).get('cleaning', {})

        self.remove_pii: bool = cleaning_cfg.get('remove_pii', True)
        self._fail_safe: bool = cleaning_cfg.get('fail_safe_on_pii_error', True)
        self._language: str  = cleaning_cfg.get('language', 'en')
        self._pii_entities: List[str] = cleaning_cfg.get('pii_entities', _DEFAULT_PII_ENTITIES)
        self._pii_replacements: Dict[str, str] = cleaning_cfg.get('pii_replacements', _DEFAULT_PII_REPLACEMENTS)
        self._custom_recognizers: List[Dict] = cleaning_cfg.get('custom_recognizers', _DEFAULT_CUSTOM_RECOGNIZERS)

        self.pii_analyzer = None
        self.pii_anonymizer = None

        if self.remove_pii:
            try:
                from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
                from presidio_anonymizer import AnonymizerEngine

                self.pii_analyzer = AnalyzerEngine()
                self.pii_anonymizer = AnonymizerEngine()

                # Register custom recognizers from config
                for rec_cfg in self._custom_recognizers:
                    pattern = Pattern(
                        name=f"{rec_cfg['entity'].lower()}_pattern",
                        regex=rec_cfg['regex'],
                        score=rec_cfg.get('score', 0.8),
                    )
                    recognizer = PatternRecognizer(
                        supported_entity=rec_cfg['entity'],
                        patterns=[pattern],
                    )
                    self.pii_analyzer.registry.add_recognizer(recognizer)

                logger.info("PII Redaction initialized (entities: %s).", self._pii_entities)

            except ImportError:
                logger.warning("⚠️  Presidio not installed. PII removal disabled.")
                self.remove_pii = False
    
    def clean(self, text: str) -> str:
        """
        Clean markdown text in sequence:
        1. Remove phantom images and links
        2. Linearize tables
        3. Fix hyphenation
        4. Collapse whitespace
        5. Remove/anonymize PII
        """
        if not text:
            return ""

        # 1. Remove phantom images from Marker
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text) 
        
        # 2. Remove phantom citation links like [](1), [](citation)
        text = re.sub(r'\[\]\([^)]*\)', '', text)
        
        # 3. Linearize markdown tables
        text = self._linearize_tables(text)
        
        # 4. Fix broken hyphens (treat- ment -> treatment)
        text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
        
        # 5. Collapse multiple newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 6. Remove/anonymize PII (if enabled)
        if self.remove_pii and self.pii_analyzer:
            text = self._remove_pii(text)
        
        return text.strip()
    
    def _remove_pii(self, text: str) -> str:
        """Detect and anonymize PII using Presidio."""
        try:
            from presidio_anonymizer.entities import OperatorConfig

            results = self.pii_analyzer.analyze(
                text=text,
                language=self._language,
                entities=self._pii_entities,
            )
            
            if not results:
                return text

            operators = {
                entity: OperatorConfig("replace", {"new_value": replacement})
                for entity, replacement in self._pii_replacements.items()
            }

            anonymized = self.pii_anonymizer.anonymize(
                text=text,
                analyzer_results=results,
                operators=operators,
            )
            
            return anonymized.text
        
        except Exception as e:
            logger.error(f"⚠️  PII removal error: {e}")
            if not self._fail_safe:
                raise
            logger.critical("Returning unredacted text due to error.")
            return text

    def _linearize_tables(self, text: str) -> str:
        """Convert markdown tables into linearized text."""
        lines = text.split('\n')
        result = []
        i = 0
        
        while i < len(lines):
            line = lines[i]
            # Simple table detection (contains | and not just a separator line)
            if '|' in line and not re.match(r'^\s*\|[\s:-]+\|', line):
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                
                # Check if next line is a header separator
                is_header = (i + 1 < len(lines) and re.match(r'^\s*\|[\s:-]+\|', lines[i + 1]))
                
                if is_header:
                    result.append(' | '.join(cells))
                    i += 2
                    continue
                elif len(cells) >= 2:
                    # Linearize: "Key: Value, Key2: Value2"
                    linearized = ', '.join([f"{cells[j]}: {cells[j+1]}" for j in range(0, len(cells)-1, 2)])
                    result.append(linearized)
                else:
                    result.append(line)
            else:
                result.append(line)
            i += 1
        
        return '\n'.join(result)
