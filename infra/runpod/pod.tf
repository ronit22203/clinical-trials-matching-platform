data "runpod_templates" "all" {}

locals {
  pod_templates = [
    for t in data.runpod_templates.all.templates : t
    if !t.is_serverless
  ]

  own_pod_templates = [
    for t in local.pod_templates : t
    if !t.is_runpod
  ]

  matched_templates = [
    for t in local.pod_templates : t
    if t.name == var.template_name
  ]

  own_template_names = join(", ", [for t in local.own_pod_templates : "\"${t.name}\""])
}

resource "terraform_data" "template_name" {
  lifecycle {
    precondition {
      condition     = length(local.matched_templates) == 1
      error_message = (
        length(local.matched_templates) > 1
        ? "More than one pod template is named \"${var.template_name}\". Rename one of them in the RunPod UI so the name is unique."
        : "No pod template named \"${var.template_name}\". Set template_name in terraform.tfvars to one of: ${local.own_template_names}${length(local.own_pod_templates) == 0 ? " (the API returned no private pod templates)" : ""}."
      )
    }
  }
}

resource "runpod_pod" "platform" {
  count         = var.pod_enabled && length(local.matched_templates) == 1 ? 1 : 0
  name          = "healthcare-platform"
  template_id   = local.matched_templates[0].id
  # The RunPod API omits the image after create. Provider v1.0.1 then leaves
  # image_name unknown and Terraform rejects the apply, tainting a pod that
  # was already created. Setting it from the template keeps the value known.
  image_name    = local.matched_templates[0].image_name
  compute_type  = "GPU"
  cloud_type    = var.cloud_type
  gpu_count     = 1
  gpu_type_ids  = var.gpu_type_ids
  ports         = var.ports
  interruptible = false

  data_center_ids = length(var.data_center_ids) > 0 ? var.data_center_ids : null
  depends_on      = [terraform_data.template_name]
}
