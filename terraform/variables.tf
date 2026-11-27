variable "aiven_api_token" {
  description = "Token de API da Aiven (Aiven Console > Profile > Authentication tokens)"
  type        = string
  sensitive   = true
}

variable "aiven_project" {
  description = "Nome do projeto na Aiven"
  type        = string
}

variable "pg_plan" {
  description = "Plano do PostgreSQL. free-1-1gb é o gratuito (1 CPU, 1 GB RAM, 1 GB disco)"
  type        = string
  default     = "free-1-1gb"
}

variable "service_name" {
  description = "Nome do serviço PostgreSQL"
  type        = string
  default     = "dashboard-pg"
}
