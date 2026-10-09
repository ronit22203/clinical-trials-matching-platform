data "runpod_templates" "all" {}

locals {
  platform_template = one([
    for t in data.runpod_templates.all.templates : t
    if t.name == var.template_name && !t.is_serverless
  ])
}

resource "runpod_pod" "platform" {
  count         = var.pod_enabled ? 1 : 0
  name          = "healthcare-platform"
  template_id   = local.platform_template.id
  compute_type  = "GPU"
  cloud_type    = var.cloud_type
  gpu_count     = 1
  gpu_type_ids  = var.gpu_type_ids
  ports         = var.ports
  interruptible = false

  data_center_ids = length(var.data_center_ids) > 0 ? var.data_center_ids : null
}
