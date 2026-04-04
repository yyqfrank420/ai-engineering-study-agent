variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "europe-west2"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "agent-backend"
}

variable "artifact_registry_repository" {
  description = "Artifact Registry repository name."
  type        = string
  default     = "agent-backend"
}

variable "image_name" {
  description = "Backend image name."
  type        = string
  default     = "agent-backend"
}

variable "image_tag" {
  description = "Container image tag to deploy."
  type        = string
  default     = "latest"
}

variable "frontend_origin" {
  description = "Allowed frontend origin for backend CORS."
  type        = string
}

variable "cpu" {
  description = "Cloud Run CPU limit."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Cloud Run memory limit."
  type        = string
  default     = "4Gi"
}

variable "min_instance_count" {
  description = "Cloud Run minimum instances."
  type        = number
  default     = 0
}

variable "max_instance_count" {
  description = "Cloud Run maximum instances."
  type        = number
  default     = 2
}

variable "container_concurrency" {
  description = "Max concurrent requests per instance."
  type        = number
  default     = 4
}

variable "request_timeout_seconds" {
  description = "Cloud Run request timeout in seconds."
  type        = number
  default     = 300
}

variable "allow_unauthenticated" {
  description = "Whether Cloud Run should be publicly invokable."
  type        = bool
  default     = true
}

variable "faiss_artifact_timeout_s" {
  description = "Backend timeout for downloading the FAISS bundle."
  type        = number
  default     = 120
}

variable "env_vars" {
  description = "Non-secret environment variables for the backend."
  type        = map(string)
  default     = {}
}

variable "secret_values" {
  description = "Secret values keyed by backend env var name. Optional but Terraform-managed if supplied."
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "enabled_secret_names" {
  description = "Non-sensitive set of backend env var names whose secret versions should be created from secret_values."
  type        = set(string)
  default     = []
}

variable "container_image" {
  description = "Full container image path override. Defaults to derived Artifact Registry path. Set to a public placeholder image on first apply before the real image is built."
  type        = string
  default     = ""
}

variable "billing_account_id" {
  description = "Optional billing account ID for budget alerts."
  type        = string
  default     = ""
}

variable "monthly_budget_amount" {
  description = "Optional monthly budget amount. Set to 0 to disable budget resource."
  type        = number
  default     = 0
}
