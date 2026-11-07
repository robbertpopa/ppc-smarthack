locals {
  name = "${var.prefix}-${var.environment}"
  flat = replace(local.name, "-", "")
  tags = {
    project     = "ppc-smarthack"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_registry" "acr" {
  name                = "acr${local.flat}${random_string.suffix.result}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_storage_account" "data" {
  name                            = "st${local.flat}${random_string.suffix.result}"
  location                        = azurerm_resource_group.rg.location
  resource_group_name             = azurerm_resource_group.rg.name
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_storage_share" "artifacts" {
  name               = "artifacts"
  storage_account_id = azurerm_storage_account.data.id
  quota              = 50
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${local.name}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azapi_resource" "env" {
  type                      = "Microsoft.App/managedEnvironments@2026-03-02-preview"
  name                      = "cae-${local.name}-std"
  parent_id                 = azurerm_resource_group.rg.id
  location                  = azurerm_resource_group.rg.location
  tags                      = local.tags
  schema_validation_enabled = false

  body = {
    properties = {
      environmentMode = "WorkloadProfiles"
      workloadProfiles = [
        { name = "Consumption", workloadProfileType = "Consumption" }
      ]
      appLogsConfiguration = {
        destination = "log-analytics"
        logAnalyticsConfiguration = {
          customerId = azurerm_log_analytics_workspace.logs.workspace_id
          sharedKey  = azurerm_log_analytics_workspace.logs.primary_shared_key
        }
      }
    }
  }

}

resource "azurerm_container_app_environment_storage" "artifacts" {
  name                         = "artifacts"
  container_app_environment_id = azapi_resource.env.id
  account_name                 = azurerm_storage_account.data.name
  share_name                   = azurerm_storage_share.artifacts.name
  access_key                   = azurerm_storage_account.data.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name}-api"
  container_app_environment_id = azapi_resource.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = var.demo_token == "" ? [] : [1]
    content {
      name  = "demo-token"
      value = var.demo_token
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    # One replica only: the action log is a single append-only file on a shared volume.
    min_replicas = 1
    max_replicas = 1

    volume {
      name          = "artifacts"
      storage_type  = "AzureFile"
      storage_name  = azurerm_container_app_environment_storage.artifacts.name
      mount_options = "uid=1000,gid=1000,file_mode=0660,dir_mode=0770"
    }

    container {
      name   = "api"
      image  = "${azurerm_container_registry.acr.login_server}/ppc-smarthack:${var.image_tag}"
      cpu    = var.app_cpu
      memory = var.app_memory

      env {
        name  = "APP_ENV"
        value = "cloud"
      }
      env {
        name  = "SOURCE"
        value = var.agent_source
      }
      env {
        name  = "SCENARIO"
        value = var.scenario
      }
      env {
        name  = "DATA_DIR"
        value = "/data/artifacts/data"
      }
      env {
        name  = "LOG_URI"
        value = "/data/artifacts/logs/actions.jsonl"
      }
      env {
        name  = "ARTIFACT_URI"
        value = "/data/artifacts"
      }
      dynamic "env" {
        for_each = var.demo_token == "" ? [] : [1]
        content {
          name        = "DEMO_TOKEN"
          secret_name = "demo-token"
        }
      }

      volume_mounts {
        name = "artifacts"
        path = "/data/artifacts"
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

resource "azurerm_container_app" "ui" {
  name                         = "ca-${local.name}-ui"
  container_app_environment_id = azapi_resource.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name    = "ui"
      image   = "${azurerm_container_registry.acr.login_server}/ppc-smarthack:${var.image_tag}"
      cpu     = var.ui_cpu
      memory  = var.ui_memory
      command = ["uvicorn", "src.ui.app:app", "--host", "0.0.0.0", "--port", "8080"]

      env {
        name  = "APP_ENV"
        value = "cloud"
      }
      env {
        name  = "API_URL"
        value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/"
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

resource "azurerm_container_app_job" "batch" {
  name                         = "caj-${local.name}-batch"
  location                     = azurerm_resource_group.rg.location
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azapi_resource.env.id
  replica_timeout_in_seconds   = var.job_timeout_seconds
  workload_profile_name        = "Consumption"
  replica_retry_limit          = 0
  tags                         = local.tags

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.acr.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  template {
    volume {
      name          = "artifacts"
      storage_type  = "AzureFile"
      storage_name  = azurerm_container_app_environment_storage.artifacts.name
      mount_options = "uid=1000,gid=1000,file_mode=0660,dir_mode=0770"
    }

    container {
      name    = "batch"
      image   = "${azurerm_container_registry.acr.login_server}/ppc-smarthack:${var.image_tag}"
      cpu     = var.job_cpu
      memory  = var.job_memory
      command = ["python", "-m", "src.smoke"]

      env {
        name  = "APP_ENV"
        value = "cloud"
      }
      env {
        name  = "ARTIFACT_URI"
        value = "/data/artifacts"
      }
      env {
        name  = "DATA_DIR"
        value = "/data/artifacts/data"
      }

      volume_mounts {
        name = "artifacts"
        path = "/data/artifacts"
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}

resource "azurerm_consumption_budget_resource_group" "rg" {
  count             = length(var.budget_contact_emails) > 0 ? 1 : 0
  name              = "budget-${local.name}"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start_date
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.budget_contact_emails
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = var.budget_contact_emails
  }
}
