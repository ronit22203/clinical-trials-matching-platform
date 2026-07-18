#!/usr/bin/env python3
"""
Medical Data Ingestion Pipeline - Main Entry Point
Orchestrates the complete pipeline: 
  PDF -> Surya OCR (_ocr.json) -> Converter (_converted.md) -> Cleaner (_cleaned.md) -> Chunker (_chunks.json) -> Vectorizer
"""

import sys
import argparse
import logging
import json
from pathlib import Path
from datetime import datetime

# Get project root (1 level up from this script: scripts/run_pipeline.py)
PROJECT_ROOT = Path(__file__).parent.parent
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.determinism import DeterminismTracker
from src.config_loader import load_ingestion_config
from src.extractors.pdf_marker_v2 import initialize_models, load_pdf_images, serialize_surya_results
from src.extractors.surya_converter import SuryaToMarkdown
from src.processors.cleaner import TextCleaner
from src.processors.chunker import MarkdownChunker
from src.storage.embedder import MedicalVectorizer


class PipelineLogger:
    """Setup and manage logging for the pipeline with comprehensive traceability"""
    
    @staticmethod
    def setup(log_file: str, config: dict = None) -> logging.Logger:
        """Setup dual logging: console (INFO) and rotating file (DEBUG)"""
        from logging.handlers import RotatingFileHandler

        log_cfg = (config or {}).get('logging', {})
        console_level_name = log_cfg.get('console_level', 'INFO')
        file_level_name    = log_cfg.get('file_level', 'DEBUG')
        max_bytes          = log_cfg.get('max_size_mb', 50) * 1024 * 1024
        backup_count       = log_cfg.get('backup_count', 3)

        logger = logging.getLogger("pipeline")
        logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers to avoid duplicates
        logger.handlers.clear()
        
        # Ensure log directory exists
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, console_level_name.upper(), logging.INFO))
        
        # Rotating file handler
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, file_level_name.upper(), logging.DEBUG))
        
        # Rich formatter with timestamps and colors for console
        console_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # Detailed formatter for file (includes function info)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_handler.setFormatter(console_formatter)
        file_handler.setFormatter(file_formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
        # Configure child loggers (for imported modules)
        logging.getLogger('src').setLevel(logging.DEBUG)
        logging.getLogger('presidio_analyzer').setLevel(logging.WARNING)  # Reduce noise
        logging.getLogger('presidio_anonymizer').setLevel(logging.WARNING)
        
        # Add file header
        logger.info("="*80)
        logger.info("MEDICAL DATA INGESTION PIPELINE - LOG START")
        logger.info("="*80)
        
        return logger


class MedicalDataPipeline:
    """Main pipeline orchestrator with full traceability"""
    
    def __init__(self, config_path: str = None):
        """Initialize pipeline with configuration"""
        if config_path is None:
            config_path = REPO_ROOT / "config" / "app.yaml"
        
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        self.config = load_ingestion_config(self.config_path)
        
        self.project_root = PROJECT_ROOT
        self.log_file = self.project_root / self.config.get('log_file', 'logs/ingestion.log')
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = PipelineLogger.setup(str(self.log_file), config=self.config)
        
        # Resolve paths from config - organized logically
        self.input_dir = self._resolve_path(self.config.get('input_dir', '../data/pdfs'))
        
        # Processing stages from config.output
        output_config = self.config.get('output', {})
        self.ocr_dir = self._resolve_path(output_config.get('ocr_dir', '../data/artifacts/extract'))
        self.markdown_dir = self._resolve_path(output_config.get('markdown_dir', '../data/artifacts/convert'))
        self.cleaned_dir = self._resolve_path(output_config.get('cleaned_dir', '../data/artifacts/clean'))
        self.chunks_dir = self._resolve_path(output_config.get('chunks_dir', '../data/artifacts/chunk'))
        
        # Create all necessary directories
        for directory in [self.input_dir, self.ocr_dir, self.markdown_dir,
                          self.cleaned_dir, self.chunks_dir]:
            directory.mkdir(parents=True, exist_ok=True)
        
        # Determinism tracking
        self.tracker = DeterminismTracker()
    
    def _resolve_path(self, relative_path: str) -> Path:
        """Resolve paths relative to project root"""
        if relative_path.startswith('/'):
            return Path(relative_path)
        return self.project_root / relative_path
    
    def log_header(self, text: str):
        """Log section header"""
        header = "=" * 60
        self.logger.info("")
        self.logger.info(header)
        self.logger.info(text)
        self.logger.info(header)
    
    def run(self, input_dir: str = None, skip_ocr: bool = False, skip_convert: bool = False,
            skip_clean: bool = False, skip_chunk: bool = False, skip_vectorize: bool = False,
            skip_graph: bool = False, max_pdfs: int = 0):
        """Run the complete pipeline"""
        self.log_header("Medical Data Ingestion Pipeline Started")
        self.logger.info(f"Config: {self.config_path}")
        self.logger.info(f"Input:  {self.input_dir}")
        self.logger.info("Pipeline outputs:")
        self.logger.info(f"  OCR:      {self.ocr_dir}")
        self.logger.info(f"  Markdown: {self.markdown_dir}")
        self.logger.info(f"  Cleaned:  {self.cleaned_dir}")
        self.logger.info(f"  Chunks:   {self.chunks_dir}")
        self.logger.info(f"Log:    {self.log_file}")
        self.logger.info(f"Timestamp: {datetime.now().strftime('%a %b %d %H:%M:%S %Z %Y')}")
        
        # Override input dir if provided
        if input_dir:
            self.input_dir = self._resolve_path(input_dir)
        
        if not self.input_dir.exists():
            self.logger.error(f"Input directory not found: {self.input_dir}")
            return False
        
        # Find PDFs
        pdf_files = list(self.input_dir.glob("**/*.pdf"))
        if not pdf_files:
            self.logger.warning(f"No PDF files found in {self.input_dir}")
            return True
        
        self.logger.info(f"Found {len(pdf_files)} PDF file(s) to process")
        if max_pdfs and max_pdfs > 0:
            pdf_files = pdf_files[:max_pdfs]
            self.logger.info(f"Limiting to {max_pdfs} PDF(s) (--max-pdfs)")
        self.logger.info("")
        
        successful = 0
        failed = 0
        failed_files = []
        
        # Load models once for all PDFs (significant time savings)
        if not skip_ocr:
            self.logger.info("Initializing Surya OCR models...")
            try:
                ocr_config = self.config.get('ocr', {})
                device = ocr_config.get('device', 'mps')
                self.predictors = initialize_models(device=device)
            except Exception as e:
                self.logger.error(f"Failed to initialize models: {e}")
                return False
        
        # Process each PDF
        for idx, pdf_file in enumerate(pdf_files, 1):
            self.logger.info("")
            self.logger.info(f"[{idx}/{len(pdf_files)}] Processing: {pdf_file}")

            # Derive a unique slug from the PDF's position in the directory tree.
            # For acquisition-structured paths (.../10.64898/2026.03.17.26348414/paper.pdf)
            # the parent dir name is the document ID.
            # When input_dir is the PDF's immediate parent (e.g. deterministic-run passes
            # --input-dir as the DOI directory), rel.parent == "." and rel.stem is a generic
            # name like "paper". In that case, climb up one level in the real filesystem to
            # recover the meaningful DOI slug (e.g. "2026.03.17.26348414").
            _GENERIC_PDF_STEMS = {
                "paper", "fulltext", "document", "manuscript",
                "article", "preprint", "doc", "file", "main",
            }
            rel = pdf_file.relative_to(self.input_dir)
            if str(rel.parent) != ".":
                filename = rel.parent.name
            elif rel.stem.lower() not in _GENERIC_PDF_STEMS:
                filename = rel.stem          # e.g. "sepsis_falsification"
            else:
                filename = pdf_file.parent.name  # e.g. "2026.03.17.26348414"

            # source_id is the full relative path — unique even if two docs share a parent name
            source_id = str(rel)

            # Register document and start a tracked execution
            doc_uuid = self.tracker.register_document(source_id)
            hyperparameters = {
                "ocr": self.config.get('ocr', {}),
                "chunking": self.config.get('chunking', {}),
                "vectorization": {
                    k: v for k, v in self.config.get('vectorization', {}).items()
                    if k != 'qdrant_url'  # exclude infra details from hyperparams
                },
            }
            exec_uuid = self.tracker.start_execution(doc_uuid, hyperparameters=hyperparameters)
            self.logger.info(f"  Tracking: doc={doc_uuid[:8]}... exec={exec_uuid[:8]}...")
            self.logger.info(f"  Slug: {filename}")
            
            exec_status = "failed"
            try:
                # Stage 1: PDF to OCR JSON (Surya)
                ocr_json_path = self.ocr_dir / f"{filename}_ocr.json"
                if not skip_ocr:
                    if ocr_json_path.exists():
                        self.logger.info(f"  Stage 1/5: OCR skipped (already exists: {ocr_json_path.name})")
                    else:
                        self.logger.info("  Stage 1/5: PDF → OCR JSON (Surya)")
                        ocr_json_path = self._stage1_ocr(pdf_file, filename)
                        self.logger.info(f"  ✓ OCR complete: {ocr_json_path.name}")
                        self.tracker.record_stage(exec_uuid, "extract",
                                                  ocr_json_path.read_text(encoding="utf-8"),
                                                  artifact_ext="json")
                else:
                    self.logger.info("  Stage 1/5: Skipped (--skip-ocr)")
                
                # Stage 2: OCR JSON to Markdown (Surya Converter)
                if not skip_convert:
                    self.logger.info("  Stage 2/5: OCR JSON → Markdown")
                    converted_md_path = self._stage2_convert(ocr_json_path, filename)
                    self.logger.info(f"  ✓ Conversion complete: {converted_md_path.name}")
                    self.tracker.record_stage(exec_uuid, "convert",
                                              converted_md_path.read_text(encoding="utf-8"),
                                              artifact_ext="md")
                else:
                    self.logger.info("  Stage 2/5: Skipped (--skip-convert)")
                    converted_md_path = self.markdown_dir / f"{filename}_converted.md"
                
                # Stage 3: Clean Markdown
                if not skip_clean:
                    self.logger.info("  Stage 3/5: Markdown → Cleaned")
                    cleaned_md_path = self._stage3_clean(converted_md_path, filename)
                    self.logger.info(f"  ✓ Cleaning complete: {cleaned_md_path.name}")
                    self.tracker.record_stage(exec_uuid, "clean",
                                              cleaned_md_path.read_text(encoding="utf-8"),
                                              artifact_ext="md")
                else:
                    self.logger.info("  Stage 3/5: Skipped (--skip-clean)")
                    cleaned_md_path = self.cleaned_dir / f"{filename}_cleaned.md"
                
                # Stage 4: Chunk Markdown
                if not skip_chunk:
                    self.logger.info("  Stage 4/5: Markdown → Chunks")
                    chunks_json_path = self._stage4_chunk(cleaned_md_path, filename)
                    self.logger.info(f"  ✓ Chunking complete: {chunks_json_path.name}")
                    self.tracker.record_stage(exec_uuid, "chunk",
                                              chunks_json_path.read_text(encoding="utf-8"),
                                              artifact_ext="json")
                else:
                    self.logger.info("  Stage 4/5: Skipped (--skip-chunk)")
                
                exec_status = "completed"
                successful += 1
                
            except Exception as e:
                self.logger.error(f"  ✗ Failed processing {filename}: {e}")
                import traceback
                self.logger.error(f"  Traceback: {traceback.format_exc()}")
                failed += 1
                failed_files.append(filename)
            finally:
                self.tracker.complete_execution(exec_uuid, status=exec_status)
        
        # Stage 5: Vectorization (once for all files)
        if not skip_vectorize and (successful > 0 or not skip_clean):
            self.logger.info("")
            self.logger.info("Stage 5/5: Vectorization (Embed & Index)")
            try:
                self._stage5_vectorize()
                self.logger.info("✓ Vectorization complete")
            except Exception as e:
                self.logger.error(f"✗ Vectorization failed: {e}")
                import traceback
                self.logger.error(f"  Traceback: {traceback.format_exc()}")
        elif skip_vectorize:
            self.logger.info("")
            self.logger.info("Stage 5/6: Skipped (--skip-vectorize)")
        
        # Stage 6: Knowledge Graph (entity extraction → Neo4j)
        kg_cfg = self.config.get("knowledge_graph", {})
        if not skip_graph and kg_cfg.get("enabled", False) and (successful > 0 or not skip_chunk):
            self.logger.info("")
            self.logger.info("Stage 6/6: Knowledge Graph (Entity Extraction → Neo4j)")
            try:
                self._stage6_knowledge_graph()
                self.logger.info("✓ Knowledge graph stage complete")
            except Exception as e:
                self.logger.error(f"✗ Knowledge graph stage failed: {e}")
                import traceback
                self.logger.error(f"  Traceback: {traceback.format_exc()}")
        elif skip_graph:
            self.logger.info("")
            self.logger.info("Stage 6/6: Skipped (--skip-graph)")
        elif not kg_cfg.get("enabled", False):
            self.logger.info("")
            self.logger.info("Stage 6/6: Skipped (knowledge_graph.enabled=false in config)")
        
        # Summary
        self.log_header("Pipeline Complete")
        self.logger.info(f"Processed: {successful}/{len(pdf_files)} successful")
        if failed > 0:
            self.logger.warning(f"Failed: {failed} file(s)")
            for f in failed_files:
                self.logger.warning(f"  - {f}")
        self.logger.info("")
        self.logger.info("Output locations:")
        self.logger.info(f"  OCR JSONs:    {self.ocr_dir}")
        self.logger.info(f"  Markdown:     {self.markdown_dir}")
        self.logger.info(f"  Cleaned:      {self.cleaned_dir}")
        self.logger.info(f"  Chunks:       {self.chunks_dir}")
        self.logger.info(f"Log: {self.log_file}")
        
        return failed == 0
    
    def _stage1_ocr(self, pdf_file: Path, filename: str) -> Path:
        """Stage 1: PDF -> OCR JSON using Surya"""
        pdf_ocr_dir = self.ocr_dir / filename
        pdf_ocr_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Convert PDF to images
            images = load_pdf_images(str(pdf_file))
            self.logger.info(f"    • Rendered {len(images)} pages")
            
            # Run OCR
            detection_predictor = self.predictors["detection"]
            recognition_predictor = self.predictors["recognition"]
            
            results = []
            for i, image in enumerate(images):
                self.logger.debug(f"    • OCR page {i + 1}/{len(images)}")
                
                # Detection
                detection_result = detection_predictor([image])
                
                # Convert polygons to bboxes
                bboxes = []
                for poly_box in detection_result[0].bboxes:
                    if hasattr(poly_box, 'polygon') and len(poly_box.polygon) > 0:
                        xs = [p[0] for p in poly_box.polygon]
                        ys = [p[1] for p in poly_box.polygon]
                        bbox = [[min(xs), min(ys), max(xs), max(ys)]]
                        bboxes.extend(bbox)
                
                # Recognition
                if bboxes:
                    recognition_result = recognition_predictor(images=[image], bboxes=[bboxes])
                    results.append(recognition_result[0])
            
            # Serialize results
            json_output = serialize_surya_results(results)
            
            # Save OCR JSON
            ocr_json_path = self.ocr_dir / f"{filename}_ocr.json"
            with open(ocr_json_path, 'w', encoding='utf-8') as f:
                json.dump(json_output, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"    • Saved OCR JSON: {ocr_json_path.name}")
            
            # Save debug visualizations (toggled by config)
            if self.config.get('ocr', {}).get('save_debug_images', True):
                self._save_debug_images(images, results, pdf_ocr_dir, filename)
            
            return ocr_json_path
            
        except Exception as e:
            raise RuntimeError(f"Stage 1 (OCR) failed: {str(e)}")
    
    def _save_debug_images(self, images, results, output_dir, filename):
        """Save debug visualization images with OCR boxes"""
        from PIL import ImageDraw
        
        confidence_threshold = self.config.get('ocr', {}).get('confidence_threshold', 0.80)
        
        debug_dir = output_dir / "debug_visualizations"
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        for i, (image, result) in enumerate(zip(images, results)):
            image_copy = image.copy()
            draw = ImageDraw.Draw(image_copy)
            
            # Draw bounding boxes
            for line in result.text_lines:
                box = line.bbox
                confidence = line.confidence
                color = "green" if confidence >= confidence_threshold else "red"
                draw.rectangle(box, outline=color, width=2)
            
            # Save debug image
            debug_image_path = debug_dir / f"{filename}_page_{i+1:03d}_debug.png"
            image_copy.save(debug_image_path)
            self.logger.debug(f"    • Saved debug image: {debug_image_path.name}")
    
    def _stage2_convert(self, ocr_json_path: Path, filename: str) -> Path:
        """Stage 2: OCR JSON -> Markdown using SuryaToMarkdown"""
        try:
            # Load OCR JSON
            with open(ocr_json_path, 'r', encoding='utf-8') as f:
                ocr_data = json.load(f)
            
            # Convert to markdown
            converter = SuryaToMarkdown(config=self.config)
            markdown_output = converter.convert(ocr_data)
            
            # Save converted markdown
            converted_md_path = self.markdown_dir / f"{filename}_converted.md"
            with open(converted_md_path, 'w', encoding='utf-8') as f:
                f.write(markdown_output)
            
            self.logger.info(f"    • Converted markdown size: {len(markdown_output)} chars")
            
            return converted_md_path
            
        except Exception as e:
            raise RuntimeError(f"Stage 2 (Conversion) failed: {str(e)}")
    
    def _stage3_clean(self, converted_md_path: Path, filename: str) -> Path:
        """Stage 3: Clean Markdown"""
        try:
            # Read converted markdown
            with open(converted_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_size = len(content)
            
            # Clean
            cleaner = TextCleaner(config=self.config)
            cleaned = cleaner.clean(content)
            cleaned_size = len(cleaned)
            
            # Save cleaned markdown
            cleaned_md_path = self.cleaned_dir / f"{filename}_cleaned.md"
            with open(cleaned_md_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            
            reduction_pct = 100 - (100 * cleaned_size // original_size)
            self.logger.info(f"    • Size reduction: {original_size} → {cleaned_size} chars ({reduction_pct}% removed)")
            
            return cleaned_md_path
            
        except Exception as e:
            raise RuntimeError(f"Stage 3 (Cleaning) failed: {str(e)}")
    
    def _stage4_chunk(self, cleaned_md_path: Path, filename: str) -> Path:
        """Stage 4: Chunk Markdown into JSON with metadata"""
        try:
            # Read cleaned markdown
            with open(cleaned_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Chunk - use config values
            chunk_config = self.config.get('chunking', {})
            max_tokens = chunk_config.get('max_tokens', 500)
            chunk_overlap = chunk_config.get('chunk_overlap', 0)
            min_chunk_tokens = chunk_config.get('min_chunk_tokens', 0)
            
            chunker = MarkdownChunker(
                max_tokens=max_tokens,
                chunk_overlap=chunk_overlap,
                min_chunk_tokens=min_chunk_tokens,
            )
            chunks = chunker.chunk(content)
            
            # Create output with metadata
            output_data = {
                "filename": filename,
                "source_file": cleaned_md_path.name,
                "total_chunks": len(chunks),
                "chunk_config": {
                    "max_tokens": max_tokens,
                    "chunk_overlap": chunk_overlap
                },
                "chunks": chunks
            }
            
            # Save chunks JSON
            chunks_json_path = self.chunks_dir / f"{filename}_chunks.json"
            with open(chunks_json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"    • Created {len(chunks)} chunks (config: max_tokens={max_tokens})")
            
            return chunks_json_path
            
        except Exception as e:
            raise RuntimeError(f"Stage 4 (Chunking) failed: {str(e)}")
    
    def _stage5_vectorize(self):
        """Stage 5: Vectorize all cleaned documents"""
        self.logger.info("  • Initializing vectorizer...")
        vectorizer = MedicalVectorizer(config=self.config)
        
        self.logger.info(f"  • Model: {self.config.get('vectorization', {}).get('model_name', 'BAAI/bge-small-en-v1.5')}")
        self.logger.info(f"  • Embedding dimension: {vectorizer.embedding_dim}")
        self.logger.info(f"  • Qdrant URL: {self.config.get('vectorization', {}).get('qdrant_url', 'http://localhost:6333')}")
        self.logger.info(f"  • Collection: {vectorizer.collection_name}")
        
        self.logger.info(f"  • Processing: {self.cleaned_dir}")
        vectorizer.run(str(self.cleaned_dir))
        self.logger.info("  ✓ Vectorization complete")


    def _stage6_knowledge_graph(self):
        """Stage 6: Extract (head, relation, tail) triplets via BioMistral and write to Neo4j."""
        sys.path.insert(0, str(Path(__file__).parent))
        from build_knowledge_graph import KnowledgeGraphBuilder

        self.logger.info(f"  • Model: {self.config.get('knowledge_graph', {}).get('model', 'cniongolo/biomistral:latest')}")
        self.logger.info(f"  • Neo4j: {self.config.get('neo4j', {}).get('uri', 'bolt://localhost:7687')}")
        self.logger.info(f"  • Chunks: {self.chunks_dir}")

        builder = KnowledgeGraphBuilder(self.config)
        try:
            builder.run(self.chunks_dir)
        finally:
            builder.close()


def main():
    parser = argparse.ArgumentParser(
        description="Medical Data Ingestion Pipeline - 6 Stages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Pipeline Stages:
  1. PDF → OCR JSON      (Surya)
  2. OCR JSON → Markdown (SuryaToMarkdown converter)
  3. Markdown → Cleaned  (TextCleaner)
  4. Cleaned → Chunks    (MarkdownChunker)
  5. Chunks → Vectors    (MedicalVectorizer → Qdrant)
  6. Chunks → Graph      (BioMistral triplet extraction → Neo4j)

Examples:
  python scripts/run_pipeline.py                           # Run full pipeline
  python scripts/run_pipeline.py --max-pdfs 2             # Process first 2 PDFs only
  python scripts/run_pipeline.py --skip-ocr               # Skip OCR (use existing artifacts)
  python scripts/run_pipeline.py --skip-graph             # Skip Neo4j stage
  python scripts/run_pipeline.py --input-dir ../data/pdfs   # Override input dir
        """
    )
    
    parser.add_argument(
        '-c', '--config',
        help='Path to config.yaml file (default: ../config/app.yaml)'
    )
    parser.add_argument(
        '-i', '--input-dir',
        help='Override input directory for PDFs'
    )
    parser.add_argument(
        '--max-pdfs',
        type=int,
        default=0,
        help='Limit processing to the first N PDFs (0 = no limit)'
    )
    parser.add_argument(
        '--skip-ocr',
        action='store_true',
        help='Skip stage 1: PDF → OCR JSON'
    )
    parser.add_argument(
        '--skip-convert',
        action='store_true',
        help='Skip stage 2: OCR JSON → Markdown'
    )
    parser.add_argument(
        '--skip-clean',
        action='store_true',
        help='Skip stage 3: Clean Markdown'
    )
    parser.add_argument(
        '--skip-chunk',
        action='store_true',
        help='Skip stage 4: Chunk Markdown'
    )
    parser.add_argument(
        '--skip-vectorize',
        action='store_true',
        help='Skip stage 5: Vectorization'
    )
    parser.add_argument(
        '--skip-graph',
        action='store_true',
        help='Skip stage 6: Knowledge graph (Neo4j entity extraction)'
    )
    
    args = parser.parse_args()
    
    try:
        pipeline = MedicalDataPipeline(config_path=args.config)
        success = pipeline.run(
            input_dir=args.input_dir,
            skip_ocr=args.skip_ocr,
            skip_convert=args.skip_convert,
            skip_clean=args.skip_clean,
            skip_chunk=args.skip_chunk,
            skip_vectorize=args.skip_vectorize,
            skip_graph=args.skip_graph,
            max_pdfs=args.max_pdfs,
        )
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
