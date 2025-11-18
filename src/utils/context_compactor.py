"""
Context compaction utilities for managing large documents
"""
from typing import List, Dict, Any
import re


class ContextCompactor:
    """Manages context window by compacting and summarizing large documents"""
    
    def __init__(self, max_tokens: int = 8000):
        self.max_tokens = max_tokens
        self.chars_per_token = 4  # Rough estimate
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text"""
        return len(text) // self.chars_per_token
    
    def compact_document(self, text: str, max_tokens: int = None) -> str:
        """Compact a document to fit within token limits"""
        if max_tokens is None:
            max_tokens = self.max_tokens
        
        current_tokens = self.estimate_tokens(text)
        
        if current_tokens <= max_tokens:
            return text
        
        # Apply compaction strategies
        text = self._remove_excessive_whitespace(text)
        text = self._compact_repetitive_sections(text)
        text = self._extract_key_sections(text, max_tokens)
        
        return text
    
    def _remove_excessive_whitespace(self, text: str) -> str:
        """Remove excessive whitespace and blank lines"""
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)
        # Replace multiple newlines with max 2
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    
    def _compact_repetitive_sections(self, text: str) -> str:
        """Identify and compact repetitive sections"""
        # This is a simple implementation
        # In production, you might use more sophisticated methods
        lines = text.split('\n')
        seen = set()
        result = []
        
        for line in lines:
            # Keep line if it's unique or a header
            line_stripped = line.strip()
            if line_stripped.startswith('#') or line_stripped not in seen:
                result.append(line)
                seen.add(line_stripped)
        
        return '\n'.join(result)
    
    def _extract_key_sections(self, text: str, max_tokens: int) -> str:
        """Extract most important sections to fit token limit"""
        max_chars = max_tokens * self.chars_per_token
        
        # Split into sections (by headers)
        sections = self._split_into_sections(text)
        
        # Prioritize sections with headers
        important_sections = []
        remaining_chars = max_chars
        
        for section in sections:
            section_length = len(section)
            if section_length <= remaining_chars:
                important_sections.append(section)
                remaining_chars -= section_length
            else:
                # Truncate last section if needed
                truncated = section[:remaining_chars] + "\n...[Content truncated]"
                important_sections.append(truncated)
                break
        
        return '\n\n'.join(important_sections)
    
    def _split_into_sections(self, text: str) -> List[str]:
        """Split text into sections based on headers"""
        # Split by markdown headers or numbered sections
        sections = re.split(r'\n(?=#{1,3} |\d+\. )', text)
        return [s.strip() for s in sections if s.strip()]
    
    def create_summary(self, text: str, summary_ratio: float = 0.3) -> str:
        """Create a summary by extracting key sentences"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        # Calculate how many sentences to keep
        num_sentences = max(1, int(len(sentences) * summary_ratio))
        
        # Simple extraction: keep first and last sentences of each paragraph
        # and sentences with keywords
        keywords = ['requirement', 'must', 'should', 'critical', 'important', 
                   'process', 'workflow', 'integration', 'test', 'user']
        
        important_sentences = []
        
        for sentence in sentences[:num_sentences]:
            if any(keyword in sentence.lower() for keyword in keywords):
                important_sentences.append(sentence)
        
        # If we don't have enough, add more from the beginning
        if len(important_sentences) < num_sentences:
            important_sentences.extend(
                sentences[:num_sentences - len(important_sentences)]
            )
        
        return ' '.join(important_sentences[:num_sentences])
    
    def chunk_document(
        self, 
        text: str, 
        chunk_size: int = 4000,
        overlap: int = 200
    ) -> List[Dict[str, Any]]:
        """Split document into overlapping chunks for processing"""
        chunks = []
        text_length = len(text)
        chunk_chars = chunk_size * self.chars_per_token
        overlap_chars = overlap * self.chars_per_token
        
        start = 0
        chunk_id = 0
        
        while start < text_length:
            end = min(start + chunk_chars, text_length)
            
            # Try to break at sentence boundary
            if end < text_length:
                sentence_end = text.rfind('.', start, end)
                if sentence_end > start + (chunk_chars // 2):
                    end = sentence_end + 1
            
            chunk = text[start:end].strip()
            
            chunks.append({
                'id': chunk_id,
                'content': chunk,
                'start_pos': start,
                'end_pos': end,
                'tokens': self.estimate_tokens(chunk)
            })
            
            chunk_id += 1
            start = end - overlap_chars
        
        return chunks
    
    def merge_chunked_results(self, results: List[str]) -> str:
        """Merge results from processing multiple chunks"""
        # Remove duplicate content from overlapping sections
        merged = []
        prev_end = ""
        
        for result in results:
            if prev_end and result.startswith(prev_end):
                # Skip overlapping part
                result = result[len(prev_end):]
            
            merged.append(result)
            # Remember last 100 chars for next comparison
            prev_end = result[-100:] if len(result) > 100 else result
        
        return '\n\n'.join(merged)


class ContextManager:
    """Manages context across multiple agent interactions"""
    
    def __init__(self):
        self.context_history = []
        self.compactor = ContextCompactor()
    
    def add_context(self, role: str, content: str, metadata: Dict[str, Any] = None):
        """Add new context entry"""
        self.context_history.append({
            'role': role,
            'content': content,
            'metadata': metadata or {},
            'tokens': self.compactor.estimate_tokens(content)
        })
    
    def get_context(self, max_tokens: int = 6000) -> List[Dict[str, str]]:
        """Get context within token limits"""
        total_tokens = sum(entry['tokens'] for entry in self.context_history)
        
        if total_tokens <= max_tokens:
            return [
                {'role': entry['role'], 'content': entry['content']}
                for entry in self.context_history
            ]
        
        # Need to compact
        return self._compact_context(max_tokens)
    
    def _compact_context(self, max_tokens: int) -> List[Dict[str, str]]:
        """Compact context history to fit token limit"""
        # Keep recent messages and system messages
        compacted = []
        remaining_tokens = max_tokens
        
        # Always keep system messages
        system_messages = [e for e in self.context_history if e['role'] == 'system']
        for msg in system_messages:
            compacted.append({'role': msg['role'], 'content': msg['content']})
            remaining_tokens -= msg['tokens']
        
        # Add recent messages in reverse order
        user_messages = [e for e in self.context_history if e['role'] != 'system']
        for msg in reversed(user_messages):
            if msg['tokens'] <= remaining_tokens:
                compacted.insert(len(system_messages), {
                    'role': msg['role'], 
                    'content': msg['content']
                })
                remaining_tokens -= msg['tokens']
            else:
                # Compact this message
                compacted_content = self.compactor.compact_document(
                    msg['content'], 
                    remaining_tokens
                )
                compacted.insert(len(system_messages), {
                    'role': msg['role'],
                    'content': compacted_content
                })
                break
        
        return compacted
    
    def clear_context(self):
        """Clear all context history"""
        self.context_history = []
    
    def get_summary(self) -> str:
        """Get summary of all context"""
        all_content = '\n\n'.join(
            f"{entry['role']}: {entry['content']}"
            for entry in self.context_history
        )
        return self.compactor.create_summary(all_content)