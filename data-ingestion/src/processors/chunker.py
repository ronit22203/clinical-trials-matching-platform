import re
from typing import List, Dict

# Patterns that mark a chunk as a preprint header/footer watermark.
# Each entry is a compiled case-insensitive pattern; matching ANY of them
# tags the chunk as boilerplate so it can be excluded from indexing.
_BOILERPLATE_PATTERNS: List[re.Pattern] = [
    re.compile(r"medrxiv preprint doi", re.IGNORECASE),
    re.compile(r"biorxiv preprint doi", re.IGNORECASE),
    re.compile(r"certified by peer review", re.IGNORECASE),
    re.compile(r"copyright holder for this preprint", re.IGNORECASE),
    re.compile(r"perpetual embargo", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    # OCR-garbled disclaimer lines ("This spraint reputs new tesearch…")
    re.compile(r"spraint reputs", re.IGNORECASE),
]


def _is_boilerplate(text: str) -> bool:
    """Return True if *text* matches any known preprint header/footer pattern."""
    return any(p.search(text) for p in _BOILERPLATE_PATTERNS)


class MarkdownChunker:
    """Context-aware hierarchical chunker for medical markdown documents."""
    
    def __init__(self, max_tokens: int = 512, chunk_overlap: int = 0, min_chunk_tokens: int = 0):
        """
        Args:
            max_tokens: Maximum tokens per chunk (rough estimate: 1 token ≈ 4 chars).
            chunk_overlap: Token overlap between consecutive chunks (sliding window).
                           Applied only when a section is split by _split_large_section.
            min_chunk_tokens: Discard chunks smaller than this (noise filter). 0 = disabled.
        """
        self.max_tokens = max_tokens
        self.chunk_overlap = chunk_overlap
        self.min_chunk_tokens = min_chunk_tokens
    
    def chunk(self, text: str) -> List[Dict[str, str]]:
        """
        Split markdown into context-aware chunks.
        
        Returns:
            List of dicts with 'content', 'context', 'level', 'char_start', 'char_end' keys.
            char_start/char_end are character offsets of the raw section content in *text*.
        """
        sections = self._parse_sections(text)
        chunks = []
        
        # Fallback: If no sections found (no headers), create a dummy section to force splitting
        if not sections and text.strip():
            sections = [{
                'context_path': 'Document Body',
                'level': 1,
                'content': text,
                'page_number': 1,
                'char_start': 0,
                'char_end': len(text),
            }]
        
        for section in sections:
            chunk_text = self._build_chunk_with_context(section)
            
            # Rule B: If section <max_tokens, keep it whole
            if self._estimate_tokens(chunk_text) <= self.max_tokens:
                chunks.append({
                    'content': chunk_text,
                    'context': section['context_path'],
                    'level': section['level'],
                    'page_number': section.get('page_number', 1),
                    'is_boilerplate': _is_boilerplate(chunk_text),
                    'char_start': section.get('char_start'),
                    'char_end': section.get('char_end'),
                })
            else:
                # Split large sections while preserving context
                chunks.extend(self._split_large_section(section))
        
        # Apply min_chunk_tokens filter
        if self.min_chunk_tokens > 0:
            chunks = [c for c in chunks if self._estimate_tokens(c['content']) >= self.min_chunk_tokens]
        
        return chunks
    
    def _parse_sections(self, text: str) -> List[Dict]:
        """Parse markdown into hierarchical sections (the tree structure)."""
        lines = text.split('\n')

        # Precompute the character start offset of each line in the original text.
        line_offsets: List[int] = []
        cursor = 0
        for line in lines:
            line_offsets.append(cursor)
            cursor += len(line) + 1  # +1 for the '\n' separator

        sections = []
        current_headers = ['', '', '', '']  # H1, H2, H3, H4
        current_content: List[str] = []
        current_level = 0
        current_page_number = 1  # Default to page 1
        content_start_line: int = -1   # index of the first content line in the current section
        content_end_line: int = -1     # index of the last content line in the current section
        
        for line_idx, line in enumerate(lines):
            # Step 0: Check for page markers - treat as mandatory section breaks
            page_match = re.match(r'^<!--\s*PAGE:\s*(\d+)\s*-->$', line)
            if page_match:
                # Save previous section if we have content
                if current_content:
                    sections.append(self._create_section(
                        current_headers, current_level, current_content, current_page_number,
                        char_start=line_offsets[content_start_line],
                        char_end=line_offsets[content_end_line] + len(lines[content_end_line]),
                    ))
                    current_content = []
                    content_start_line = -1
                    content_end_line = -1
                
                current_page_number = int(page_match.group(1))
                continue
            
            # Step 1: Identify headers (lines starting with #)
            header_match = re.match(r'^(#{1,4})\s+(.+)$', line)
            
            if header_match:
                # Save previous section if exists
                if current_content:
                    sections.append(self._create_section(
                        current_headers, current_level, current_content, current_page_number,
                        char_start=line_offsets[content_start_line],
                        char_end=line_offsets[content_end_line] + len(lines[content_end_line]),
                    ))
                    current_content = []
                    content_start_line = -1
                    content_end_line = -1
                
                # Step 2: Update header hierarchy (parent-child relationships)
                level = len(header_match.group(1))
                current_level = level
                current_headers[level - 1] = header_match.group(2)
                
                # Clear child headers (maintain tree structure)
                for i in range(level, 4):
                    current_headers[i] = ''
            else:
                if not current_content:
                    content_start_line = line_idx
                current_content.append(line)
                content_end_line = line_idx
        
        # Save last section
        if current_content:
            sections.append(self._create_section(
                current_headers, current_level, current_content, current_page_number,
                char_start=line_offsets[content_start_line],
                char_end=line_offsets[content_end_line] + len(lines[content_end_line]),
            ))
        
        return sections
    
    def _create_section(
        self,
        headers: List[str],
        level: int,
        content: List[str],
        page_number: int = 1,
        char_start: int = None,
        char_end: int = None,
    ) -> Dict:
        """Create a section with its full context path and byte-range in the source text."""
        # Build breadcrumb: "Clinical Studies > Efficacy Results"
        context_parts = [h for h in headers[:level] if h]
        return {
            'context_path': ' > '.join(context_parts),
            'level': level,
            'content': '\n'.join(content).strip(),
            'headers': headers.copy(),
            'page_number': page_number,
            'char_start': char_start,
            'char_end': char_end,
        }
    
    def _build_chunk_with_context(self, section: Dict) -> str:
        """
        Step 3 Rule C: Prepend context breadcrumb to content.
        
        Example:
            Context: Clinical Studies > Efficacy Results
            
            The drug showed 50% improvement...
        """
        if section['context_path']:
            return f"Context: {section['context_path']}\n\n{section['content']}"
        return section['content']
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (1 token ≈ 4 chars for English)."""
        return len(text) // 4
    
    def _split_large_section(self, section: Dict) -> List[Dict]:
        """Split large sections while preserving context and respecting atomic blocks.
        
        When chunk_overlap > 0, consecutive chunks share trailing/leading paragraphs
        so that concepts spanning a boundary are present in both chunks.
        char_start/char_end on each output chunk reflect the paragraph range within
        the original source text.
        """
        chunks = []
        content = section['content']
        page_number = section.get('page_number', 1)
        section_char_start: int | None = section.get('char_start')
        
        # Rule A: Never split lists or code blocks (unless oversized)
        if self._is_atomic_block(content):
            chunk_text = self._build_chunk_with_context(section)
            return [{
                'content': chunk_text,
                'context': section['context_path'],
                'level': section['level'],
                'page_number': page_number,
                'is_boilerplate': _is_boilerplate(chunk_text),
                'char_start': section_char_start,
                'char_end': section.get('char_end'),
            }]
        
        # Split by paragraphs (natural boundaries)
        paragraphs = content.split('\n\n')

        # Precompute each paragraph's (start, end) offset within the section content string.
        para_ranges: List[tuple[int, int]] = []
        search_pos = 0
        for para in paragraphs:
            idx = content.find(para, search_pos)
            if idx == -1:
                # Fallback: keep search_pos advancing monotonically
                para_ranges.append((search_pos, search_pos + len(para)))
                search_pos += len(para) + 2  # +2 for '\n\n'
            else:
                para_ranges.append((idx, idx + len(para)))
                search_pos = idx + len(para)

        current_paras: List[str] = []
        current_para_indices: List[int] = []

        def _make_chunk(paras: List[str], para_indices: List[int]) -> Dict:
            chunk_content = '\n\n'.join(paras)
            text = f"Context: {section['context_path']}\n\n{chunk_content}"
            # Derive absolute char offsets from the first/last paragraph ranges.
            if section_char_start is not None and para_indices:
                c_start = section_char_start + para_ranges[para_indices[0]][0]
                c_end = section_char_start + para_ranges[para_indices[-1]][1]
            else:
                c_start = None
                c_end = None
            return {
                'content': text,
                'context': section['context_path'],
                'level': section['level'],
                'page_number': page_number,
                'is_boilerplate': _is_boilerplate(text),
                'char_start': c_start,
                'char_end': c_end,
            }
        
        for p_idx, para in enumerate(paragraphs):
            test_content = '\n\n'.join(current_paras + [para])
            test_chunk = f"Context: {section['context_path']}\n\n{test_content}"
            
            if self._estimate_tokens(test_chunk) > self.max_tokens and current_paras:
                chunks.append(_make_chunk(current_paras, current_para_indices))
                
                # Sliding-window overlap: carry over trailing paragraphs
                if self.chunk_overlap > 0:
                    overlap_paras: List[str] = []
                    overlap_indices: List[int] = []
                    overlap_tokens = 0
                    for op, oi in zip(reversed(current_paras), reversed(current_para_indices)):
                        p_tokens = self._estimate_tokens(op)
                        if overlap_tokens + p_tokens > self.chunk_overlap:
                            break
                        overlap_paras.insert(0, op)
                        overlap_indices.insert(0, oi)
                        overlap_tokens += p_tokens
                    current_paras = overlap_paras + [para]
                    current_para_indices = overlap_indices + [p_idx]
                else:
                    current_paras = [para]
                    current_para_indices = [p_idx]
            else:
                current_paras.append(para)
                current_para_indices.append(p_idx)
        
        # Add remaining content
        if current_paras:
            chunks.append(_make_chunk(current_paras, current_para_indices))
        
        return chunks
    
    def _is_atomic_block(self, text: str) -> bool:
        """
        Rule A: Check if content is a list or code block that shouldn't be split.
        However, if the 'atomic' block is already over our limit, we must split it anyway.
        """
        # If the atomic block is oversized, don't protect it - allow splitting
        if self._estimate_tokens(text) > self.max_tokens:
            return False
        
        # Check for markdown lists (-, *, +)
        if re.search(r'^\s*[-*+]\s', text, re.MULTILINE):
            return True
        # Check for numbered lists
        if re.search(r'^\s*\d+\.\s', text, re.MULTILINE):
            return True
        # Check for code blocks
        if '```' in text:
            return True
        return False
