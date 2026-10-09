output "pod_id" {
  description = "RunPod pod id. Null when the pod is disabled."
  value       = var.pod_enabled ? runpod_pod.platform[0].id : null
}

output "public_ip" {
  description = "Public IP of the pod, when the provider returns one."
  value       = var.pod_enabled ? runpod_pod.platform[0].public_ip : null
}

output "cost_per_hr" {
  description = "RunPod credit cost per hour for the running pod."
  value       = var.pod_enabled ? runpod_pod.platform[0].cost_per_hr : null
}

output "blueprint_url" {
  description = "Blueprint UI through the RunPod HTTPS proxy."
  value       = var.pod_enabled ? "https://${runpod_pod.platform[0].id}-5173.proxy.runpod.net" : null
}
