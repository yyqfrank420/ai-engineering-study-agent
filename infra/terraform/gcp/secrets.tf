resource "google_secret_manager_secret" "app" {
  for_each  = local.secret_bindings
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "app" {
  for_each = {
    for env_name in var.enabled_secret_names : env_name => env_name
    if contains(keys(local.secret_bindings), env_name)
  }

  secret      = google_secret_manager_secret.app[each.key].id
  secret_data = var.secret_values[each.key]
}
