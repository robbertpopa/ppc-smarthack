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

resource "azurerm_container_app_environment" "env" {
  name                       = "cae-${local.name}"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  tags                       = local.tags
}

resource "azurerm_container_app_environment_storage" "artifacts" {
  name                         = "artifacts"
  container_app_environment_id = azurerm_container_app_environment.env.id
  account_name                 = azurerm_storage_account.data.name
  share_name                   = azurerm_storage_share.artifacts.name
  access_key                   = azurerm_storage_account.data.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name}-api"
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"
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
        value = "mock"
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
