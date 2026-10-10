variable "template_name" {
  description = "Name of the saved RunPod pod template. Must match exactly one non-serverless template."
  type        = string
}

variable "pod_enabled" {
  description = "Create the GPU pod. Set to false and apply to tear the pod down without destroying the template."
  type        = bool
  default     = true
}

variable "gpu_type_ids" {
  description = "RunPod GPU types the pod may rent, in preference order."
  type        = list(string)
  default     = ["NVIDIA L4"]
}

variable "cloud_type" {
  description = "SECURE for Secure Cloud, COMMUNITY for Community Cloud."
  type        = string
  default     = "SECURE"

  validation {
    condition     = contains(["SECURE", "COMMUNITY"], var.cloud_type)
    error_message = "cloud_type must be SECURE or COMMUNITY."
  }
}

variable "ports" {
  description = "Ports exposed on the pod, formatted as port/protocol. Add a PORT/udp entry only if you need UDP."
  type        = list(string)
  default     = ["22/tcp", "5173/http", "8000/http", "8002/http"]
}

variable "data_center_ids" {
  description = "Optional RunPod data center IDs. Empty lets RunPod place the pod by availability."
  type        = list(string)
  default     = []
}

variable "volume_in_gb" {
  description = "Persistent pod volume mounted at /workspace, in GB. Deleted with the pod. The provider default is 20, which is too small for the CUDA wheels."
  type        = number
  default     = 100
}

variable "container_disk_in_gb" {
  description = "Ephemeral container disk, in GB. Wiped when the pod restarts."
  type        = number
  default     = 50
}
