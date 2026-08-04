resource "google_storage_bucket" "eval_evidence" {
  name                        = "${var.project_id}-eval-evidence"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  retention_policy {
    retention_period = 31536000
  }

  lifecycle_rule {
    condition {
      age = 730
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}
