"""
Medical keyword categories for targeted bioRxiv paper searches.
"""

MEDICAL_KEYWORDS = {
    'oncology': [
        'cancer', 'tumor', 'oncology', 'carcinoma', 'metastasis',
        'chemotherapy', 'neoplasm', 'malignant'
    ],
    'cardiology': [
        'heart', 'cardiac', 'cardiovascular', 'myocardial', 'arrhythmia',
        'hypertension', 'atherosclerosis', 'heart failure'
    ],
    'neurology': [
        'brain', 'neural', 'neuro', 'stroke', 'alzheimer', 'parkinson',
        'epilepsy', 'dementia', 'cognitive'
    ],
    'infectious_disease': [
        'virus', 'bacterial', 'infection', 'pandemic', 'covid',
        'pathogen', 'antibiotic', 'viral', 'epidemic'
    ],
    'immunology': [
        'immune', 'antibody', 'vaccine', 'immunotherapy', 'cytokine',
        'autoimmune', 'inflammation', 'T-cell', 'B-cell'
    ],
    'genetics': [
        'mutation', 'gene', 'genetic', 'variant', 'inherited',
        'genome', 'CRISPR', 'genomic', 'hereditary'
    ],
    'pharmacology': [
        'drug', 'therapeutic', 'treatment', 'compound', 'pharmacology',
        'dosage', 'efficacy', 'clinical trial'
    ],
    'diagnostics': [
        'biomarker', 'diagnostic', 'imaging', 'detection', 'screening',
        'MRI', 'CT scan', 'radiology', 'pathology'
    ],
    'epidemiology': [
        'epidemiology', 'prevalence', 'incidence', 'cohort', 'population',
        'risk factor', 'mortality', 'morbidity', 'surveillance'
    ],
    'public_health': [
        'public health', 'healthcare', 'policy', 'intervention',
        'prevention', 'health outcomes', 'global health'
    ]
}

# Flat list of all medical keywords for broad searches
ALL_MEDICAL_KEYWORDS = list(set(
    kw for keywords in MEDICAL_KEYWORDS.values() for kw in keywords
))
