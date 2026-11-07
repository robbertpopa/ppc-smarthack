variable "subscription_id" {
  description = "Azure subscription. Null falls back to ARM_SUBSCRIPTION_ID."
  type        = string
  default     = null
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "germanywestcentral"
}

variable "prefix" {
  description = "Short lowercase prefix for resource names (letters and digits only)."
  type        = string
  default     = "ppcsmart"
}

variable "environment" {
  description = "Environment name, used in resource names."
  type        = string
  default     = "demo"
}

variable "image_tag" {
  description = "Tag of the ppc-smarthack image in the registry."
  type        = string
  default     = "latest"
}

variable "agent_source" {
  description = "Where the agent gets its forecasts: mock, or model (needs labels and trained models on the share)."
  type        = string
  default     = "mock"

  validation {
    condition     = contains(["mock", "model"], var.agent_source)
    error_message = "agent_source must be mock or model."
  }
}

variable "scenario" {
  description = "Scenario (A, B or B-VAR) used when source is model."
  type        = string
  default     = "A"
}

variable "ui_cpu" {
  type    = number
  default = 0.25
}

variable "ui_memory" {
  type    = string
  default = "0.5Gi"
}

variable "app_cpu" {
  type    = number
  default = 0.5
}

variable "app_memory" {
  type    = string
  default = "1Gi"
}

variable "job_cpu" {
  description = "CPU of the batch job (labels, training, evaluation)."
  type        = number
  default     = 1.0
}

variable "job_memory" {
  description = "Memory of the batch job; 1.0 CPU needs 2Gi on the consumption plan."
  type        = string
  default     = "2Gi"
}

variable "job_timeout_seconds" {
  description = "A batch run is stopped after this long."
  type        = number
  default     = 3600
}

variable "demo_token" {
  description = "Token required for write endpoints of the public demo. Empty disables the check."
  type        = string
  default     = ""
  sensitive   = true
}

variable "budget_amount" {
  description = "Monthly budget in the subscription currency."
  type        = number
  default     = 50
}

variable "budget_contact_emails" {
  description = "Emails notified at 80% of the budget. Empty skips the budget."
  type        = list(string)
  default     = []
}

variable "budget_start_date" {
  description = "First day of a month, RFC 3339."
  type        = string
  default     = "2026-11-01T00:00:00Z"
}
