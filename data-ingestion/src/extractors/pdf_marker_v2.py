import os
import sys
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw
import pypdfium2 as pdfium # Crucial for converting PDF pages to images

# Add project root to path so imports work from any directory
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# --- SURYA IMPORTS ---
from surya.models import load_predictors

# --- CONFIGURATION CLASS ---
class Config:
    """
    Centralized configuration for the OCR pipeline.
    """
    # Languages: Medical docs are often English, but you can add others.
    LANGS = ["en"]

    # Device: On macOS, 'mps' uses the GPU (Apple Silicon).
    # If you get errors, switch this to 'cpu'.
    DEVICE = "mps" 

    # Batch Sizes:
    # Medical PDFs are dense. 
    # DET_BATCH: Layout analysis (SegFormer)
    # REC_BATCH: Text reading (Donut)
    DET_BATCH_SIZE = 2
    REC_BATCH_SIZE = 16
    
    # Rendering Scale: 2 = 144 DPI (Good), 3 = 216 DPI (Better for small text)
    IMAGE_SCALE = 2

    # Paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
    PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")

# --- UTILITIES ---
def initialize_models(device=None):
    """Loads all predictors into memory ONCE."""
    if device is None:
        device = Config.DEVICE
    print(f"Loading models on device: {device}...")
    
    predictors = load_predictors(device=device)
    
    print("Models loaded successfully.")
    return predictors

def load_pdf_images(pdf_path):
    """
    Converts a PDF file into a list of PIL Images.
    Surya needs images to see the text.
    """
    print(f"Rendering PDF: {pdf_path}...")
    pdf = pdfium.PdfDocument(pdf_path)
    images = []
    
    for i, page in enumerate(pdf):
        # Render the page to a bitmap
        bitmap = page.render(
            scale=Config.IMAGE_SCALE, # Higher scale = better OCR accuracy
            rotation=0
        )
        # Convert to PIL Image
        pil_image = bitmap.to_pil()
        images.append(pil_image)
        
    print(f"Converted {len(images)} pages to images.")
    return images

def serialize_surya_results(results):
    """
    Converts Surya's custom result objects into a clean dictionary
    that can be saved as JSON.
    """
    output = []
    for i, result in enumerate(results):
        page_data = {
            "page_number": i + 1,
            "image_bbox": result.image_bbox,
            "text_lines": []
        }
        
        for text_line in result.text_lines:
            page_data["text_lines"].append({
                "text": text_line.text,
                "confidence": round(text_line.confidence, 4),
                "bbox": text_line.bbox, # [x1, y1, x2, y2]
                "polygon": text_line.polygon # [[x1, y1], [x2, y1], ...]
            })
        
        output.append(page_data)
    return output

def visualize_results(image, page_result, save_path):
    """
    Debug Tool: Draws bounding boxes on the image so you can see what Surya detected.
    Green box = High confidence (>= 0.80)
    Red box = Low confidence (< 0.80)
    """
    draw = ImageDraw.Draw(image)
    
    for line in page_result.text_lines:
        # box is [x1, y1, x2, y2]
        box = line.bbox
        confidence = line.confidence
        
        # Color code: Green for sure, Red for unsure
        color = "green" if confidence >= 0.80 else "red"
        
        # Draw the rectangle
        draw.rectangle(box, outline=color, width=2)
        
    image.save(save_path)
    print(f"Saved debug image: {save_path}")


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # 1. Parse Arguments
    parser = argparse.ArgumentParser(description="Extract text from PDF using Surya OCR")
    parser.add_argument("input_pdf", type=str, help="Path to the input PDF file")
    args = parser.parse_args()
    
    # 2. Validation
    input_file = Path(args.input_pdf)
    if not input_file.exists():
        print(f"Error: Input file '{args.input_pdf}' does not exist.")
        sys.exit(1)
    
    # 3. Setup Output Directory
    output_dir = Path(project_root) / "tests" / "test_data"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 4. Initialize Models
    predictors = initialize_models()
    
    # 5. Process PDF
    try:
        # Convert PDF -> Images
        images = load_pdf_images(str(input_file))
        
        # Run OCR using detection and recognition predictors
        print(f"Running OCR on {len(images)} pages...")
        
        detection_predictor = predictors["detection"]
        recognition_predictor = predictors["recognition"]
        
        results = []
        for i, image in enumerate(images):
            print(f"  Processing page {i + 1}/{len(images)}...")
            
            # Run detection on single image
            detection_result = detection_predictor([image])
            
            # Convert PolygonBox objects to bounding boxes for recognition
            # Each bbox should be in format [[x1, y1, x2, y2], ...]
            bboxes = []
            for poly_box in detection_result[0].bboxes:
                # PolygonBox has polygon attribute - get the bounding box
                if hasattr(poly_box, 'polygon') and len(poly_box.polygon) > 0:
                    xs = [p[0] for p in poly_box.polygon]
                    ys = [p[1] for p in poly_box.polygon]
                    bbox = [[min(xs), min(ys), max(xs), max(ys)]]
                    bboxes.extend(bbox)
            
            # Run recognition with converted bboxes
            if bboxes:
                recognition_result = recognition_predictor(images=[image], bboxes=[bboxes])
                results.append(recognition_result[0])
        
        # 6. Save Results
        json_output = serialize_surya_results(results)
        
        # 7. Save Debug Images (Visual Validation)
        debug_dir = output_dir / "debug_viz"
        debug_dir.mkdir(exist_ok=True)
        
        print("\n🔍 Generating debug visualizations...")
        for i, (image, result) in enumerate(zip(images, results)):
            # We pass a copy so we don't draw on the original in memory
            visualize_results(
                image.copy(),
                result, 
                debug_dir / f"page_{i+1}_debug.png"
            )
        
        # Save JSON (same as before)
        output_filename = f"{input_file.stem}_ocr.json"
        output_path = output_dir / output_filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_output, f, indent=2, ensure_ascii=False)
            
        print(f"\nSuccess! JSON saved to: {output_path}")
        print(f"Check {debug_dir} to see the visualized OCR boxes.")

    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()