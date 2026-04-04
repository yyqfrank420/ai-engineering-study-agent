resource "google_cloud_run_v2_service" "backend" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.backend.email
    timeout                          = "${var.request_timeout_seconds}s"
    max_instance_request_concurrency = var.container_concurrency

    scaling {
      max_instance_count = var.max_instance_count
    }

    containers {
      # Use explicit override if set (e.g. bootstrap placeholder), else derived Artifact Registry path.
      image = var.container_image != "" ? var.container_image : local.backend_image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      ports {
        container_port = 8080
      }

      startup_probe {
        failure_threshold     = 60
        initial_delay_seconds = 0
        period_seconds        = 5
        timeout_seconds       = 5

        http_get {
          path = "/api/prepare"
          port = 8080
        }
      }

      dynamic "env" {
        for_each = local.base_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_bindings
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app[env.key].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  lifecycle {
    ignore_changes = [
      client,
      client_version,
      traffic,
      template[0].labels,
      template[0].revision,
      template[0].containers[0].image,
      template[0].scaling[0],
    ]
  }

  depends_on = [
    google_artifact_registry_repository.backend,
    google_project_iam_member.artifact_registry_reader,
    google_project_iam_member.secret_accessor,
  ]
}
