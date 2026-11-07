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

variable "app_cpu" {
  type    = number
  default = 0.5
}

variable "app_memory" {
  type    = string
  default = "1Gi"
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
