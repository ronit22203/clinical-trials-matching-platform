#!/usr/bin/env python3
"""
Download medical PDFs from bioRxiv.

Usage:
    python biorxiv_downloader.py --keywords cancer,heart,brain --max-papers 20
    python biorxiv_downloader.py --category oncology --max-papers 10
"""

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import arxiv
import requests
from medical_keywords import MEDICAL_KEYWORDS


class BioRxivDownloader:
    """Download medical PDFs from bioRxiv."""

    def __init__(self, pdf_dir: str = "./pdfs"):
        self.pdf_dir = Path(pdf_dir)
        self.pdf_dir.mkdir(exist_ok=True)
        self.metadata_file = self.pdf_dir.parent / "metadata.json"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; BioRxivDownloader/1.0)'
        })

    def search_papers(
        self,
        keywords: List[str],
        max_results: int = 20
    ) -> List[Dict]:
        """Search bioRxiv papers by keywords using arXiv API."""
        papers = []
        # Search in title and abstract, filter for bioRxiv (q-bio or 10.1101 DOI)
        search_query = ' AND '.join([f'all:{kw}' for kw in keywords])
        # Add bioRxiv filter
        full_query = f'({search_query}) AND (all:bioRxiv OR all:q-bio)'

        print(f"Searching for: {full_query}")
        print(f"Max results: {max_results}\n")

        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=full_query,
                max_results=max_results * 2,  # Get more to filter
                sort_by=arxiv.SortCriterion.SubmittedDate
            )

            for result in client.results(search):
                # Filter for bioRxiv papers (DOI starts with 10.1101 or q-bio category)
                is_biorxiv = (
                    (result.doi and result.doi.startswith('10.1101')) or
                    any('q-bio' in str(cat) for cat in result.categories)
                )
                
                if is_biorxiv:
                    paper = {
                        'title': result.title,
                        'doi': result.doi,
                        'published': result.published.isoformat(),
                        'summary': result.summary,
                        'authors': [author.name for author in result.authors],
                        'pdf_url': result.pdf_url,
                        'arxiv_id': result.get_short_id()
                    }
                    papers.append(paper)

        except Exception as e:
            print(f"Error searching papers: {e}")

        return papers

    def download_pdf(
        self,
        paper: Dict,
        timeout: int = 60
    ) -> Optional[Path]:
        """Download PDF for a paper."""
        pdf_url = paper.get('pdf_url')
        doi = paper.get('doi', '') or paper.get('arxiv_id', '')

        if not pdf_url:
            print(f"  No PDF URL for: {paper['title'][:50]}...")
            return None

        # Create filename from DOI or arxiv_id
        filename = hashlib.md5(doi.encode()).hexdigest() + ".pdf"
        pdf_path = self.pdf_dir / filename

        if pdf_path.exists():
            print(f"  Already cached: {pdf_path.name}")
            return pdf_path

        try:
            print(f"  Downloading: {pdf_url}")
            response = self.session.get(pdf_url, stream=True, timeout=timeout)
            response.raise_for_status()

            # Check if it's actually a PDF
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' not in content_type.lower():
                print(f"  Warning: Content-Type is {content_type}, skipping")
                return None

            with open(pdf_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"  Saved: {pdf_path.name}")
            return pdf_path

        except Exception as e:
            print(f"  Error downloading: {e}")
            return None

    def load_existing_metadata(self) -> List[Dict]:
        """Load existing metadata if available."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return []

    def save_metadata(self, papers: List[Dict]):
        """Save paper metadata to JSON file."""
        existing = self.load_existing_metadata()
        existing_dois = {p.get('doi') for p in existing if p.get('doi')}

        # Add new papers only
        new_papers = [
            p for p in papers
            if p.get('doi') not in existing_dois
        ]

        existing.extend(new_papers)

        with open(self.metadata_file, 'w') as f:
            json.dump(existing, f, indent=2)

        print(f"\nSaved metadata to {self.metadata_file}")
        print(f"Total papers in metadata: {len(existing)}")

    def download_by_keywords(
        self,
        keywords: List[str],
        max_papers: int = 20
    ) -> List[Dict]:
        """Download papers matching keywords."""
        papers = self.search_papers(keywords, max_results=max_papers)
        downloaded = []

        print(f"\nFound {len(papers)} bioRxiv papers")
        print("Downloading PDFs...\n")

        for i, paper in enumerate(papers, 1):
            print(f"[{i}/{len(papers)}] {paper['title'][:60]}...")
            pdf_path = self.download_pdf(paper)

            if pdf_path:
                paper['pdf_path'] = str(pdf_path)
                downloaded.append(paper)

            # Be respectful to the server
            time.sleep(1)

        self.save_metadata(downloaded)
        return downloaded

    def download_by_category(
        self,
        category: str,
        max_papers: int = 20
    ) -> List[Dict]:
        """Download papers from a specific medical category."""
        if category not in MEDICAL_KEYWORDS:
            print(f"Unknown category: {category}")
            print(f"Available: {', '.join(MEDICAL_KEYWORDS.keys())}")
            return []

        keywords = MEDICAL_KEYWORDS[category]
        print(f"\n{'='*50}")
        print(f"Category: {category}")
        print(f"Keywords: {', '.join(keywords[:5])}...")
        print(f"{'='*50}\n")

        return self.download_by_keywords(keywords, max_papers)


def main():
    parser = argparse.ArgumentParser(
        description='Download medical PDFs from bioRxiv'
    )
    parser.add_argument(
        '--keywords', '-k',
        type=str,
        help='Comma-separated keywords (e.g., cancer,heart,brain)'
    )
    parser.add_argument(
        '--category', '-c',
        type=str,
        choices=list(MEDICAL_KEYWORDS.keys()),
        help='Medical category to search'
    )
    parser.add_argument(
        '--max-papers', '-n',
        type=int,
        default=10,
        help='Maximum papers to download (default: 10)'
    )
    parser.add_argument(
        '--pdf-dir',
        type=str,
        default='./pdfs',
        help='Directory to save PDFs (default: ./pdfs)'
    )

    args = parser.parse_args()

    downloader = BioRxivDownloader(pdf_dir=args.pdf_dir)

    if args.category:
        downloader.download_by_category(args.category, args.max_papers)
    elif args.keywords:
        keywords = [k.strip() for k in args.keywords.split(',')]
        downloader.download_by_keywords(keywords, args.max_papers)
    else:
        # Default: search for common medical terms
        print("No keywords or category specified.")
        print("Using default medical keywords: cancer, heart, brain\n")
        downloader.download_by_keywords(
            ['cancer', 'heart', 'brain'],
            args.max_papers
        )

    print(f"\n{'='*50}")
    print("Download complete!")
    print(f"PDFs saved to: {downloader.pdf_dir.absolute()}")
    print(f"Metadata saved to: {downloader.metadata_file}")
    print(f"{'='*50}")


if __name__ == '__main__':
    main()
