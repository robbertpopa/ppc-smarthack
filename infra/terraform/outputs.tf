output "app_url" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "storage_account" {
  value = azurerm_storage_account.data.name
}

output "artifacts_share" {
  value = azurerm_storage_share.artifacts.name
}

output "batch_job" {
  value = azurerm_container_app_job.batch.name
}
