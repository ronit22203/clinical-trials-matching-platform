# RunPod Terraform

`infra/runpod/` rents and releases one GPU pod from a template you already saved in the RunPod UI. `terraform apply` starts billing. `terraform destroy`, or `pod_enabled = false` then apply, deletes the pod.

The provider is [`decentralized-infrastructure/runpod`](https://registry.terraform.io/providers/decentralized-infrastructure/runpod/latest/docs) `~> 1.0`. It can create pods, network volumes, and serverless endpoints. It cannot create or edit templates. Image, container disk, the `/workspace` volume, and environment variables stay on the saved template. A template edit in the UI is picked up only when the pod is replaced. Pods cannot be updated in place.

Once the pod is up, follow [Production Startup](../guides/prod-startup.md).

## What Terraform sets

| Setting | Value |
|---------|-------|
| Compute | GPU, `interruptible = false` |
| GPU | `NVIDIA L4`, count 1 |
| Cloud | `SECURE` |
| Ports | `22/tcp`, `5173/http`, `8000/http`, `8002/http` |
| Name | `healthcare-platform` |

`8001` is RunPod’s own nginx. Ingestion listens on `8002`. The Blueprint UI is `https://<pod-id>-5173.proxy.runpod.net`.

The pod volume mounted at `/workspace` survives a stop and start. It is deleted with the pod. That matches the template field “persistent storage tied to the Pod’s lifecycle” and is the disk [`docker/entrypoint.sh`](../../docker/entrypoint.sh) clones into.

## Files

| File | Role |
|------|------|
| `infra/runpod/versions.tf` | Terraform `>= 1.5`, provider pin |
| `infra/runpod/providers.tf` | Reads `RUNPOD_API_KEY`. No key in the file |
| `infra/runpod/variables.tf` | Template name and deploy overrides |
| `infra/runpod/pod.tf` | Template lookup and `runpod_pod.platform` |
| `infra/runpod/outputs.tf` | Pod id, public IP, hourly cost, Blueprint URL |
| `infra/runpod/terraform.tfvars.example` | Copy to `terraform.tfvars` |

`pod.tf` loads every template and keeps the one whose name matches `template_name` and is not serverless. If that name matches nothing, the plan lists the private pod templates on the account. If it matches more than one, rename one of them in the RunPod UI.

## Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `template_name` | required | Exact name of the saved pod template |
| `pod_enabled` | `true` | `false` deletes the pod and leaves the template |
| `gpu_type_ids` | `["NVIDIA L4"]` | GPU types, in preference order |
| `cloud_type` | `SECURE` | `SECURE` or `COMMUNITY` |
| `ports` | `22/tcp`, `5173/http`, `8000/http`, `8002/http` | Add `"PORT/udp"` only if you need UDP |
| `data_center_ids` | `[]` | Empty lets RunPod place the pod by availability |

Do not put `AUTH_*` or the API key in `.tf` or `terraform.tfvars`. Set secrets on the template. Export the API key in the shell.

## Commands

```bash
cd infra/runpod
cp terraform.tfvars.example terraform.tfvars   # set template_name
export RUNPOD_API_KEY=...                       # RunPod Settings → API Keys
terraform init
terraform apply                                 # spin up
terraform apply -var='pod_enabled=false'        # spin down
terraform destroy                               # delete the pod
```

State stays on the machine. `.terraform/`, `*.tfstate`, and `*.tfvars` are gitignored. `terraform.tfvars.example` and `.terraform.lock.hcl` are committed.

## Outputs

| Output | Meaning |
|--------|---------|
| `pod_id` | RunPod pod id. Null when the pod is disabled |
| `public_ip` | Public IP, when the provider returns one |
| `cost_per_hr` | Credit cost per hour |
| `blueprint_url` | `https://<pod-id>-5173.proxy.runpod.net` |

## Not in this stack

- Creating or editing the RunPod template
- A network volume that survives `terraform destroy` (that disk is separate from the pod volume, and it pins the pod to one data center)
- Remote state
- Building or pushing `Dockerfile.runpod`
