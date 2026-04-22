# Storage Tests

Integration and unit tests for multi-cloud storage providers.

## Structure

```
tests/
├── storage/
│   ├── conftest.py           # Pytest fixtures and shared utilities
│   ├── test_utils.py         # Test client utilities for AWS, Azure, Local
│   ├── test_aws_s3.py        # AWS S3 integration tests
│   ├── test_azure_blob.py    # Azure Blob Storage integration tests
│   ├── test_local_fallback.py # Local filesystem tests
│   └── test_storage_integration.py # Multi-cloud integration tests
└── __init__.py
```

## Running Tests

### All Storage Tests
```bash
pytest tests/storage/ -v
```

### By Provider
```bash
# AWS S3 only
pytest tests/storage/test_aws_s3.py -v
pytest -m aws -v

# Azure Blob only
pytest tests/storage/test_azure_blob.py -v
pytest -m azure -v

# Local filesystem only
pytest tests/storage/test_local_fallback.py -v
pytest -m local -v
```

### Integration vs Unit Tests
```bash
# Integration tests (require cloud credentials)
pytest -m integration -v

# Unit tests only (no credentials needed)
pytest -m "not integration" -v
```

### With Coverage
```bash
pytest tests/storage/ --cov=src --cov-report=html
```

## Test Markers

| Marker | Description |
|--------|-------------|
| `aws` | AWS S3 storage tests |
| `azure` | Azure Blob Storage tests |
| `local` | Local filesystem tests |
| `storage` | All storage tests |
| `integration` | Tests requiring cloud credentials |
| `slow` | Slow running tests |

## Configuration

### Environment Variables

Set these before running integration tests:

```bash
# AWS
export AWS_PROFILE=clinical-trials-fetcher
export AWS_DEFAULT_REGION=ap-south-1

# Azure
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=..."
export AZURE_STORAGE_ACCOUNT=$AZURE_STORAGE_ACCOUNT
```

### Config Files

Tests load configuration from:
- `config/data-acquisition/storage/aws_s3.yml`
- `config/data-acquisition/storage/azure_blob.yml`
- `config/data-acquisition/storage/local_fallback.yml`
- `config/data-acquisition/storage/providers.yml`

## Test Data

Tests use generated test data with unique prefixes to avoid conflicts:
- Test blobs/objects: `test-{uuid}/...`
- Test metadata: Generated with unique NCT IDs
- All test data is cleaned up after each test

## Storage Providers

### AWS S3 (Primary)
- Bucket: `clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3`
- Region: `ap-south-1`
- Type: S3 Express One Zone (Directory Bucket)

### Azure Blob (Fallback)
- Account: `$AZURE_STORAGE_ACCOUNT`
- Container: `clinical-trials-fallback`
- Region: `centralindia`
- Resource Group: `$AZURE_STORAGE_RESOURCE_GROUP`

### Local Fallback (Catastrophic)
- Base Directory: `/data/graphrag/fallback`
- Retention: 7 days
- Triggers: Both clouds unavailable, budget exhausted, network isolation

## Test Utilities

The `test_utils.py` module provides:

- `StorageTestUtils`: Common test utilities (MD5, key generation, metadata)
- `AWSTestClient`: S3 test operations
- `AzureTestClient`: Azure Blob test operations
- `LocalTestClient`: Local filesystem test operations
- `StorageTestResult`: Standardized test result format
- `StorageTestReport`: Aggregated test reporting

## Example Test

```python
import pytest
from tests.storage.test_utils import AWSTestClient, StorageTestReport

@pytest.mark.aws
@pytest.mark.integration
def test_upload_download(aws_s3_config, sample_pdf_content):
    """Test upload and download cycle."""
    bucket = aws_s3_config["buckets"]["clinical-trials-pdfs"]["name"]
    client = AWSTestClient(
        profile=aws_s3_config["profile"],
        region=aws_s3_config["region"],
        bucket=bucket,
    )
    
    if not client.is_available:
        pytest.skip("AWS credentials not available")
    
    # Upload
    upload_result = client.upload_object("test/key.pdf", sample_pdf_content)
    assert upload_result.success
    
    # Download
    download_result = client.download_object("test/key.pdf")
    assert download_result.success
    
    # Cleanup
    client.delete_object("test/key.pdf")
```

## Troubleshooting

### "Credentials not available"
Ensure environment variables are set or AWS profile exists:
```bash
aws configure list-profiles
az account show
```

### "Bucket/Container not found"
Verify resources exist:
```bash
# AWS
aws s3api head-bucket --bucket clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3

# Azure
az storage container exists --name clinical-trials-fallback --account-name $AZURE_STORAGE_ACCOUNT
```

### Test cleanup failures
Tests attempt to clean up after themselves, but if cleanup fails, manually remove test objects:
```bash
# AWS
aws s3 rm s3://clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3/test- --recursive

# Azure
az storage blob delete-batch --source clinical-trials-fallback --pattern test-*
```
