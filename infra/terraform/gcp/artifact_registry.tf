resource "google_artifact_registry_repository" "backend" {
  location      = var.region
  repository_id = var.artifact_registry_repository
  description   = "Backend images for the AI study agent."
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}
