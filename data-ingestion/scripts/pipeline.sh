#!/bin/bash
# scripts/pipeline.sh
# Medical Data Ingestion Pipeline
# Orchestrates: PDF->Markdown, Cleaning, Vectorization

set -euo pipefail

# Get the project root
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$PROJECT_ROOT/../config/app.yaml"
LOG_FILE="$PROJECT_ROOT/../data/artifacts/ingestion.log"
VENV_DIR="$PROJECT_ROOT/.ingestionenv"

# Validate config exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found at $CONFIG_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

# Source config (using Python for YAML parsing)
source_config() {
    python3 << EOF
import yaml
import os
with open("$CONFIG_FILE") as f:
    config = (yaml.safe_load(f) or {}).get('data_ingestion', {})
    input_dir = os.path.join("$PROJECT_ROOT", config.get('input_dir', '../data/pdfs'))
    raw_dir = os.path.join("$PROJECT_ROOT", config.get('output', {}).get('markdown_dir', '../data/artifacts/markdown'))
    clean_dir = os.path.join("$PROJECT_ROOT", config.get('output', {}).get('cleaned_dir', '../data/artifacts/cleaned'))
    print(f"INPUT_DIR={input_dir}")
    print(f"RAW_DIR={raw_dir}")
    print(f"CLEAN_DIR={clean_dir}")
EOF
}

# Load config variables
eval "$(source_config)"

# Create directories
mkdir -p "$RAW_DIR" "$CLEAN_DIR"
touch "$LOG_FILE"

# Activate virtual environment if enabled
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "✓ Activated virtual environment: $VENV_DIR" | tee -a "$LOG_FILE"
else
    echo "Warning: Virtual environment not found at $VENV_DIR" | tee -a "$LOG_FILE"
    echo "Install with: python3 -m venv $VENV_DIR && source $VENV_DIR/bin/activate && pip install -r $PROJECT_ROOT/requirements.txt" | tee -a "$LOG_FILE"
fi

echo "========================================" | tee -a "$LOG_FILE"
echo "Medical Data Ingestion Pipeline" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Config: $CONFIG_FILE" | tee -a "$LOG_FILE"
echo "Input:  $INPUT_DIR" | tee -a "$LOG_FILE"
echo "Raw:    $RAW_DIR" | tee -a "$LOG_FILE"
echo "Clean:  $CLEAN_DIR" | tee -a "$LOG_FILE"
date | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Track stats
PROCESSED=0
FAILED=0

# Process all PDFs
if [ ! -d "$INPUT_DIR" ]; then
    echo "Error: Input directory not found: $INPUT_DIR" | tee -a "$LOG_FILE"
    exit 1
fi

PDF_COUNT=$(find "$INPUT_DIR" -name "*.pdf" | wc -l)
if [ "$PDF_COUNT" -eq 0 ]; then
    echo "No PDF files found in $INPUT_DIR" | tee -a "$LOG_FILE"
    exit 0
fi

echo "Found $PDF_COUNT PDF files to process" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Process each PDF using while loop to avoid subshell issues
while IFS= read -r pdf_file; do
    
    filename=$(basename "$pdf_file" .pdf)
    echo "================================================" | tee -a "$LOG_FILE"
    echo "Processing: $filename" | tee -a "$LOG_FILE"
    echo "================================================" | tee -a "$LOG_FILE"

    # Step A: PDF to Markdown (Marker OCR)
    echo "Step 1/3: PDF Extraction (PDF -> Markdown)" | tee -a "$LOG_FILE"
    pdf_raw_dir="$RAW_DIR/$filename"
    mkdir -p "$pdf_raw_dir"
    
    if python3 "$PROJECT_ROOT/scripts/run_pipeline.py" --pdf "$pdf_file" --output "$pdf_raw_dir" 2>&1 | tee -a "$LOG_FILE"; then
        echo "✓ PDF extraction complete" | tee -a "$LOG_FILE"
    else
        echo "✗ PDF extraction failed for $filename" | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
        ((FAILED++))
        continue
    fi

    ((PROCESSED++))
    echo "" | tee -a "$LOG_FILE"

done < <(find "$INPUT_DIR" -name "*.pdf")

# Step C: Vectorization (Embed & Index) - Run once for all cleaned documents
echo "================================================" | tee -a "$LOG_FILE"
echo "Step 2/2: Vectorization (Embed & Index)" | tee -a "$LOG_FILE"
echo "================================================" | tee -a "$LOG_FILE"

if python3 "$PROJECT_ROOT/scripts/run_pipeline.py" --vectorize --config "$CONFIG_FILE" --input "$CLEAN_DIR" 2>&1 | tee -a "$LOG_FILE"; then
    echo "✓ Vectorization complete" | tee -a "$LOG_FILE"
else
    echo "✗ Vectorization failed" | tee -a "$LOG_FILE"
    ((FAILED++))
fi
    
echo "" | tee -a "$LOG_FILE"

echo "========================================" | tee -a "$LOG_FILE"
echo "✓ Pipeline Complete" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "Processed: $PROCESSED files" | tee -a "$LOG_FILE"
echo "Failed: $FAILED files" | tee -a "$LOG_FILE"
echo "Output Directory: $CLEAN_DIR" | tee -a "$LOG_FILE"
echo "Log File: $LOG_FILE" | tee -a "$LOG_FILE"
date | tee -a "$LOG_FILE"
