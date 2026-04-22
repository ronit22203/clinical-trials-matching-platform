# Cloud Storage Setup

This guide covers the one-time setup of the two storage providers used by this pipeline.

> **Prerequisites:** AWS CLI configured with a profile that has S3 permissions. Azure CLI installed and logged in via `az login`.

---

## AWS S3 (Primary)

### 1. Create the bucket

```bash
aws s3api create-bucket \
    --bucket clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3 \
    --region ap-south-1 \
    --create-bucket-configuration LocationConstraint=ap-south-1
```

This creates an S3 Express One Zone directory bucket in `ap-south-1a`.

### 2. Block public access

```bash
aws s3api put-public-access-block \
    --bucket clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3 \
    --public-access-block-configuration \
        BlockPublicAcls=true,IgnorePublicAcls=true,\
        BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### 3. Enable versioning

```bash
aws s3api put-bucket-versioning \
    --bucket clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3 \
    --versioning-configuration Status=Enabled
```

### 4. Set lifecycle rule (Glacier after 30 days)

Create `s3-lifecycle.json`:

```json
{
  "Rules": [
    {
      "Id": "MoveToGlacier",
      "Status": "Enabled",
      "Prefix": "raw/",
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "GLACIER"
        }
      ]
    }
  ]
}
```

Apply it:

```bash
aws s3api put-bucket-lifecycle-configuration \
    --bucket clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3 \
    --lifecycle-configuration file://s3-lifecycle.json
```

### 5. Create folder structure

```bash
BUCKET=clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3

aws s3api put-object --bucket $BUCKET --key raw/clinical_trials/
aws s3api put-object --bucket $BUCKET --key raw/biorxiv/
aws s3api put-object --bucket $BUCKET --key raw/medrxiv/
aws s3api put-object --bucket $BUCKET --key metadata/
aws s3api put-object --bucket $BUCKET --key manifests/
```

### 6. Verify

```bash
aws s3api list-directory-buckets --region ap-south-1
```

---

## Azure Blob Storage (Fallback)

### 1. Create a resource group

```bash
az group create \
    --name clinical-trials-pdfs-prod-fallback \
    --location centralindia
```

### 2. Create a storage account

```bash
az storage account create \
    --name <your-storage-account> \
    --resource-group clinical-trials-pdfs-prod-fallback \
    --location centralindia \
    --sku Standard_LRS \
    --kind StorageV2
```

### 3. Create the container (private)

```bash
az storage container create \
    --name clinical-trials-fallback \
    --account-name <your-storage-account> \
    --auth-mode login

az storage container set-permission \
    --name clinical-trials-fallback \
    --account-name <your-storage-account> \
    --public-access off \
    --auth-mode login
```

### 4. Retrieve the connection string

```bash
az storage account show-connection-string \
    --name <your-storage-account> \
    --resource-group clinical-trials-pdfs-prod-fallback \
    --query connectionString \
    --output tsv
```

Store the output in your `.env` file as `AZURE_STORAGE_CONNECTION_STRING`. Do not commit this value.

---

## Configuration

After provisioning, update the config files:

**`config/data-acquisition/storage/aws_s3.yaml`:**
```yaml
bucket: clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3
region: ap-south-1
prefix: raw/clinical_trials/
versioning: enabled
lifecycle: glacier-after-30-days
```

**`config/data-acquisition/storage/azure_blob.yaml`:**
```yaml
container: clinical-trials-fallback
account: <your-storage-account>
prefix: raw/clinical_trials/
```

**`.env`** (not committed):
```env
AWS_PROFILE=clinical-trials-fetcher
AZURE_STORAGE_CONNECTION_STRING=<output from step 4 above>
```

---

## Verification

### Test S3 upload

```bash
aws s3 cp test.pdf \
    s3://clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3/raw/clinical_trials/test.pdf

aws s3 ls \
    s3://clinical-trials-pdfs-prod-ap-south-1--aps1-az1--x-s3/raw/clinical_trials/
```

### Test Azure upload

```bash
az storage blob upload \
    --container-name clinical-trials-fallback \
    --file test.pdf \
    --name raw/clinical_trials/test.pdf \
    --account-name <your-storage-account> \
    --auth-mode login

az storage blob list \
    --container-name clinical-trials-fallback \
    --prefix raw/clinical_trials/ \
    --account-name <your-storage-account> \
    --auth-mode login \
    --output table
```

### Run a dry fetch

```bash
python scripts/fetch_pdfs.py \
    --source clinical_trials \
    --query "diabetes" \
    --max-pdfs 1 \
    --dry-run
```

### Run a small live batch

```bash
python scripts/fetch_pdfs.py \
    --source clinical_trials \
    --query "diabetes" \
    --max-pdfs 5 \
    --metrics-enabled
```

