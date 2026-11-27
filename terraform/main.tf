terraform {
  required_providers {
    aiven = {
      source  = "aiven/aiven"
      version = "~> 4.0"
    }
  }

  # Sem backend remoto: o state fica no runner do GitHub Actions e some no fim
  # do job. Por isso o infra.yml importa o serviço antes do plan quando ele
  # já existe (senão a segunda execução tenta criar de novo e falha).
}

provider "aiven" {
  api_token = var.aiven_api_token
}

# Plano free: sem cloud_name, a Aiven escolhe uma região elegível.
# Cuidado: "hobbyist" NÃO é gratuito, é cobrado.
resource "aiven_pg" "dashboard_db" {
  project                 = var.aiven_project
  plan                    = var.pg_plan
  service_name            = var.service_name
  maintenance_window_dow  = "sunday"
  maintenance_window_time = "03:00:00"
}
